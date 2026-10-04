# AnswerWorks API

FastAPI backend. Install with `make install-api` (uses `uv sync --extra dev`), run from the repo
root with `make run-api`; tests with `make test-api`. OpenAPI docs are served at `/docs` and `/redoc`.

## Endpoints (imported from aie-log-analysis)

- `GET /health` – liveness check.
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
