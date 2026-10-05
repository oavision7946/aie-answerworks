# AnswerWorks API

FastAPI backend. Install with `make install-api` (uses `uv sync --extra dev`), run from the repo
root with `make run-api`; tests with `make test-api`. OpenAPI docs are served at `/docs` and `/redoc`.

## Endpoints (imported from aie-log-analysis)

- `GET /health` – 200 `{status: ok, database: ok}`, or 503 `degraded` when PostgreSQL is unreachable.
- `GET /models` – models listed in `config/model_costs.yaml`.
- `POST /ask` – question → answer with `tokens_used`, `latency_ms`, `cost_usd`. `"stream": true`
  returns server-sent events (`delta`, `done`, `error`). Transient OpenAI errors are retried with
  exponential backoff; invalid model output is retried once.

Requires `OPENAI_API_KEY` in `.env` (without it, `/ask` returns 503).
Settings: `llm:` section of `config/app.yaml`; pricing: `config/model_costs.yaml`.

## Layout

`app/main.py` (app wiring) · `app/api/` (routes, error handlers) · `app/schemas/ask.py` ·
`app/services/llm/` (OpenAI client + retry, streaming, cost) · `app/core/config.py` (YAML/.env).
Tests: `tests/unit`, `tests/contract` (HTTP behaviour).

## Configuration and database

- `app/core/settings.py` validates `config/*.yaml` (strict: unknown keys, a missing default provider
  or an overlap larger than the chunk size fail at startup) and reads secrets from the environment/`.env`
  (`DATABASE_URL`, `JWT_SECRET`, provider keys). Use `get_settings()`.
- Migrations: `make migrate` (`alembic upgrade head`, using `DATABASE_URL`). Create one with
  `cd api && uv run alembic revision --autogenerate -m "message"`.
- Tests run on SQLite. To also run the migration tests on PostgreSQL:
  `TEST_POSTGRES_URL=postgresql+psycopg://user:pass@localhost:5432/dbname uv run pytest tests/integration`
  (the database's `users`/`alembic_version` tables are dropped, so use a scratch database).
