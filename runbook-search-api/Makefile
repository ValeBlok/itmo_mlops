.PHONY: venv index test quality negative build up down smoke helm-check local-check

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
DUMMY_DIGEST := sha256:$(shell printf local | shasum -a 256 | cut -d' ' -f1)

venv:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -r requirements-dev.txt

index: venv
	$(BIN)/python scripts/build_index.py --output artifacts

test: index
	$(BIN)/python -m pytest -q

quality: index
	$(BIN)/python scripts/evaluate.py --artifact-dir artifacts --output reports/quality-report.json

negative: index
	@if $(BIN)/python scripts/evaluate.py --artifact-dir artifacts --ranking-mode reverse \
		--output reports/negative-quality-report.json; then \
		echo "ERROR: bad candidate passed"; exit 1; \
	else \
		echo "Bad candidate blocked as expected"; \
	fi

helm-check:
	helm lint helm/mlops-search --set image.digest=$(DUMMY_DIGEST)
	helm template blokhina-search-staging helm/mlops-search -n mlops-students --set image.digest=$(DUMMY_DIGEST) >/dev/null
	@if helm template blokhina-search-staging helm/mlops-search >/dev/null 2>&1; then \
		echo "ERROR: chart rendered without digest"; exit 1; else echo "Empty digest rejected as expected"; fi

build:
	docker compose build search

up:
	docker compose up -d --build search

down:
	docker compose down

smoke:
	$(PYTHON) scripts/smoke_local.py

local-check: test quality negative helm-check build
