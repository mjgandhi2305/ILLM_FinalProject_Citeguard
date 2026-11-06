# CiteGuard runbook

## Components

| Service | What it does | Health |
| --- | --- | --- |
| `web` | nginx: SPA + reverse proxy (SSE buffering off). Proxies `/api/`, `/healthz`, `/readyz`, `/docs` and `/openapi.json`; `/metrics` is not exposed | `GET /readyz` (through to the API and DB) |
| `api` | FastAPI; creates checks, streams events, serves exports | `GET /healthz` (liveness), `GET /readyz` (DB); Prometheus scrapes `api:8000/metrics` inside the network |
| `worker` | ARQ; runs checks, purges expired data nightly (03:17 UTC) | process up; Redis queue depth |
| `postgres` | checks, citations (JSON results), feedback, API keys | `pg_isready` |
| `redis` | job queue, HTTP + LLM cache, shared rate-limit buckets, event pub/sub | `redis-cli ping` |
| `grobid` (optional) | PDF → structured references | `GET :8070/api/isalive` |

## Routine operations

```bash
# create / rotate API keys (keys are shown once; only SHA-256 hashes are stored)
docker compose -f deploy/docker-compose.yml exec api citeguard create-key --name "lab-team" --rate-limit 30
# revoke: set revoked_at
docker compose -f deploy/docker-compose.yml exec postgres psql -U citeguard -c \
  "update api_keys set revoked_at = now() where prefix = 'cg_XXXXXXX';"

# database migrations (run automatically by the `migrate` service on `up`)
docker compose -f deploy/docker-compose.yml run --rm migrate
# new migration after a model change
cd backend && DATABASE_URL=... .venv/bin/alembic revision --autogenerate -m "describe change"

# scale workers
docker compose -f deploy/docker-compose.yml up -d --scale worker=3
```

## Metrics to watch (`GET /metrics`)

| Metric | Alert when |
| --- | --- |
| `citeguard_source_requests_total{outcome="error"}` | error ratio > 20 % for a source for 10 min (that source's circuit opens; checks degrade to fewer sources) |
| `citeguard_llm_calls_total{outcome="rate_limited"}` | sustained: raise Groq tier or lower `LLM_TPM` so the limiter paces calls |
| `citeguard_checks_total{status="failed"}` | any increase: see API/worker logs (JSON, with `request_id`) |
| `citeguard_verdicts_total` | sudden shift in distribution: often a source outage or an API change upstream |

## Failure modes

| Symptom | Likely cause | What happens / what to do |
| --- | --- | --- |
| Many `UNVERIFIABLE` with flag "Some databases unavailable" | a source is down or rate-limiting | Automatic: circuit breaker, reduced confidence. Check `/api/v1/sources/health`. Add `S2_API_KEY` if Semantic Scholar is throttling |
| Explanations say "Rule-based" while the LLM is enabled | Groq quota (TPM/TPD) exhausted or Groq down | Automatic template fallback. Check `llm.daily_budget_left` in `/api/v1/sources/health` |
| A source suddenly `unavailable` for hours | It returned `429` with a long `Retry-After` (e.g. OpenAlex's anonymous daily budget is used up) | Automatic: the source's circuit opens for the requested time (≤ 1 h, then a trial request) and checks continue with the other databases. Set `OPENALEX_API_KEY` |
| `source.deadline` warnings, slow checks | A source answers slowly or not at all | Each call has a hard 20 s deadline that covers rate-limit waits, retries and slow responses. After 5 misses in a row, the source's circuit opens for 60 s and checks continue without it. Check the source's status page; `GET /api/v1/sources/health` shows open circuits |
| DBLP always `error` | DBLP's anti-bot challenge blocks API clients | DBLP is disabled by default; leave it off |
| Checks stuck in `running` after a crash | worker died mid-check | Inline mode: interrupted checks are re-queued on start. ARQ: on SIGTERM the worker drains for 30 s, then cancels; cancelled jobs are retried. After a hard kill the job is picked up again once its in-progress lock expires. Re-runs are idempotent (per-citation upserts) |
| `413` on upload | file > `MAX_UPLOAD_MB` | raise the limit (also `client_max_body_size` in `frontend/nginx.conf`) |

## Data retention and privacy

- Uploaded documents (`check_inputs`) are deleted as soon as a check finishes or fails.
- Checks and results expire after `RETENTION_DAYS` (default 30) and are purged by a scheduled job. Users can delete them at any time (`DELETE /api/v1/checks/{id}`).
- Only reference strings and citing sentences are sent to Groq. Set `LLM_ENABLED=false` for fully local processing (scholarly lookups still send titles and authors).
- Feedback rows keep the citation text (for the evaluation set) but not the document.
