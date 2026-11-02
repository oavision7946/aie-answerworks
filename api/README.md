# AnswerWorks API

FastAPI backend. Install with `make install-api` (uses `uv sync --extra dev`), run from the repo
root with `make run-api`; tests with `make test-api`. OpenAPI docs are served at `/docs` and `/redoc`.

## Endpoints

- `GET /health` – 200 `{status: ok, database: ok}`, or 503 `degraded` when PostgreSQL is unreachable.
- `POST /auth/login` – `{email, password}` → `access_token`, `refresh_token`, `expires_in`, and
  `must_change_password`. Wrong password and unknown email give the same 401; a deactivated account gets 403.
- `POST /auth/refresh` – `{refresh_token}` → a new token pair (403 for deactivated users).
- `GET /auth/me`, `POST /auth/change-password` – usable while a password change is pending.
- `POST /admin/users`, `GET /admin/users`, `PATCH /admin/users/{id}` (role, `is_active`),
  `POST /admin/users/{id}/reset-password` – admin only. You cannot deactivate or demote yourself.
- `GET /models` – every model of every available provider (`provider`, `id`, `label`) plus the default.
- `POST /ask` – `{question, provider?, model?, stream?}` → answer with `provider`, `model`,
  `tokens_used`, `latency_ms` and `cost_usd` (`null` when the model has no pricing). Omit
  `provider`/`model` for the default. `"stream": true` returns server-sent events
  (`delta`, `done`, `error`). Transient provider errors are retried with exponential backoff; an
  invalid (blank) answer is retried once. `/ask` is the stateless question-answer mode: nothing is stored.
  Use `/chat` for conversations; both are supported.
- `POST /chat` – `{message, conversation_id?, provider?, model?, stream?}` → the answer plus
  `conversation_id` and `message_id`. Without `conversation_id` a new conversation is created and
  titled from the message. The model sees the last `chat.history_messages` stored messages
  (`config/app.yaml`). Without `provider`/`model` the conversation's last model is used, then the
  default. The exchange is stored only after a successful answer. `"stream": true` returns the same
  `delta`/`done`/`error` events as `/ask`, with the ids in `done`.
- `POST /conversations` (optional `title`, `provider`, `model`), `GET /conversations`
  (`limit`, `offset`; newest activity first), `GET /conversations/{id}` (with messages),
  `PATCH /conversations/{id}` (`title`), `DELETE /conversations/{id}` (204). Every lookup is
  scoped to the signed-in user: someone else's conversation answers 404, same as a missing one.

- `GET /rag/options`, `POST /rag/search` – the configured embedding models (with availability) and
  splitting strategies; retrieval without a language model.
- `POST /documents` (multipart `file`, optional `embedding`, `chunking`, admin-only `corpus_id`),
  `GET /documents` (`?corpus_id=`), `GET /documents/{id}`, `GET /documents/{id}/chunks`,
  `POST /documents/{id}/index` (index again with another model/strategy), `DELETE /documents/{id}`.
- `GET /corpora`; admin only: `POST /corpora`, `PATCH`, `DELETE /corpora/{id}`,
  `GET|POST /corpora/{id}/access`, `DELETE /corpora/{id}/access/{user_id}`, `POST /corpora/{id}/ingest`.
- `POST /chat` also accepts `use_rag`, `embedding`, `chunking`, `corpus_ids` and returns `citations`.
  See `docs/api/documents.md` and `docs/rag.md`.

## Authentication

Send `Authorization: Bearer <access_token>`. Everything except `/health`, `/auth/login` and
`/auth/refresh` needs it; `/models`, `/ask` and the admin routes additionally need the password
change to be done, and `/admin/*` needs the `admin` role. Accounts are created by admins (no
registration). Status codes: 401 missing/invalid/expired token, 403 wrong role, deactivated account or
pending password change, 503 when `JWT_SECRET` is empty or under 16 characters.

- Passwords: Argon2, 12 to 128 characters. Tokens: HS256 JWT, lifetimes in `config/app.yaml` (`auth:`).
  Access and refresh tokens are not interchangeable.
- Every request re-reads the user, so deactivating an account locks out its existing access token too.
- First admin: `make create-admin` (or `cd api && uv run python -m scripts.create_admin`). It reads
  `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD` or prompts, and refuses to run if an admin exists.
- Code: `app/core/security.py` (hashing, JWT), `app/core/permissions.py` (`current_user`,
  `active_user`, `admin_user` dependencies), `app/services/auth_service.py`, `app/api/v1/auth.py`,
  `app/api/v1/admin_users.py`. Tests use `tests/auth_helpers.py` (in-memory database and tokens).

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

`app/main.py` (app wiring) · `app/api/` (routes, error handlers) · `app/schemas/` · `app/db/repositories/` · `scripts/` ·
`app/services/llm/` (provider interface, adapters, registry, chat service, retry, cost) · `app/core/config.py` (YAML/.env).
Chat: `app/services/chat_service.py` (prompt from history, provider call, persistence), `app/services/conversation_service.py`, `app/db/repositories/conversation_repo.py`, `app/api/v1/{chat,conversations}.py`.
RAG: `app/services/rag/` (`chunking`, `parsers`, `sources/`, `embeddings`, `index` (embedding model + strategy and the metadata stored on every chunk), `vector_store/` (pgvector), `retriever` (the visibility rule), `ingestion`, and the document/corpus/retrieval services), `app/api/v1/{documents,corpora,rag}.py`, `scripts/ingest.py` (`make ingest ARGS="--corpus NAME"`). Embeddings are a provider method (`Provider.embed`); Anthropic does not support it.
Tests: `tests/unit`, `tests/integration`, `tests/contract` (HTTP behaviour, and the OpenAPI snapshot in `docs/openapi.json`: after an intended API change run `make openapi`); `tests/chat_helpers.py` gives chat tests a database, two users and a scriptable fake provider.

## Configuration and database

- `app/core/settings.py` validates `config/*.yaml` (strict: unknown keys, a missing default provider
  or an overlap larger than the chunk size fail at startup) and reads secrets from the environment/`.env`
  (`DATABASE_URL`, `JWT_SECRET`, provider keys). Use `get_settings()`.
- Migrations: `make migrate` (`alembic upgrade head`, using `DATABASE_URL`). Create one with
  `cd api && uv run alembic revision --autogenerate -m "message"`.
- Tests run on SQLite. To also run the migration tests on PostgreSQL:
  `TEST_POSTGRES_URL=postgresql+psycopg://user:pass@localhost:5432/dbname uv run pytest tests/integration`
  (all application tables, `alembic_version` and the enum types are dropped, so use a scratch database). The same variable enables the test that ranks vectors with pgvector's cosine operator; the database must offer the `vector` extension (the `make db-up` image does).

## Container image

`api/Dockerfile` (built from the repository root, see `docker-compose.yml`) installs the locked dependencies with uv, copies `config/` next to the package and, at start, runs `alembic upgrade head` before serving on port 8000. `docker compose run --rm api python -m scripts.create_admin` creates the first admin.
