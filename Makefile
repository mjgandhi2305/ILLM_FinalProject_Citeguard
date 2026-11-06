.PHONY: install dev api web test lint typecheck openapi up down eval-smoke

PY := backend/.venv/bin

install:  ## Create the Python venv and install everything
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[server,ingest,dev]"
	cd frontend && npm ci

api:  ## API on :8000 (inline jobs, SQLite, auth off) — for local development
	cd backend && AUTH_ENABLED=false .venv/bin/citeguard serve --reload

web:  ## Frontend dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test

lint:
	cd backend && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests

typecheck:
	cd backend && .venv/bin/mypy src
	cd frontend && npm run typecheck

openapi:  ## Regenerate docs/openapi.json and the frontend's typed client
	cd backend && .venv/bin/python -c "import json; from citeguard.api.app import create_app; from citeguard.config import Settings; print(json.dumps(create_app(Settings(llm_enabled=False)).openapi(), indent=1))" > ../docs/openapi.json
	cd frontend && npm run gen:api

up:  ## Full stack (Postgres, Redis, API, worker, web) on :8080
	docker compose -f deploy/docker-compose.yml --env-file .env up -d --build

down:
	docker compose -f deploy/docker-compose.yml --env-file .env down

eval-smoke:  ## Small evaluation run (no LLM) — see docs/EVALUATION.md
	cd backend && .venv/bin/python -m citeguard.eval.run --dataset ../eval/datasets/citebench_dev.jsonl --no-llm --limit 40
