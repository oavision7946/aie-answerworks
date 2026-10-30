# AnswerWorks

One interface (API + UI) for working with several AI models, with retrieval-augmented generation (RAG) so answers can be grounded in your own documents.

> **Project status: early development.** The model layer, admin-created accounts with login, and a chat UI work today; saved conversations and RAG are planned and not built yet. See [What works today](#what-works-today) and the [roadmap](#roadmap) before relying on anything here.

FastAPI backend · Streamlit frontend · PostgreSQL + pgvector · configuration in YAML, secrets in `.env`.

## What works today

- **Several providers behind one interface:** Anthropic, OpenAI, and any OpenAI-compatible server (Ollama, vLLM, llama.cpp, ...). Providers and models are declared in [config/providers.yaml](config/providers.yaml); a provider whose API key is missing is skipped, so you only need keys for the ones you use.
- **Login and accounts:** every endpoint except `/health` and `/auth/*` requires a bearer token. There is no self-registration: an admin bootstraps with `make create-admin` and then creates accounts through the admin API. Passwords are hashed with Argon2, sessions use short-lived JWT access tokens plus refresh tokens, accounts can be deactivated, and a new user must choose their own password before using anything else. Roles are `admin` and `user`.
- **Chat endpoint:** `POST /ask` answers a question with the provider and model you choose (or the default), optionally streaming the answer as server-sent events. Transient provider errors are retried with exponential backoff, and the API returns safe error messages without leaking provider internals.
- **Transparent usage:** every answer reports provider, model, token count, latency and estimated cost. Cost is `null` for models with no pricing configured.
- **Chat UI:** a Streamlit app with a sign-in screen, a forced password-change screen, a model picker, a streaming toggle and per-answer usage details.
- **API foundation:** validated configuration (typos in YAML fail at startup), a PostgreSQL connection with Alembic migrations, and a `/health` endpoint that reports database status. Login needs the database.
- **A keyless fake provider** that echoes your question, for trying the app, UI work and tests without spending tokens.

### Not built yet

Saved conversations, an admin page in the UI (users are managed through the API for now), and RAG (document upload, shared corpora, retrieval with citations). The configuration files for RAG (`config/rag.yaml`, `config/corpora.yaml`) are in place, but nothing reads them yet. `/ask` is a stateless stepping stone and will be replaced by conversation endpoints.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.13 and the dependencies for you)
- `make`
- Docker, to start the local PostgreSQL with `make db-up` (or bring your own PostgreSQL)
- An API key for at least one provider, unless you use the fake provider below

## Quickstart

```bash
git clone https://github.com/oavision7946/aie-answerworks.git
cd aie-answerworks

cp .env.example .env      # then set JWT_SECRET and the API key(s) for the providers you use
make install              # uv sync in api/ and ui/
make test                 # no database, keys or network needed
```

Set `JWT_SECRET` in `.env` to a random string of at least 16 characters (`openssl rand -hex 32` works). Without it the API answers every login with 503.

To run the system you need the database and a first admin:

```bash
make db-up                # PostgreSQL + pgvector in Docker; prints the DATABASE_URL to use
make migrate              # creates the tables
make create-admin         # asks for the first admin's email and password
make run-api              # http://localhost:8000  (interactive docs at /docs)
make run-ui               # http://localhost:8501  (in a second terminal)
```

Open http://localhost:8501 and sign in with the admin account you just created. The UI finds the API at `http://127.0.0.1:8000`; set `API_BASE_URL` to point it elsewhere.

If something is already listening on port 5432, use another port: `make db-up DB_PORT=55432`, then put the `DATABASE_URL` it prints into `.env`. `make db-down` stops the database (data is kept); `make db-destroy` deletes the data.

## Demo: run the whole system without API keys

This walks through login, the forced password change, and the admin API using the built-in fake provider, which echoes your question, so it costs nothing and needs no provider keys. Nothing here edits tracked files.

**1. Prepare**

```bash
cp .env.example .env
# Edit .env: set JWT_SECRET (e.g. the output of `openssl rand -hex 32`).
# If port 5432 is taken, also use DB_PORT=55432 below and set
# DATABASE_URL=postgresql+psycopg://answerworks:answerworks@localhost:55432/answerworks

make install
make db-up                # add DB_PORT=55432 if needed
make migrate
```

**2. Switch to the fake provider in a private copy of the config**

```bash
cp -r config /tmp/aw-config
sed -i 's/^default_provider: anthropic/default_provider: fake/' /tmp/aw-config/providers.yaml
sed -i '/^  fake:/,/enabled:/ s/enabled: false/enabled: true/' /tmp/aw-config/providers.yaml
export ANSWERWORKS_CONFIG_DIR=/tmp/aw-config
```

