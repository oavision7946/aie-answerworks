# Architecture

```
Streamlit web app  --HTTP, JWT-->  FastAPI API  -->  PostgreSQL (+ pgvector)
                                        |
                                        +--> providers: Anthropic | OpenAI | local (OpenAI-compatible) | fake
                                        +--> RAG: source -> parse -> split -> embed -> store -> retrieve
```

The repository holds two independent Python packages, `api/` and `ui/`, each with its own dependencies, tests and virtual environment. The web app talks to the API only over HTTP and never touches the database.

## API (`api/app`)

| Package | Role |
|---|---|
| `api/` | Routers: `health`, `auth`, `ask`, `chat`, `conversations`, `models`, `documents`, `corpora`, `rag`, `admin_users` |
| `core/` | Settings (YAML plus environment), security (Argon2, JWT), permission dependencies |
| `schemas/` | Pydantic request and response models |
| `services/llm/` | The `Provider` interface, the registry, the retry and streaming service, and one adapter per provider type |
| `services/rag/` | Parsers, splitters, embeddings, ingestion, retriever, sources and the vector store |
| `db/` | SQLAlchemy models, repositories and the session dependency; Alembic migrations live in `api/migrations` |

Routes call services, services call repositories and providers. No route imports a provider SDK.

## A chat request

1. The bearer token is checked, and the user must be active with no password change pending.
2. The conversation (if any) is loaded for that user only, with the most recent messages.
3. With documents on, the question is embedded and the closest chunks the user may read are retrieved; they are added to the prompt.
4. The provider is called through the registry (retrying transient errors), optionally streaming the answer as server-sent events.
5. Both messages are stored with provider, model, tokens, latency, cost and the ids of the chunks used.

## Web app (`ui/app`)

`main.py` shows the sign-in form (and the forced password change) and then builds the page list with `st.navigation`. Pages live in `views/`, shared widgets in `components/`, sign-in and chat state in `state/`, and every API call in `clients/api_client.py`. See [UI overview](ui/overview.md).

## Providers

A provider is declared in `config/providers.yaml`; its key is read from an environment variable. A provider without a key is skipped at startup with a warning, so only the ones you use need keys. Adapters translate SDK errors into three exceptions (transient, failure, incomplete answer), which keeps retries and error messages independent of any SDK.
