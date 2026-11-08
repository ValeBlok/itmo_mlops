import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.search import SearchEngine

SERVICE_NAME = os.getenv("SERVICE_NAME", "runbook-search-api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger(SERVICE_NAME)

engine: SearchEngine | None = None
metrics_lock = threading.Lock()
request_count = 0
search_count = 0
search_latency_seconds = 0.0


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500, examples=["rollback canary deployment"])
    limit: int = Field(default=5, ge=1, le=10)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    artifact_dir = Path(os.getenv("ARTIFACT_DIR", "artifacts"))
    engine = SearchEngine(artifact_dir, os.getenv("RANKING_MODE", "normal"))
    logger.info(json.dumps({
        "event": "service_ready",
        "service": SERVICE_NAME,
        "index_version": engine.metadata["index_version"],
        "documents": engine.metadata["documents"],
    }))
    yield
    engine = None


app = FastAPI(
    title="Runbook Search API",
    summary="Internal retrieval service for operational procedures and engineering knowledge",
    version="1.2.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def observability(request: Request, call_next):
    global request_count
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - started
    with metrics_lock:
        request_count += 1
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = f"{elapsed * 1000:.2f}"
    logger.info(json.dumps({
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": round(elapsed * 1000, 2),
    }))
    return response


@app.get("/livez", tags=["platform"])
def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health", include_in_schema=False)
def health_alias() -> dict[str, str]:
    return livez()


@app.get("/readyz", tags=["platform"])
def readyz() -> dict[str, str | int]:
    if engine is None:
        raise HTTPException(status_code=503, detail="search index is not loaded")
    return {
        "status": "ready",
        "index_version": engine.metadata["index_version"],
        "documents": engine.metadata["documents"],
    }


@app.get("/ready", include_in_schema=False)
def ready_alias() -> dict[str, str | int]:
    return readyz()


@app.get("/meta", tags=["platform"])
def metadata() -> dict[str, str | int]:
    return {
        "service": SERVICE_NAME,
        "service_version": os.getenv("APP_VERSION", "dev"),
        "build_revision": os.getenv("BUILD_REVISION", "local"),
        "image": os.getenv("IMAGE_REF", "local"),
        "image_digest": os.getenv("IMAGE_DIGEST", "local"),
        "environment": os.getenv("ENVIRONMENT", "local"),
        "index_version": engine.metadata["index_version"] if engine else "unavailable",
        "model_type": engine.metadata.get("model_type", "unknown") if engine else "unavailable",
        "ranking_mode": engine.ranking_mode if engine else "unavailable",
        "documents": engine.metadata["documents"] if engine else 0,
    }


@app.get("/version", include_in_schema=False)
def version_alias() -> dict[str, str | int]:
    return metadata()


@app.post("/v1/search", tags=["retrieval"])
def search(request: SearchRequest, http_request: Request) -> dict:
    global search_count, search_latency_seconds
    if engine is None:
        raise HTTPException(status_code=503, detail="search index is not loaded")
    started = time.perf_counter()
    results = engine.search(request.query, request.limit)
    elapsed = time.perf_counter() - started
    with metrics_lock:
        search_count += 1
        search_latency_seconds += elapsed
    return {
        "request_id": http_request.state.request_id,
        "query": request.query,
        "took_ms": round(elapsed * 1000, 3),
        "index_version": engine.metadata["index_version"],
        "results": results,
    }


@app.post("/search", include_in_schema=False)
def search_alias(request: SearchRequest, http_request: Request) -> dict:
    return search(request, http_request)


@app.get("/v1/documents/{document_id}/recommendations", tags=["retrieval"])
def recommend(document_id: str, limit: int = 3) -> dict:
    if engine is None:
        raise HTTPException(status_code=503, detail="search index is not loaded")
    try:
        results = engine.recommend(document_id, min(max(limit, 1), 10))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="document not found") from error
    return {"document_id": document_id, "index_version": engine.metadata["index_version"], "results": results}


@app.get("/recommend/{document_id}", include_in_schema=False)
def recommend_alias(document_id: str, limit: int = 3) -> dict:
    return recommend(document_id, limit)


@app.get("/metrics", tags=["platform"])
def metrics() -> Response:
    index_loaded = 1 if engine is not None else 0
    body = "\n".join([
        "# HELP http_requests_total Total HTTP requests processed.",
        "# TYPE http_requests_total counter",
        f"http_requests_total {request_count}",
        "# HELP search_requests_total Total retrieval requests processed.",
        "# TYPE search_requests_total counter",
        f"search_requests_total {search_count}",
        "# HELP search_request_duration_seconds_sum Cumulative retrieval latency.",
        "# TYPE search_request_duration_seconds_sum counter",
        f"search_request_duration_seconds_sum {search_latency_seconds:.6f}",
        "# HELP search_index_loaded Whether the search index is loaded.",
        "# TYPE search_index_loaded gauge",
        f"search_index_loaded {index_loaded}",
        "",
    ])
    return Response(content=body, media_type="text/plain; version=0.0.4")
