# AnswerWorks

One interface (API + UI) for working with several AI models, with retrieval-augmented generation (RAG) so answers can be grounded in your own documents.

- **Many models, one place:** connect Anthropic, OpenAI or any OpenAI-compatible local server (Ollama, vLLM, ...) through `config/providers.yaml`, and switch models per conversation.
- **Grounded answers (RAG):** ingest PDF, text and Markdown files into a pgvector store and have answers draw on, and cite, the retrieved passages.
- **Transparent usage:** every answer reports the model used, token count, latency and estimated cost.
- **Configurable, not hard-coded:** providers, models, pricing, chunking and retrieval live in `config/*.yaml`; secrets stay in `.env`.

FastAPI backend, Streamlit frontend, PostgreSQL + pgvector.

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
make install      # uv sync in api/ and ui/
make test
```

Run `make run-api` and `make run-ui` in separate terminals. The API docs are served at http://localhost:8000/docs.

### To run demo_page.py do: 
```bash
uv run  streamlit run demo_page.py --server.port 8502
```

## Status

Steps 1 (skeleton) and 2 (API core: validated config, Postgres session, Alembic, health) done. Imported the log-analysis `/health`, `/models`, `/ask` API and chat UI (OpenAI-backed; needs `OPENAI_API_KEY`). Next: provider layer.
