# AnswerWorks

One interface (API + UI) for working with several AI models, with retrieval-augmented generation (RAG) so answers can be grounded in your own documents.

> **Project status: early development.** The model layer, admin-created accounts with login, saved conversations (API) and a chat UI work today; the UI does not use saved conversations yet, and RAG is planned and not built. See [What works today](#what-works-today) and the [roadmap](#roadmap) before relying on anything here.

FastAPI backend · Streamlit frontend · PostgreSQL + pgvector · configuration in YAML, secrets in `.env`.

## What works today

- **Several providers behind one interface:** Anthropic, OpenAI, and any OpenAI-compatible server (Ollama, vLLM, llama.cpp, ...). Providers and models are declared in [config/providers.yaml](config/providers.yaml); a provider whose API key is missing is skipped, so you only need keys for the ones you use.
- **Login and accounts:** every endpoint except `/health` and `/auth/*` requires a bearer token. There is no self-registration: an admin bootstraps with `make create-admin` and then creates accounts through the admin API. Passwords are hashed with Argon2, sessions use short-lived JWT access tokens plus refresh tokens, accounts can be deactivated, and a new user must choose their own password before using anything else. Roles are `admin` and `user`.
- **Saved conversations:** `POST /chat` sends a message into a conversation (or starts a new one) and the model sees the earlier messages. Conversations and messages are stored in PostgreSQL per user, with provider, model, tokens, latency and cost on every reply, and nobody else can read, rename or delete them. List, read, rename and delete through `/conversations`. Streaming works here too.
- **Question-answer endpoint:** `POST /ask` answers a question with the provider and model you choose (or the default), optionally streaming the answer as server-sent events. Transient provider errors are retried with exponential backoff, and the API returns safe error messages without leaking provider internals.
- **Transparent usage:** every answer reports provider, model, token count, latency and estimated cost. Cost is `null` for models with no pricing configured.
- **Chat UI:** a Streamlit app with a sign-in screen, a forced password-change screen, a model picker, a streaming toggle and per-answer usage details. It works in question-answer mode (`/ask`, no history); a chat mode with saved conversations is next.
- **API foundation:** validated configuration (typos in YAML fail at startup), a PostgreSQL connection with Alembic migrations, and a `/health` endpoint that reports database status. Login needs the database.
- **A keyless fake provider** that echoes your question, for trying the app, UI work and tests without spending tokens.

### Not built yet

A UI for saved conversations, an admin page in the UI (users are managed through the API for now), and RAG (document upload, shared corpora, retrieval with citations). The configuration files for RAG (`config/rag.yaml`, `config/corpora.yaml`) are in place, but nothing reads them yet. The API supports two modes side by side, and both are kept: question-answer (`/ask`, one stateless question and answer) and chat (`/chat`, stored conversations).

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

### Clean up

Stop `make run-api` and `make run-ui` with Ctrl+C in their terminals, then:

```bash
make db-down              # stop the database, keeping its data
make db-destroy           # or delete the container and its data (you will need `make migrate` and `make create-admin` again)
make clean                # remove __pycache__, .pytest_cache and the docs build
```

Local files you may want to remove too: `.env` (it holds your keys) and the virtual environments in `api/.venv` and `ui/.venv`. Pass the same `DB_PORT`/`DB_CONTAINER` values to `db-down` and `db-destroy` if you overrode them in `db-up`.

## Adding users (admin)

There is no sign-up page: an admin creates each account with a temporary password, and the user must replace it at first sign-in. With the API running and the first admin created (`make create-admin`):

```bash
# 1. Sign in as the admin and keep the access token
TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<admin password>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. Create the user (temporary password: 12 to 128 characters; "role" is optional, "user" by default)
curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"email":"ana@example.com","temporary_password":"<temporary password>"}'

# 3. See everyone, or deactivate someone (use the "id" from the list)
curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN"
curl -s -X PATCH localhost:8000/admin/users/<id> -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"is_active": false}'
```

Give the temporary password to the user over a secure channel. The same calls work from the interactive docs at http://localhost:8000/docs (sign in with `POST /auth/login`, click **Authorize**). More in the [admin guide](docs/admin-guide.md).

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

To use real providers instead, see the next section.

## Demo: run the whole system with API keys

Same flow as the demo above, but answers come from real models. Requests are billed by the provider, so keep questions short. The Anthropic, OpenAI and local adapters are tested against mocked HTTP only; this demo is how you check them against the real services.

**1. Prepare**

```bash
cp .env.example .env
```

Edit `.env`:

- `JWT_SECRET`: a random string of at least 16 characters (`openssl rand -hex 32`).
- The key for each provider you want: `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY`. A provider without a key is skipped with a warning in the API log, so you only need one. With only an OpenAI key the default falls back to OpenAI automatically.
- `ANTHROPIC_WORKSPACE_ID`: only if Anthropic answers with `This API key is not scoped to a workspace ... must include the anthropic-workspace-id header`. Put the ID of the workspace to use here (or create a key scoped to a workspace instead). Leave it empty otherwise.
- If port 5432 is taken, `DATABASE_URL=postgresql+psycopg://answerworks:answerworks@localhost:55432/answerworks`, and add `DB_PORT=55432` to the `make db-up` command.

```bash
make install
make db-up
make migrate
unset ANSWERWORKS_CONFIG_DIR     # in case the fake-provider config from the other demo is still set
```

To use a local model server (Ollama, vLLM, llama.cpp) as well, set `enabled: true` for `local` in `config/providers.yaml`, adjust its `base_url` and model ids, and make sure the server is running. To change which models are offered or their prices, edit the lists in the same file.

**2. Create the first admin and start both services**

```bash
BOOTSTRAP_ADMIN_EMAIL=admin@example.com \
BOOTSTRAP_ADMIN_PASSWORD='admin passphrase 1' \
make create-admin

make run-api              # terminal 1
make run-ui               # terminal 2
```

**3. Check which providers loaded**

`/models` needs a token, so sign in first to get an `access_token`. Either use the interactive docs or a terminal.

In the browser, open http://localhost:8000/docs:

1. Expand `POST /auth/login`, click **Try it out**, enter `{"email": "admin@example.com", "password": "admin passphrase 1"}` and click **Execute**.
2. Copy the value of `access_token` from the response body (the long string, without the quotes).
3. Click **Authorize** at the top right, paste it into the value box, click **Authorize**, then **Close**.
4. Expand `GET /models`, click **Try it out**, then **Execute**.

In a terminal:

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"admin passphrase 1"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/models -H "Authorization: Bearer $TOKEN"
```

The access token is valid for 15 minutes (`auth.access_token_ttl_minutes` in `config/app.yaml`); after that, log in again for a new one. Only models of providers that loaded are listed. If one is missing, look in the `make run-api` output for a warning naming the environment variable that is not set.

**4. Chat**

Open http://localhost:8501 and sign in. Pick a model in the sidebar, ask a question, and compare:

- the answer from different providers and models (use the same question);
- streaming: toggle **Stream responses** to see the answer arrive in pieces;
- tokens and estimated cost under each answer. Cost shows "n/a" for models with no `pricing` entry in `config/providers.yaml`.

**5. Accounts and rules**

Create a second user, see the forced password change and try the admin rules exactly as in steps 5 to 7 of the demo above. A user's token works with every configured provider.

**6. Clean up**

Stop both services, then `make db-down` (or `make db-destroy` to delete the data). Remove your keys from `.env` if this is a shared machine.

## Demo: saved conversations (API)

Builds on the demos above: the same running system, now with conversations that are stored and remembered. It uses curl against the API, because the UI does not use saved conversations yet. It works with the fake provider or with real keys. With the fake provider the answers just echo, so the point is what gets stored and who can see it; with real keys you can also watch the model use earlier messages.

**1. Start from a running system**

Follow steps 1 to 3 of either demo above (database, `make migrate`, first admin, `make run-api`). If you ran that demo before this feature existed, run `make migrate` again to add the conversation tables and restart `make run-api`.

**2. Sign in and send a first message**

```bash
login() {
  curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}
TOKEN=$(login admin@example.com 'admin passphrase 1')
curl -s localhost:8000/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message": "My favourite colour is green. Please remember it."}'
```

The reply has the answer, usage (`tokens_used`, `latency_ms`, `cost_usd`) and a `conversation_id`. Copy it: `CID=<the id>`. The conversation title was taken from your first message.

**3. Continue the conversation**

```bash
curl -s localhost:8000/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"conversation_id\": \"$CID\", \"message\": \"Which colour did I say?\"}"
```

With a real model the answer mentions green, because the earlier messages are sent along with the new one (the most recent `chat.history_messages` of them, 20 by default, in `config/app.yaml`). The fake provider only echoes, so use the next step to see what was stored.

**4. Read the history**

```bash
curl -s localhost:8000/conversations/$CID -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Each assistant message records its own provider, model, tokens, latency and cost. The user's own messages carry none.

**5. Stream a reply and switch models**

```bash
curl -N -s localhost:8000/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"conversation_id\": \"$CID\", \"message\": \"Say hello\", \"stream\": true}"
```

You get `delta` events and a final `done` event with the stored message id. Add `"provider"` and `"model"` (ids from `GET /models`) to answer with a different model; the conversation then remembers it for the next message. A message is stored only after the model answered, so a failed call leaves nothing behind and you can simply send it again.

**6. List, rename, delete**

```bash
curl -s localhost:8000/conversations -H "Authorization: Bearer $TOKEN"        # newest activity first
curl -s -X PATCH localhost:8000/conversations/$CID -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"title": "Colours"}'
```

Delete is shown at the end of the next step.

**7. See that conversations are private**

Create a second user and sign in as them (steps 5 and 6 of the demo above, including the forced password change), then:

```bash
ANA=$(login ana@example.com '<ana new password>')
curl -s localhost:8000/conversations -H "Authorization: Bearer $ANA"                 # []
curl -s localhost:8000/conversations/$CID -H "Authorization: Bearer $ANA"            # 404, as if it did not exist
curl -s localhost:8000/chat -H "Authorization: Bearer $ANA" -H 'Content-Type: application/json' \
  -d "{\"conversation_id\": \"$CID\", \"message\": \"hi\"}"                     # 404
curl -s -X DELETE localhost:8000/conversations/$CID -H "Authorization: Bearer $TOKEN" -w '%{http_code}\n'   # 204 (yours)
```

Not even an admin can read another user's conversations through these endpoints.

**8. Clean up**

Same as the demos above. Deleting a conversation also deletes its messages; stopping the services and `make db-down` is all that is left.

## API access in short

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /health` | anyone | API and database status |
| `POST /auth/login`, `POST /auth/refresh` | anyone | Get or renew a token pair |
| `GET /auth/me`, `POST /auth/change-password` | signed in (works while a password change is pending) | Current user, change own password |
| `GET /models`, `POST /ask` | signed in, password change done | Models and stateless questions |
| `POST /chat`, `/conversations` (create, list, read, rename, delete) | signed in, password change done; each user sees only their own | Saved conversations and chat |
| `POST /admin/users`, `GET /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/reset-password` | admin | User management |

Details are in [api/README.md](api/README.md) and the interactive docs at `/docs`.

### The standalone demo page

[ui/demo_page.py](ui/demo_page.py) is a minimal separate UI for `/ask`, kept as originally written. It predates login and sends no token, so the API now answers it with 401 and it can't be used against this API as is. Use the main app instead.

## Configuration

| File | What it controls |
|---|---|
| [config/providers.yaml](config/providers.yaml) | Providers, their models, optional per-model pricing (USD per 1M tokens), timeouts, retries and the default provider |
| [config/app.yaml](config/app.yaml) | App name and environment, CORS origins, auth token lifetimes, how many past messages chat sends to the model, upload limit |
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
| `docs/` | Documentation: authentication, authorization, conversations, data model, admin guide |
| `Makefile` | Install, run, test, lint, migrate, create-admin and local-database commands |

`api/` and `ui/` are separate uv projects with their own environments, which is why `make install` syncs both.

## Roadmap

| Step | Scope | Status |
|---|---|---|
| 1 | Skeleton: configs, Makefile, two packages, CI stubs | Done |
| 2 | API core: validated config, PostgreSQL, migrations, health | Done |
| 3 | Provider layer: Anthropic, OpenAI, local and fake providers | Done |
| 4 | Auth and users: login, JWT, roles, admin-created accounts | Done |
| 5 | Conversations and chat: persistence and streaming (API) | Done |
| 6 | UI: conversations and admin pages (login screen done) | Next |
| 7 | RAG: documents, shared corpora, retrieval with citations | Planned |
| 8 | Docker Compose, docs site, end-to-end tests | Planned |

## License

Released under the [MIT License](LICENSE).
