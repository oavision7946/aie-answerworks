# Configuration

Non-secret settings live in YAML under `config/`; secrets live in `.env`. Everything is validated once at startup, so a typo, an unknown key or a broken reference stops the API with a clear message instead of misbehaving later.

| File | Content |
|---|---|
| `config/providers.yaml` | Providers and their models, optional prices (USD per 1M tokens), request timeouts and retries, the default provider and model |
| `config/app.yaml` | App name and environment, CORS origins, token lifetimes, how many past messages chat sends, the upload limit |
| `config/rag.yaml` | Named embedding models and splitting strategies with defaults, `top_k` and `min_score`, the vector store and accepted file types |
| `config/corpora.yaml` | Shared corpora filled from a folder with `make ingest` |

## Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `JWT_SECRET` | API | At least 16 characters. Without it every login answers 503 |
| `DATABASE_URL` | API | SQLAlchemy URL of the PostgreSQL database |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LOCAL_LLM_API_KEY` | API | Keys named by `api_key_env` in `providers.yaml` |
| `ANTHROPIC_WORKSPACE_ID` | API | Only for Anthropic keys that are not scoped to a workspace |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` | `create-admin` | Non-interactive first admin |
| `ANSWERWORKS_CONFIG_DIR` | API | Use another config directory |
| `API_BASE_URL` | Web app | Where the API is (default `http://127.0.0.1:8000`) |

Real environment variables win over `.env`. `.env` is never committed.

## Common changes

- **Add a model:** add an entry under its provider in `providers.yaml`.
- **Use another default:** set `default_provider` and the provider's `default_model`.
- **Try another embedding model or splitter:** add it to `embedding_models` or `chunking_strategies` in `rag.yaml`. See [RAG](rag.md).
- **Change a token lifetime:** `auth.access_token_ttl_minutes` and `auth.refresh_token_ttl_days` in `app.yaml`.
