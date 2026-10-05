# AnswerWorks

One interface (API + UI) for working with several AI models, with retrieval-augmented generation (RAG) so answers can be grounded in your own documents.

> **Project status: early development.** The model layer and chat UI work today; accounts, saved conversations and RAG are planned and not built yet. See [What works today](#what-works-today) and the [roadmap](#roadmap) before relying on anything here.

FastAPI backend · Streamlit frontend · PostgreSQL + pgvector · configuration in YAML, secrets in `.env`.

## What works today

- **Several providers behind one interface:** Anthropic, OpenAI, and any OpenAI-compatible server (Ollama, vLLM, llama.cpp, ...). Providers and models are declared in [config/providers.yaml](config/providers.yaml); a provider whose API key is missing is skipped, so you only need keys for the ones you use.
- **Chat endpoint:** `POST /ask` answers a question with the provider and model you choose (or the default), optionally streaming the answer as server-sent events. Transient provider errors are retried with exponential backoff, and the API returns safe error messages without leaking provider internals.
- **Transparent usage:** every answer reports provider, model, token count, latency and estimated cost. Cost is `null` for models with no pricing configured.
- **Chat UI:** a Streamlit page with a model picker, a streaming toggle and per-answer usage details.
- **API foundation:** validated configuration (typos in YAML fail at startup), a PostgreSQL connection with Alembic migrations, and a `/health` endpoint that reports database status.
- **A keyless fake provider** that echoes your question, for trying the app, UI work and tests without spending tokens.

### Not built yet

Login and user accounts, saved conversations, and RAG (document upload, shared corpora, retrieval with citations). The configuration files for them (`config/rag.yaml`, `config/corpora.yaml`) are in place, but nothing reads them yet. `/ask` is a stateless stepping stone and will be replaced by conversation endpoints.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.13 and the dependencies for you)
- `make`
- Docker, only if you want the local PostgreSQL started by `make db-up`
- An API key for at least one provider, unless you use the fake provider below

## Quickstart

```bash
git clone https://github.com/oavision7946/aie-answerworks.git
cd aie-answerworks

cp .env.example .env      # then add the API key(s) for the providers you use
make install              # uv sync in api/ and ui/
make test                 # no database, keys or network needed
```

Start the services in two terminals:

```bash
make run-api              # http://localhost:8000  (interactive docs at /docs)
make run-ui               # http://localhost:8501
```

The UI finds the API at `http://127.0.0.1:8000`; set `API_BASE_URL` to point it elsewhere.

### Try it without API keys

Enable the fake provider in a private copy of the config, so the tracked files stay untouched:

```bash
cp -r config /tmp/aw-config
# in /tmp/aw-config/providers.yaml set:  default_provider: fake  and  providers.fake.enabled: true
ANSWERWORKS_CONFIG_DIR=/tmp/aw-config make run-api
make run-ui               # in another terminal
```

### Database (optional for now)

Nothing user-facing needs the database yet, but `/health` reports `degraded` (HTTP 503) without it, and the migrations create the future users table.

```bash
make db-up                # PostgreSQL + pgvector in Docker, prints the DATABASE_URL to use
make migrate              # applies the Alembic migrations
make db-down              # stop it (data is kept); make db-destroy deletes the data
```

If something is already listening on port 5432, use another port: `make db-up DB_PORT=55432`, then put the `DATABASE_URL` it prints into `.env`.

### The standalone demo page

[ui/demo_page.py](ui/demo_page.py) is a minimal separate UI for `/ask`, kept as originally written. Run it with the API up:

```bash
cd ui && uv run streamlit run demo_page.py --server.port 8502
```

Its model list is hard-coded (`gpt-4o-mini`, `gpt-4o`, `o3-mini`). The API rejects any model that isn't in `config/providers.yaml`, so `o3-mini` will fail unless you add it.

## Configuration

| File | What it controls |
|---|---|
| [config/providers.yaml](config/providers.yaml) | Providers, their models, optional per-model pricing (USD per 1M tokens), timeouts, retries and the default provider |
| [config/app.yaml](config/app.yaml) | App name and environment, CORS origins, auth token lifetimes, upload limit |
| [config/rag.yaml](config/rag.yaml) | Embeddings, chunking and retrieval settings (reserved for RAG) |
| [config/corpora.yaml](config/corpora.yaml) | Shared document collections (reserved for RAG) |
| `.env` | Secrets and deployment values only: provider API keys, `DATABASE_URL`, `JWT_SECRET`. Never committed |

All YAML is validated at startup, so a typo or a broken reference fails loudly instead of silently misbehaving. Set `ANSWERWORKS_CONFIG_DIR` to use a different config directory.

To add a model, add an entry under its provider in `providers.yaml`. To add a different kind of backend, see [api/README.md](api/README.md).

## Development

```bash
make test        # API + UI test suites (85% coverage gate; both currently at 100%)
make lint        # ruff
make format      # ruff --fix and format
```

Tests never reach a real provider; adapters are tested against mocked HTTP. Automatic CI runs are deliberately disabled for now; the workflows in `.github/workflows/` can be started manually from the Actions tab.

## Layout

| Path | Purpose |
|---|---|
| `api/` | FastAPI backend and its tests; see [api/README.md](api/README.md) |
| `ui/` | Streamlit frontend and its tests; see [ui/README.md](ui/README.md) |
| `config/` | Non-secret YAML configuration |
| `docs/` | Documentation (index only so far) |
| `Makefile` | Install, run, test, lint, migrate and local-database commands |

`api/` and `ui/` are separate uv projects with their own environments, which is why `make install` syncs both.

## Roadmap

| Step | Scope | Status |
|---|---|---|
| 1 | Skeleton: configs, Makefile, two packages, CI stubs | Done |
| 2 | API core: validated config, PostgreSQL, migrations, health | Done |
| 3 | Provider layer: Anthropic, OpenAI, local and fake providers | Done |
| 4 | Auth and users: login, JWT, roles, admin-created accounts | Next |
| 5 | Conversations and chat: persistence and streaming | Planned |
| 6 | UI: login, conversations, admin pages | Planned |
| 7 | RAG: documents, shared corpora, retrieval with citations | Planned |
| 8 | Docker Compose, docs site, end-to-end tests | Planned |

## License

No license has been chosen yet, so by default all rights are reserved. Add a `LICENSE` file before inviting reuse or contributions.