**3. Create the first admin and start both services**

```bash
BOOTSTRAP_ADMIN_EMAIL=admin@example.com \
BOOTSTRAP_ADMIN_PASSWORD='admin passphrase 1' \
make create-admin         # or run `make create-admin` alone to be prompted

make run-api              # terminal 1 (keep ANSWERWORKS_CONFIG_DIR exported)
make run-ui               # terminal 2
```

Passwords must be 12 to 128 characters. The bootstrap admin does not have to change their password. Running `make create-admin` again fails and changes nothing, because an admin already exists.

**4. Sign in and chat as the admin**

Open http://localhost:8501, sign in as `admin@example.com`, leave the model on "Echo (fake)", and ask something. The answer is `Echo: <your question>` with token usage, and cost shows "n/a" because the fake model has no price.

**5. Create a regular user (admin API)**

Open http://localhost:8000/docs, call `POST /auth/login` with the admin credentials, copy the `access_token`, click **Authorize** and paste it. Then call `POST /admin/users` with:

```json
{"email": "ana@example.com", "temporary_password": "temporary pass 123"}
```

The same from a terminal:

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"admin passphrase 1"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"email":"ana@example.com","temporary_password":"temporary pass 123"}'
```

**6. See the forced password change**

In the UI, sign out and sign in as `ana@example.com` with the temporary password. The app asks for a new password before showing the chat. Until it is changed, the API answers 403 to `/models` and `/ask` for that account. After changing it, the chat opens.

**7. Try the rules**

- Call `GET /admin/users` with ana's token: 403 (admins only). Without a token: 401.
- As the admin, `PATCH /admin/users/{id}` with `{"is_active": false}` deactivates ana. Signing in or refreshing then fails with 403, and her existing token stops working.
- `POST /admin/users/{id}/reset-password` sets a new temporary password and forces another change.
- You cannot deactivate or demote your own account. `POST /auth/register` does not exist (404).

**8. Clean up**

```bash
make db-down              # keeps the data; `make db-destroy` deletes it
rm -rf /tmp/aw-config
unset ANSWERWORKS_CONFIG_DIR
```

To use real providers instead, skip step 2 and put the keys for the providers you want in `.env`.

## API access in short

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /health` | anyone | API and database status |
| `POST /auth/login`, `POST /auth/refresh` | anyone | Get or renew a token pair |
| `GET /auth/me`, `POST /auth/change-password` | signed in (works while a password change is pending) | Current user, change own password |
| `GET /models`, `POST /ask` | signed in, password change done | Models and chat |
| `POST /admin/users`, `GET /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/reset-password` | admin | User management |

Details are in [api/README.md](api/README.md) and the interactive docs at `/docs`.

### The standalone demo page

[ui/demo_page.py](ui/demo_page.py) is a minimal separate UI for `/ask`, kept as originally written. It predates login and sends no token, so the API now answers it with 401 and it can't be used against this API as is. Use the main app instead.

## Configuration

| File | What it controls |
|---|---|
| [config/providers.yaml](config/providers.yaml) | Providers, their models, optional per-model pricing (USD per 1M tokens), timeouts, retries and the default provider |
| [config/app.yaml](config/app.yaml) | App name and environment, CORS origins, auth token lifetimes, upload limit |
| [config/rag.yaml](config/rag.yaml) | Embeddings, chunking and retrieval settings (reserved for RAG) |
| [config/corpora.yaml](config/corpora.yaml) | Shared document collections (reserved for RAG) |
| `.env` | Secrets and deployment values only: provider API keys, `DATABASE_URL`, `JWT_SECRET` (at least 16 characters), and optionally `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD` for `make create-admin`. Never committed |

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
| `Makefile` | Install, run, test, lint, migrate, create-admin and local-database commands |

`api/` and `ui/` are separate uv projects with their own environments, which is why `make install` syncs both.

## Roadmap

| Step | Scope | Status |
|---|---|---|
| 1 | Skeleton: configs, Makefile, two packages, CI stubs | Done |
| 2 | API core: validated config, PostgreSQL, migrations, health | Done |
| 3 | Provider layer: Anthropic, OpenAI, local and fake providers | Done |
| 4 | Auth and users: login, JWT, roles, admin-created accounts | Done |
| 5 | Conversations and chat: persistence and streaming | Next |
| 6 | UI: conversations and admin pages (login screen done) | Planned |
| 7 | RAG: documents, shared corpora, retrieval with citations | Planned |
| 8 | Docker Compose, docs site, end-to-end tests | Planned |

## License

No license has been chosen yet, so by default all rights are reserved. Add a `LICENSE` file before inviting reuse or contributions.
