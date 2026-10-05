# AnswerWorks API

FastAPI backend. Install with `make install-api` (uses `uv sync --extra dev`), run from the repo
root with `make run-api`; tests with `make test-api`. OpenAPI docs are served at `/docs` and `/redoc`.

## Endpoints

- `GET /health` – 200 `{status: ok, database: ok}`, or 503 `degraded` when PostgreSQL is unreachable.
- `GET /models` – every model of every available provider (`provider`, `id`, `label`) plus the default.
- `POST /ask` – `{question, provider?, model?, stream?}` → answer with `provider`, `model`,
  `tokens_used`, `latency_ms` and `cost_usd` (`null` when the model has no pricing). Omit
  `provider`/`model` for the default. `"stream": true` returns server-sent events
  (`delta`, `done`, `error`). Transient provider errors are retried with exponential backoff; an
  invalid (blank) answer is retried once. `/ask` is a stateless stopgap and goes away once
  conversations land.

## Providers

`config/providers.yaml` declares them; `app/services/llm/` implements them:

| `type` | Adapter | Notes |
|---|---|---|
| `anthropic` | `AnthropicProvider` | needs `ANTHROPIC_API_KEY` |
| `openai` | `OpenAIProvider` | needs `OPENAI_API_KEY` |
| `openai_compatible` | `LocalProvider` | Ollama, vLLM, ...; key optional, usage may be missing |
| `fake` | `FakeProvider` | echoes the question; no network or key. Enable it for demos/UI work |

An enabled provider whose key is missing is skipped with a warning, so the API still starts; with
none available `/ask` returns 503. Per-model `pricing` (USD per 1M tokens) is optional. Timeouts,
retries and `max_output_tokens` live under `request:`. To add a backend, subclass `Provider`
(`complete`, `stream`), translate its SDK errors to `TransientProviderError`/`ProviderError`, and
register it in `registry.build_provider`.

Quick try without keys: set `default_provider: fake` and `fake.enabled: true` in a copy of the
config, then `ANSWERWORKS_CONFIG_DIR=/path/to/copy make run-api`.

## Layout

`app/main.py` (app wiring) · `app/api/` (routes, error handlers) · `app/schemas/ask.py` ·
`app/services/llm/` (provider interface, adapters, registry, chat service, retry, cost) · `app/core/config.py` (YAML/.env).
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
