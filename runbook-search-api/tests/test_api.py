import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ARTIFACT_DIR"] = "artifacts"

from app.main import app  # noqa: E402


def test_search_and_version() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/search",
            headers={"x-request-id": "test-request-42"},
            json={"query": "как вернуть предыдущую модель после плохого релиза", "limit": 3},
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"] == "test-request-42"
        assert response.json()["request_id"] == "test-request-42"
        assert response.json()["results"][0]["id"] == "doc-rollback"
        assert client.get("/readyz").status_code == 200
        meta = client.get("/meta").json()
        assert meta["model_type"] == "tfidf-word-char-cosine"
        assert meta["ranking_mode"] == "normal"
        for key in ("environment", "build_revision", "image_digest", "index_version"):
            assert key in meta
        assert "search_requests_total" in client.get("/metrics").text


def test_unknown_recommendation_document() -> None:
    with TestClient(app) as client:
        assert client.get("/v1/documents/missing/recommendations").status_code == 404
