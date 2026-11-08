# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements.txt requirements-dev.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && pip install --no-cache-dir -r requirements-dev.txt

COPY app app
COPY data data
COPY scripts scripts
COPY tests/test_api.py tests/test_api.py

RUN python scripts/build_index.py --output artifacts \
    && pytest -q tests/test_api.py \
    && python scripts/evaluate.py --artifact-dir artifacts --output artifacts/quality-report.json \
    && if python scripts/evaluate.py --artifact-dir artifacts --ranking-mode reverse \
           --output /tmp/negative-quality-report.json > /tmp/negative.log 2>&1; then \
         echo "negative quality control: reverse candidate unexpectedly passed" >&2; exit 1; \
       fi \
    && echo "negative quality control: reverse candidate blocked"



FROM ${PYTHON_IMAGE} AS runtime

ARG BUILD_REVISION=unknown
ARG APP_VERSION=1.2.0

LABEL org.opencontainers.image.title="runbook-search-api" \
      org.opencontainers.image.description="Internal runbook retrieval API with an immutable search index" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${BUILD_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ARTIFACT_DIR=/app/artifacts \
    APP_VERSION=${APP_VERSION} \
    BUILD_REVISION=${BUILD_REVISION}

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    --mount=type=bind,source=requirements.txt,target=/tmp/requirements.txt \
    pip install --no-cache-dir --no-index --find-links=/wheels -r /tmp/requirements.txt

COPY --from=builder /build/app ./app
COPY --from=builder /build/artifacts ./artifacts

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
