# AnswerWorks

AI chat application with RAG. FastAPI backend, Streamlit frontend, PostgreSQL + pgvector.

## Layout

| Path | Purpose |
|---|---|
| `api/` | FastAPI backend (auth, conversations, providers, RAG) and its tests |
| `ui/` | Streamlit frontend and its tests |
| `config/` | Non-secret YAML configuration (providers, RAG, app, corpora) |
| `tests_e2e/` | End-to-end tests spanning both services |
| `docs/` | Architecture, API and UI documentation |
| `.env` | Secrets only (copy from `.env.example`, never committed) |

## Quickstart

```bash
cp .env.example .env     # fill in keys and JWT_SECRET
make install
make test
```

Run `make run-api` and `make run-ui` in separate terminals. The API docs are served at http://localhost:8000/docs.

## Status

Step 1 (skeleton) done. Next: API core (config loader, Postgres, migrations, health).
