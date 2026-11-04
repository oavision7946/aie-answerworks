# AnswerWorks

One interface (API + UI) for working with several AI models, with retrieval-augmented generation (RAG) so answers can be grounded in your own documents.

> **Project status: early development.** The model layer, admin-created accounts with login, saved conversations, and a web UI with chat, conversation history, question-answer and user administration work today, and so does RAG: upload documents, share corpora, and get answers with sources. See [What works today](#what-works-today) and the [roadmap](#roadmap) before relying on anything here.

FastAPI backend · Streamlit frontend · PostgreSQL + pgvector · configuration in YAML, secrets in `.env`.

## Contents

- [What works today](#what-works-today)
  - [Known limits](#known-limits)
- [Prerequisites](#prerequisites)
- [Quickstart](#quickstart)
  - [Clean up the local run](#clean-up-the-local-run)
  - [Run with Docker Compose](#run-with-docker-compose)
- [Examples](#examples)
  - [Credentials used in the examples](#credentials-used-in-the-examples)
  - [Adding users (admin)](#adding-users-admin)
  - [Example: Run the whole system with or without provider API keys](#example-run-the-whole-system-with-or-without-provider-api-keys)
  - [Example: saved conversations (API)](#example-saved-conversations-api)
  - [Example: the web app (chat, conversations, admin)](#example-the-web-app-chat-conversations-admin)
  - [Example: your documents (RAG)](#example-your-documents-rag)
- [API access in short](#api-access-in-short)
  - [The standalone demo page](#the-standalone-demo-page)
- [Configuration](#configuration)
- [Development](#development)
- [Layout](#layout)
- [Roadmap](#roadmap)
- [License](#license)

## What works today

- **Several providers behind one interface:** Anthropic, OpenAI, and any OpenAI-compatible server (Ollama, vLLM, llama.cpp, ...). Providers and models are declared in [config/providers.yaml](config/providers.yaml); a provider whose API key is missing is skipped, so you only need keys for the ones you use.
- **Login and accounts:** every endpoint except `/health`, `/health/ready` and `/auth/*` requires a bearer token. There is no self-registration: an admin bootstraps with `make create-admin` and then creates accounts through the admin API. Passwords are hashed with Argon2, sessions use short-lived JWT access tokens plus refresh tokens, accounts can be deactivated, and a new user must choose their own password before using anything else. Roles are `admin` and `user`.
- **Saved conversations:** `POST /chat` sends a message into a conversation (or starts a new one) and the model sees the earlier messages. Conversations and messages are stored in PostgreSQL per user, with provider, model, tokens, latency and cost on every reply, and nobody else can read, rename or delete them. List, read, rename and delete through `/conversations`. Streaming works here too.
- **Question-answer endpoint:** `POST /ask` answers a question with the provider and model you choose (or the default), optionally streaming the answer as server-sent events. Transient provider errors are retried with exponential backoff, and the API returns safe error messages without leaking provider internals.
- **Transparent usage:** every answer reports provider, model, token count, latency and estimated cost. Cost is `null` for models with no pricing configured.
- **Web UI:** a Streamlit app with sign-in, a forced password-change screen and these pages: **Chat** (saved conversations with a model picker, streaming, per-answer usage and optional document sources), **Conversations** (open, rename, delete), **Documents** (your uploads and the shared corpora you can read, with how each was indexed), **Ask** (one-off question-answer, nothing saved) and, for admins only, **Admin · Users** and **Admin · Corpora**.
- **RAG (answers from your documents):** upload PDF, TXT, Markdown, Word (`.docx`) or HTML files (private to you) or have an admin build shared corpora (from a folder or a list of web addresses, optionally refreshed on a schedule), then turn on documents in Chat or pass `use_rag` to `/chat`. Answers cite the passages they used. **Embedding models and text-splitting strategies are configurable and interchangeable** (several can be defined in [config/rag.yaml](config/rag.yaml)), and every stored chunk records which embedding model and which splitter produced it, so a document can be indexed several ways and compared. Retrieval is strictly scoped: your private documents never reach another user, and shared corpora are visible only to users with a grant (or to everyone if public), with revocation applying immediately. See [docs/rag.md](docs/rag.md).
- **API foundation:** validated configuration (typos in YAML fail at startup), a PostgreSQL connection with Alembic migrations, and separate liveness (`/health`) and readiness (`/health/ready`) endpoints. Login needs the database.
- **Observability:** an admin **System** page and `GET /admin/status` show the database and schema version, which providers loaded and how their calls are going, embedding model availability, each corpus's last ingestion, row counts and request totals; an optional token-protected `GET /metrics` serves the same in the Prometheus format. See [docs/observability.md](docs/observability.md).
- **Docker Compose:** `docker compose up --build` starts PostgreSQL with pgvector, the API (migrations applied at start) and the web app. See [Run with Docker Compose](#run-with-docker-compose).
- **Documentation site, contract and end-to-end tests:** a MkDocs site built from [docs/](docs/index.md), a committed OpenAPI snapshot that a contract test checks, and an end-to-end test of sign-in, upload, chat with sources and saved history.
- **A keyless fake provider** that echoes your question, for trying the app, UI work and tests without spending tokens.

### Known limits

Deliberately simple for now: uploads are indexed while the request waits, similarity search is exact (no approximate vector index), and only text is read (PDF, TXT, Markdown, Word and HTML; no OCR for scanned pages). The API supports two modes side by side, and both are kept: question-answer (`/ask`, one stateless question and answer) and chat (`/chat`, stored conversations). The UI offers both.

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

#### Clean up the local run

Stop `make run-api` and `make run-ui` with Ctrl+C in their terminals, then:

```bash
make db-down              # stop the database, keeping its data
make db-destroy           # or delete the container and its data (you will need `make migrate` and `make create-admin` again)
make clean                # remove Python and tool caches
```

Local files you may want to remove too: `.env` (it holds your keys) and the virtual environments in `api/.venv` and `ui/.venv`. Pass the same `DB_PORT`/`DB_CONTAINER` values to `db-down` and `db-destroy` if you overrode them in `db-up`.

### Run with Docker Compose

The same system without installing Python or `uv` on the host:

```bash
cp .env.example .env                 # set JWT_SECRET and the provider keys you use
docker compose up --build -d
docker compose run --rm api python -m scripts.create_admin
```

Open http://localhost:8501 (web app) or http://localhost:8000/docs (API). Migrations run when the API starts, the database lives in a Docker volume, and `config/` is mounted so YAML edits apply after `docker compose restart api`. Ports, config directory and database credentials can be changed with variables; see [docs/deployment.md](docs/deployment.md). Corpora with `refresh_minutes` are refreshed by the optional scheduler service: `docker compose --profile scheduler up -d`.

#### Clean up the Docker Compose run

Stop the containers, and remove their data and images if you no longer need them:

```bash
docker compose down                # stop everything and keep the data
docker compose down -v             # stop everything and delete the data
docker compose down -v --rmi local # also remove the images built for this project
docker builder prune               # optional: clear the build cache
```

## Examples

### Credentials used in the examples

The examples below read the accounts from shell variables instead of fixed values. Set them once in each terminal you use (choose your own values; passwords are 12 to 128 characters):

```bash
export ADMIN_EMAIL=<admin email>
export ADMIN_PASSWORD=<admin password>
export USER1_EMAIL=<first user's email>
export USER1_TEMP_PASSWORD=<temporary password the admin gives the user>
export USER1_PASSWORD=<password the user chooses at first sign-in>
```

`USER1_PASSWORD` only works after the user has replaced the temporary one (see "See the forced password change" below). Quote a value that contains spaces or shell characters, for example `export ADMIN_PASSWORD='a long passphrase'`.

### Adding users (admin)

There is no sign-up page: an admin creates each account with a temporary password, and the user must replace it at first sign-in. With the API running and the first admin created (`make create-admin`):

```bash
# 1. Sign in as the admin and keep the access token
TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. Create the user (temporary password: 12 to 128 characters; "role" is optional, "user" by default)
curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$USER1_EMAIL\",\"temporary_password\":\"$USER1_TEMP_PASSWORD\"}"

# 3. List users and their ids
curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN"

# 4. Deactivate a user (here, id 2)
curl -s -X PATCH localhost:8000/admin/users/2 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"is_active": false}'

# or using the email
ID=$(curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN" \
  | jq -r --arg email "$USER1_EMAIL" '.[] | select(.email==$email) | .id')
curl -s -X PATCH localhost:8000/admin/users/$ID \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"is_active": false}'
```

Give the temporary password to the user over a secure channel. The same calls work from the interactive docs at http://localhost:8000/docs (sign in with `POST /auth/login`, click **Authorize**). More in the [admin guide](docs/admin-guide.md).

### Example: Run the whole system with or without provider API keys

This walks through login, the forced password change and the admin API. Run it one of two ways:

- **Keyless case:** a built-in fake provider echoes your question, so it costs nothing and needs no provider keys.
- **Provider-keys case:** answers come from real models. Requests are billed by the provider, so keep questions short. The Anthropic, OpenAI and local adapters are tested against mocked HTTP only; this example is how you check them against the real services.

Steps 2 and 5 apply to one case only and say which. Nothing here edits tracked files.

**1. Prepare**

```bash
cp .env.example .env
```

Edit `.env`:

- `JWT_SECRET`: a random string of at least 16 characters (`openssl rand -hex 32`).
- If port 5432 is taken, `DATABASE_URL=postgresql+psycopg://answerworks:answerworks@localhost:55432/answerworks`, and add `DB_PORT=55432` to the `make db-up` command.
- Provider-keys case only: the key for each provider you want, `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY`. A provider without a key is skipped with a warning in the API log, so you only need one. With only an OpenAI key the default falls back to OpenAI automatically.
  - `ANTHROPIC_WORKSPACE_ID`: only if Anthropic answers with `This API key is not scoped to a workspace ... must include the anthropic-workspace-id header`. Put the ID of the workspace to use here (or create a key scoped to a workspace instead). Leave it empty otherwise.

```bash
make install
make db-up                    # add DB_PORT=55432 if needed
make migrate
```

Provider-keys case only: to use a local model server (Ollama, vLLM, llama.cpp) as well, set `enabled: true` for `local` in `config/providers.yaml`, adjust its `base_url` and model ids, and make sure the server is running. To change which models are offered or their prices, edit the lists in the same file. If you ran the keyless case before in this terminal, run `unset ANSWERWORKS_CONFIG_DIR` so the real config applies.

**2. Keyless case only: switch to the fake provider in a private copy of the config**

```bash
cp -r config /tmp/aw-config
sed -i 's/^default_provider: anthropic/default_provider: fake/' /tmp/aw-config/providers.yaml
sed -i '/^  fake:/,/enabled:/ s/enabled: false/enabled: true/' /tmp/aw-config/providers.yaml
export ANSWERWORKS_CONFIG_DIR=/tmp/aw-config
```

**3. Create the first admin**

```bash
BOOTSTRAP_ADMIN_EMAIL="$ADMIN_EMAIL" \
BOOTSTRAP_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
make create-admin         # or run `make create-admin` alone to be prompted
```

Passwords must be 12 to 128 characters. The bootstrap admin does not have to change their password. Running `make create-admin` again fails and changes nothing, because an admin already exists.

**4. Start API and UI services**

```bash
make run-api              # terminal 1 (keyless case: keep ANSWERWORKS_CONFIG_DIR exported)
make run-ui               # terminal 2
```

**5. Provider-keys case only: check which providers loaded**

`/models` needs a token, so sign in first to get an `access_token`. Either use the interactive docs or a terminal.

In the browser, open http://localhost:8000/docs:

1. Expand `POST /auth/login`, click **Try it out**, enter `{"email": "<ADMIN_EMAIL>", "password": "<ADMIN_PASSWORD>"}` and click **Execute**.
2. Copy the value of `access_token` from the response body (the long string, without the quotes).
3. Click **Authorize** at the top right, paste it into the value box, click **Authorize**, then **Close**.
4. Expand `GET /models`, click **Try it out**, then **Execute**.

In a terminal:

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/models -H "Authorization: Bearer $TOKEN"
```

The access token is valid for 15 minutes (`auth.access_token_ttl_minutes` in `config/app.yaml`); after that, log in again for a new one. Only models of providers that loaded are listed. If one is missing, look in the `make run-api` output for a warning naming the environment variable that is not set.

**6. Sign in and chat as the admin**

Open http://localhost:8501 and sign in as `ADMIN_EMAIL`. Pick a model in the sidebar ("Echo (fake)" in the keyless case) and ask something.

- Keyless case: the answer is `Echo: <your question>` with token usage, and cost shows "n/a" because the fake model has no price.
- Provider-keys case, compare:
  - the answer from different providers and models (use the same question);
  - streaming: toggle **Stream responses** to see the answer arrive in pieces;
  - tokens and estimated cost under each answer. Cost shows "n/a" for models with no `pricing` entry in `config/providers.yaml`.

**7. Create a regular user (admin API)**

Open http://localhost:8000/docs, call `POST /auth/login` with the admin credentials, copy the `access_token`, click **Authorize** and paste it. Then call `POST /admin/users` with:

```json
{"email": "<USER1_EMAIL>", "temporary_password": "<USER1_TEMP_PASSWORD>"}
```

The same from a terminal:

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/admin/users -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$USER1_EMAIL\",\"temporary_password\":\"$USER1_TEMP_PASSWORD\"}"
```

**8. See the forced password change**

In the UI, sign out and sign in as `USER1_EMAIL` with `USER1_TEMP_PASSWORD`. The app asks for a new password before showing the chat. Until it is changed, the API answers 403 to `/models` and `/ask` for that account. After changing it, the chat opens.

**9. Try the rules**

- Call `GET /admin/users` with the user's token: 403 (admins only). Without a token: 401.
- As the admin, `PATCH /admin/users/{id}` with `{"is_active": false}` deactivates that user. Signing in or refreshing then fails with 403, and their existing token stops working.
- `POST /admin/users/{id}/reset-password` sets a new temporary password and forces another change.
- You cannot deactivate or demote your own account. `POST /auth/register` does not exist (404).
- Provider-keys case: the regular user's token works with every configured provider.

**10. Clean up**

Stop both services with Ctrl+C, then:

```bash
make db-down              # keeps the data; `make db-destroy` deletes it
make clean                # removes Python and tool caches (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`)
```

- Provider-keys case: remove your keys from `.env` if this is a shared machine.
- Keyless case: remove the private config and unset the variable:

  ```bash
  rm -rf /tmp/aw-config
  unset ANSWERWORKS_CONFIG_DIR
  ```

### Example: saved conversations (API)

Builds on the demos above: the same running system, now with conversations that are stored and remembered. It uses curl against the API, because the UI does not use saved conversations yet. It works with the fake provider or with real keys. With the fake provider the answers just echo, so the point is what gets stored and who can see it; with real keys you can also watch the model use earlier messages.

**1. Start from a running system**

Follow steps 1 to 4 of the [first example](#example-run-the-whole-system-with-or-without-provider-api-keys) above, in either case (database, `make migrate`, first admin, `make run-api`). If you ran that demo before this feature existed, run `make migrate` again to add the conversation tables and restart `make run-api`.

**2. Sign in and send a first message**

```bash
# login EMAIL PASSWORD prints an access token. Defining it prints nothing, and it is
# forgotten when you close the terminal, so paste this block again in a new one.
login() {
  curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}
TOKEN=$(login "$ADMIN_EMAIL" "$ADMIN_PASSWORD")
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

Create a second user and sign in as them (steps 7 and 8 of the [first example](#example-run-the-whole-system-with-or-without-provider-api-keys), including the forced password change), then:

```bash
USER1_TOKEN=$(login "$USER1_EMAIL" "$USER1_PASSWORD")
curl -s localhost:8000/conversations -H "Authorization: Bearer $USER1_TOKEN"                 # []
curl -s localhost:8000/conversations/$CID -H "Authorization: Bearer $USER1_TOKEN"            # 404, as if it did not exist
curl -s localhost:8000/chat -H "Authorization: Bearer $USER1_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"conversation_id\": \"$CID\", \"message\": \"hi\"}"                     # 404
curl -s -X DELETE localhost:8000/conversations/$CID -H "Authorization: Bearer $TOKEN" -w '%{http_code}\n'   # 204 (yours)
```

Not even an admin can read another user's conversations through these endpoints.

**8. Clean up**

Same as the demos above. Deleting a conversation also deletes its messages; stopping the services, `make db-down` (or `make db-destroy` to delete the data) and `make clean` is all that is left.

### Example: the web app (chat, conversations, admin)

The same system seen through the browser. Every UI step has an "Same from the API" line, so you can see what the page does behind the scenes. Start from a running system: steps 1 to 4 of the [first example](#example-run-the-whole-system-with-or-without-provider-api-keys) above, in either case: database, `make migrate`, first admin, `make run-api`, then `make run-ui` and open http://localhost:8501. If you set up the system before the UI had these pages, nothing needs migrating.

**1. Sign in and find your way around**

Sign in as the admin. The sidebar lists the pages: **Chat**, **Conversations**, **Ask** and **Admin · Users**, and under them your email, **Sign out** and the API address. Admins see "(admin)" next to their email. A regular user does not get the Admin page at all.

Same from the API: `GET /auth/me` returns your `role`, which is how the UI decides what to list:

```bash
# login EMAIL PASSWORD prints an access token. Defining it prints nothing, and it is
# forgotten when you close the terminal, so paste this block again in a new one.
login() {
  curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}
TOKEN=$(login "$ADMIN_EMAIL" "$ADMIN_PASSWORD")
curl -s localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
```

**2. Chat**

On **Chat**, send "My favourite colour is green. Please remember it.", then "Which colour did I say?". Under each answer you see the model, tokens and estimated cost. Pick another model in the sidebar to change who answers the next message; tick **Stream responses** to watch the answer arrive in pieces. With the fake provider the answers just echo; with real keys the second answer mentions green because the first message is sent along with it. **＋ New chat** starts a fresh conversation.

Same from the API: the [saved conversations example](#example-saved-conversations-api), steps 2 to 5 (`POST /chat`, with `"stream": true` for streaming).

**3. Conversations**

Open **Conversations**. Your chat is listed with its model and last activity. Click **Open** to go back to Chat with the whole history loaded and keep talking; **Rename** changes the title; **Delete** asks for confirmation and removes the conversation with its messages.

Same from the API:

```bash
curl -s localhost:8000/conversations -H "Authorization: Bearer $TOKEN"                    # the list
curl -s localhost:8000/conversations/<id> -H "Authorization: Bearer $TOKEN"               # Open
curl -s -X PATCH localhost:8000/conversations/<id> -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"title": "Colours"}'                            # Rename
curl -s -X DELETE localhost:8000/conversations/<id> -H "Authorization: Bearer $TOKEN"     # Delete
```

**4. Ask (question-answer)**

Open **Ask** and ask a question. Each question is answered on its own: no history is sent, nothing is saved, and it never shows up under Conversations. Use it for one-off questions or to compare models on the same prompt. (The **Tests** box in its sidebar forces a bad first answer to show the API's retry.)

Same from the API:

```bash
curl -s localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question": "What is RAG?"}'
```

**5. Admin · Users**

Open **Admin · Users**. The table lists every account with its role, whether it is active, and whether a password change is pending. Under **Add a user**, enter an email, a temporary password (12 to 128 characters) and a role, then **Create user**. Under **Manage a user**, pick someone to change their role, deactivate them, or set a new temporary password. Try deactivating yourself: the API refuses, and the page shows its message.

Same from the API: see [Adding users (admin)](#adding-users-admin) and step 9 of the [first example](#example-run-the-whole-system-with-or-without-provider-api-keys).

**6. See it as a regular user**

Sign out and sign in as the user you created. The app first asks for a new password. Then there is no Admin page, **Conversations** is empty (conversations are private), and the admin API refuses the same token:

```bash
USER1_TOKEN=$(login "$USER1_EMAIL" "$USER1_PASSWORD")
curl -s localhost:8000/admin/users -H "Authorization: Bearer $USER1_TOKEN"     # 403
```

**7. Clean up**

Stop `make run-ui` and `make run-api`, then `make db-down` (or `make db-destroy` to delete the data), then `make clean` to remove caches.

### Example: your documents (RAG)

Builds on the web-app example. You will upload a document, see exactly how it was split and embedded, index it a second way with a different embedding model and splitter, ask questions with and without documents, check that other users cannot see your files, and share a corpus. Every UI step has a "Same from the API" curl equivalent.

The keyless setup uses the fake provider's embeddings, which are a hashed bag of words: they find passages that **share words** with your question, which is enough to see the whole mechanism. Real embedding models also match meaning. To try them, follow **Prepare (with keys)** in step 1 instead of **Prepare (keyless)**; every other step is the same for both.

**1. Prepare (keyless)**

Skip to **Prepare (with keys)** below if you use real providers.

Start from the first example (database, `make migrate`, the private copy of the config in `/tmp/aw-config`, the first admin, `make run-api` and `make run-ui`). The pgvector tables come from the same `make migrate`; run it again if you set the system up before documents existed. Then give the private config two fake embedding models and a few splitting strategies, and restart `make run-api`:

```bash
cat > /tmp/aw-config/rag.yaml <<'EOF'
embedding_models:
  fake-small: { provider: fake, model: fake-small, dimensions: 256 }
  fake-large: { provider: fake, model: fake-large, dimensions: 512 }
default_embedding: fake-small
chunking_strategies:
  recursive: { method: recursive, size: 200, overlap: 30 }
  sentence:  { method: sentence,  size: 120, overlap: 30 }
  fixed:     { method: fixed,     size: 100, overlap: 20 }
default_chunking: recursive
retrieval: { top_k: 3, min_score: 0.0 }
vector_store: { type: pgvector }
supported_formats: [pdf, txt, md]
EOF
```

Then, in a terminal, sign in and look at what can be chosen:

```bash
# login EMAIL PASSWORD prints an access token. Defining it prints nothing, and it is
# forgotten when you close the terminal, so paste this block again in a new one.
login() {
  curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}
TOKEN=$(login "$ADMIN_EMAIL" "$ADMIN_PASSWORD")
curl -s localhost:8000/rag/options -H "Authorization: Bearer $TOKEN"
```

`/rag/options` lists the embedding models, the splitting strategies and the defaults. Embedding models whose provider is not running show `"available": false` and cannot be used.

Keep two embedding model names in variables, so the later steps work for both setups:

```bash
EMB_SMALL=fake-small
EMB_LARGE=fake-large
```

**1. Prepare (with keys)**

Start from the [first example](#example-run-the-whole-system-with-or-without-provider-api-keys), provider-keys case (steps 1, 3 and 4: `.env`, database, `make migrate`, first admin, `make run-api`, `make run-ui`). Do not use the private config of the keyless case; run `unset ANSWERWORKS_CONFIG_DIR` so the real `config/rag.yaml` applies. That file defines the embedding models and splitters:

| Name | Provider | Model | Needs |
| --- | --- | --- | --- |
| `openai-small` (default) | `openai` | `text-embedding-3-small` | `OPENAI_API_KEY` |
| `openai-large` | `openai` | `text-embedding-3-large` | `OPENAI_API_KEY` |
| `local-nomic` | `local` | `nomic-embed-text` | `local` enabled in `config/providers.yaml` and an embedding-capable server (for example Ollama with `ollama pull nomic-embed-text`) |

Anthropic has no embeddings API, so an Anthropic key alone cannot index documents; it can still answer the chat questions of step 6 (pick a Claude model in the sidebar) after another provider has done the embedding. Embedding calls are billed by the provider, but the demo file is tiny.

Then sign in as in the keyless setup (the `login` helper and `TOKEN` below), look at what can be chosen, and set the two model names:

```bash
# login EMAIL PASSWORD prints an access token. Defining it prints nothing, and it is
# forgotten when you close the terminal, so paste this block again in a new one.
login() {
  curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}
TOKEN=$(login "$ADMIN_EMAIL" "$ADMIN_PASSWORD")
curl -s localhost:8000/rag/options -H "Authorization: Bearer $TOKEN"
EMB_SMALL=openai-small
EMB_LARGE=openai-large
```

Check that the models you use show `"available": true`. A model whose key is missing is `false` and the API log names the variable to set. With `local-nomic`, set `EMB_LARGE=local-nomic` instead.

Differences from the keyless setup to expect in the steps below:

- The splitters are the ones in `config/rag.yaml` (`recursive` 800, `sentence` 500, `fixed` 1000 characters). The demo file is about 270 characters, so each index holds a single chunk and the chunk counts are equal; the index table still shows the different models and splitters. Use a longer file to see the counts differ.
- Real embeddings match meaning, not just shared words, so a question such as "what do penguins eat" ranks the penguin passage first even if the wording differs, and scores are cosine similarities you can compare between indexes of the same model only.
- In **Chat**, pick the answering model in the sidebar. Its answer is a real reply, not an echo of the prompt.

**2. Upload a document**

Create a file to upload:

```bash
cat > /tmp/penguins.txt <<'EOF'
Penguins live in the Southern Hemisphere, mostly in Antarctica. They eat fish and krill.
Emperor penguins huddle together to stay warm during the Antarctic winter.
Volcanoes are different: they erupt molten lava from magma chambers beneath the crust.
EOF
```

In the app open **Documents**. Under **My uploads** choose the file, leave the default embedding model and text splitting, and press **Upload and index**.

Same from the API:

```bash
curl -s localhost:8000/documents -H "Authorization: Bearer $TOKEN" -F file=@/tmp/penguins.txt
```

The response lists `indexes`: which embedding model (name, model, dimensions), which splitting strategy (method, size, overlap) and how many chunks that produced.

**3. See how it was indexed**

On the Documents page, open the document: **How it was indexed** is a table of embedding model and splitter, and **Show chunks** lists the stored passages with the index recorded on each one.

Same from the API:

```bash
DOC=<the id from step 2>
curl -s localhost:8000/documents/$DOC/chunks -H "Authorization: Bearer $TOKEN"
```

Each chunk carries `embedding_name`, `embedding_model`, `embedding_dimensions`, `chunking_method`, `chunk_size` and `chunk_overlap`. That record is what lets you tell, for any vector in the database, which model made it and which splitter cut its text.

**4. Index the same document a second way**

Still in the document's box, under **Add another index** choose `fake-large` (`openai-large` with keys) and `sentence`, then **Index with these settings**. The table now shows two rows with different chunk counts.

Same from the API:

```bash
curl -s localhost:8000/documents/$DOC/index -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"embedding\": \"$EMB_LARGE\", \"chunking\": \"sentence\"}"
```

**5. Compare what each index retrieves**

Only chunks of the chosen index are compared, because vectors from different models (and sizes) cannot be compared with each other. Search with each setup and look at the passages and scores:

```bash
search() {
  curl -s localhost:8000/rag/search -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$1" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["embedding_name"],d["chunking_name"]);[print(" ",h["score"],h["text"][:70]) for h in d["hits"]]'
}
search '{"query": "what do penguins eat"}'
search "{\"query\": \"what do penguins eat\", \"embedding\": \"$EMB_LARGE\", \"chunking\": \"sentence\"}"
search '{"query": "what do penguins eat", "chunking": "fixed"}'      # nothing: no chunks made this way yet
```

The last search finds nothing because the document has not been indexed with `fixed` yet. Index it that way (as in step 4) and repeat.

**6. Chat with your documents**

In **Chat**, switch on **Answer from my documents** in the sidebar (open **Retrieval settings** to pick the embedding model, splitter and shared corpora) and ask "What do penguins eat?". Under the answer, **Sources** shows the passages used, their similarity and the index they came from. With the fake provider the answer echoes the prompt, so you can read the excerpts that were sent to the model. Ask the same with the switch off to see the difference.

Same from the API:

```bash
curl -s localhost:8000/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"message\": \"What do penguins eat?\", \"use_rag\": true, \"embedding\": \"$EMB_SMALL\", \"chunking\": \"recursive\"}"
```

The response has `citations`. Open the conversation again (Conversations, then Open, or `GET /conversations/<id>`): the sources are kept with the answer.

**7. Private means private**

Sign in as another user (see [Adding users](#adding-users-admin)) and open **Documents**: your upload is not there, and a search finds none of it:

```bash
USER1_TOKEN=$(login "$USER1_EMAIL" "$USER1_PASSWORD")
curl -s localhost:8000/documents -H "Authorization: Bearer $USER1_TOKEN"            # []
curl -s localhost:8000/documents/$DOC -H "Authorization: Bearer $USER1_TOKEN"       # 404
search_as_user1() {
  curl -s localhost:8000/rag/search -H "Authorization: Bearer $USER1_TOKEN" -H 'Content-Type: application/json' \
    -d '{"query": "penguins Antarctica"}'
}
search_as_user1                                                               # no hits
```

Not even an admin can open, search or delete another user's private upload.

**8. Share a corpus (admin)**

In **Admin · Corpora** create a corpus called `handbook`, upload `/tmp/penguins.txt` into it, and grant `USER1_EMAIL`. Back as that user, **Documents** then **Shared corpora** shows it (read-only) and chat can use it. Press **Revoke** and ana's next search finds nothing again.

Same from the API:

```bash
CORPUS=$(curl -s localhost:8000/corpora -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "handbook", "description": "Demo corpus"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
curl -s localhost:8000/documents -H "Authorization: Bearer $TOKEN" -F file=@/tmp/penguins.txt -F corpus_id=$CORPUS
USER1_ID=$(curl -s localhost:8000/auth/me -H "Authorization: Bearer $USER1_TOKEN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
search_as_user1                                                               # no hits yet
curl -s -X POST localhost:8000/corpora/$CORPUS/access -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"user_id\": \"$USER1_ID\"}"
search_as_user1                                                               # hits from handbook
curl -s -X DELETE localhost:8000/corpora/$CORPUS/access/$USER1_ID -H "Authorization: Bearer $TOKEN"
search_as_user1                                                               # no hits again
```

Setting `"is_public": true` (`PATCH /corpora/$CORPUS`) makes a corpus readable by every user instead of by grant.

**9. Ingest a folder (optional)**

Corpora can also be filled from a folder, declared in the private copy of `corpora.yaml`. HTML and Word files are read as well as text and PDF:

```bash
mkdir -p /tmp/aw-handbook && cp /tmp/penguins.txt /tmp/aw-handbook/
cat > /tmp/aw-handbook/volcanoes.html <<'EOF'
<html><head><title>Volcanoes</title></head><body><h1>Volcanoes</h1>
<p>Volcanoes erupt molten lava from magma chambers beneath the crust.</p></body></html>
EOF
cat > /tmp/aw-config/corpora.yaml <<'EOF'
corpora:
  - name: folder-demo
    description: Files from a folder
    source: { type: filesystem, path: /tmp/aw-handbook }
EOF
make ingest ARGS="--corpus folder-demo"                                         # default embedding and splitter
make ingest ARGS="--corpus folder-demo --embedding $EMB_LARGE --chunking fixed" # a second index
```

The corpus appears in **Admin · Corpora** with its documents and both indexes. Run the command again after editing the files to refresh them: unchanged files are not embedded again. A file that cannot be read is kept as `failed` with the reason.

**10. Web addresses and scheduled refresh (optional)**

A corpus can also be filled from a list of web addresses, and refreshed on a schedule. Serve a page from your machine and declare a corpus with `refresh_minutes`:

```bash
mkdir -p /tmp/aw-web && cp /tmp/aw-handbook/volcanoes.html /tmp/aw-web/page.html
(cd /tmp/aw-web && python3 -m http.server 18999 --bind 127.0.0.1 &)
cat > /tmp/aw-config/corpora.yaml <<'EOF'
corpora:
  - name: web-demo
    description: A page fetched over HTTP
    public: true
    source:
      type: url
      urls:
        - http://127.0.0.1:18999/page.html
        - http://127.0.0.1:18999/missing.html
    refresh_minutes: 1
EOF
cd api && uv run python -m scripts.scheduler --once; cd ..       # ingests it, because it was never ingested
```

The page is stored as `127.0.0.1:18999/page.html`, and the address that answers 404 is listed as `failed`. In **Admin · Corpora** the corpus shows its source, "Refreshed automatically every 1 minutes", when it last ran and the problem. Run the scheduler again right away and nothing happens: the corpus is not due for another minute, and when it is, the unchanged page is not embedded again. For a long-running scheduler use `uv run python -m scripts.scheduler` (it checks every minute) or the Compose profile in [Run with Docker Compose](#run-with-docker-compose).

**11. Check the system status**

Liveness and readiness are open; the detailed view needs an admin token:

```bash
curl -s localhost:8000/health                       # {"status":"ok"}
curl -s localhost:8000/health/ready                 # database, migrations, auth, providers (503 when one fails)
curl -s localhost:8000/admin/status -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -60
```

In the web app open **Admin · System**: database and schema version, each provider with its call results, the embedding models and whether they are available, the corpora with their last ingestion (the `web-demo` corpus appears as up to date, with its problem noted), and request totals. To see readiness fail, stop the database (`make db-down`) and call `/health/ready` again: `/health` still answers 200, `/health/ready` answers 503. Start it again with `make db-up`. To try the Prometheus endpoint, put `METRICS_TOKEN=demo-token` in `.env`, restart `make run-api` and run `curl -s localhost:8000/metrics -H "Authorization: Bearer demo-token"`. More in [docs/observability.md](docs/observability.md).

**12. Clean up**

Stop `make run-ui` and `make run-api` and the page server (`kill $(lsof -ti :18999)`), then:

```bash
make db-down              # keeps the data; `make db-destroy` deletes it
rm -rf /tmp/aw-config /tmp/aw-handbook /tmp/aw-web /tmp/penguins.txt
unset ANSWERWORKS_CONFIG_DIR
make clean
```

## API access in short

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /health`, `GET /health/ready` | anyone | Liveness (process is up) and readiness (database migrated, JWT secret set, a provider loaded) |
| `POST /auth/login`, `POST /auth/refresh` | anyone | Get or renew a token pair |
| `GET /auth/me`, `POST /auth/change-password` | signed in (works while a password change is pending) | Current user, change own password |
| `GET /models`, `POST /ask` | signed in, password change done | Models and stateless questions |
| `POST /chat`, `/conversations` (create, list, read, rename, delete) | signed in, password change done; each user sees only their own | Saved conversations and chat |
| `POST /admin/users`, `GET /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/reset-password` | admin | User management |
| `GET /admin/status` | admin | Detailed system status for dashboards |
| `GET /monitoring/status` | admin, monitor | The same status for the `monitor` role |
| `GET /metrics` | `METRICS_TOKEN` bearer | Prometheus metrics (off unless the token is set) |

Details are in [api/README.md](api/README.md) and the interactive docs at `/docs`.

### The standalone demo page

[ui/demo_page.py](ui/demo_page.py) is a minimal separate UI for `/ask`, kept as originally written. It predates login and sends no token, so the API now answers it with 401 and it can't be used against this API as is. Use the main app instead.

## Configuration

| File | What it controls |
|---|---|
| [config/providers.yaml](config/providers.yaml) | Providers, their models, optional per-model pricing (USD per 1M tokens), timeouts, retries and the default provider |
| [config/app.yaml](config/app.yaml) | App name and environment, CORS origins, auth token lifetimes, how many past messages chat sends to the model, upload limit |
| [config/rag.yaml](config/rag.yaml) | Named embedding models and text-splitting strategies (with defaults), retrieval settings and accepted file types |
| [config/corpora.yaml](config/corpora.yaml) | Shared corpora to ingest from a folder or a list of web addresses with `make ingest`, each optionally refreshed every `refresh_minutes` by the scheduler |
| `.env` | Secrets and deployment values only: provider API keys, `DATABASE_URL`, `JWT_SECRET` (at least 16 characters), and optionally `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD` for `make create-admin` and `METRICS_TOKEN` to turn on `/metrics`. Never committed |

All YAML is validated at startup, so a typo or a broken reference fails loudly instead of silently misbehaving. Set `ANSWERWORKS_CONFIG_DIR` to use a different config directory.

To add a model, add an entry under its provider in `providers.yaml`. To try another embedding model or splitting strategy, add an entry to `embedding_models` or `chunking_strategies` in `rag.yaml`; documents can be indexed with several (see [docs/rag.md](docs/rag.md)). To add a different kind of backend, see [api/README.md](api/README.md).

## Development

```bash
make test        # API + UI test suites (85% coverage gate; both currently at 100%)
make lint        # ruff
make format      # ruff --fix and format
make test-e2e    # end-to-end flow against running services (see docs/testing.md)
make openapi     # rewrite docs/openapi.json after an intended API change
```

Install the hooks with `pre-commit install` to run ruff and mypy before each commit. Build the documentation site with `cd api && uv run --with mkdocs-material mkdocs build -f ../mkdocs.yml` (output in `site/`); more in [docs/contributing.md](docs/contributing.md).

Tests never reach a real provider; adapters are tested against mocked HTTP. Automatic CI runs are deliberately disabled for now; the workflows in `.github/workflows/` can be started manually from the Actions tab.

## Layout

| Path | Purpose |
|---|---|
| `api/` | FastAPI backend and its tests; see [api/README.md](api/README.md) |
| `ui/` | Streamlit frontend and its tests; see [ui/README.md](ui/README.md) |
| `config/` | Non-secret YAML configuration |
| `docs/` | Documentation site sources (`mkdocs.yml`): architecture, configuration, deployment, observability, API, RAG, UI, data model, admin guide, testing, contributing; plus `openapi.json` |
| `docker-compose.yml`, `api/Dockerfile`, `ui/Dockerfile` | Run the database, API and web app in containers |
| `tests_e2e/` | End-to-end test and its keyless config |
| `Makefile` | Install, run, test, lint, migrate, create-admin, ingest and local-database commands |

`api/` and `ui/` are separate uv projects with their own environments, which is why `make install` syncs both.

## Roadmap

| Step | Scope | Status |
|---|---|---|
| 1 | Skeleton: configs, Makefile, two packages, CI stubs | Done |
| 2 | API core: validated config, PostgreSQL, migrations, health | Done |
| 3 | Provider layer: Anthropic, OpenAI, local and fake providers | Done |
| 4 | Auth and users: login, JWT, roles, admin-created accounts | Done |
| 5 | Conversations and chat: persistence and streaming (API) | Done |
| 6 | UI: chat, conversations, question-answer and admin users pages | Done |
| 7 | RAG: documents, shared corpora, configurable embedding models and splitters, retrieval with citations | Done |
| 8 | Docker Compose, docs site, contract and end-to-end tests | Done |
| 9 | Liveness/readiness and system status, Word and HTML parsers, web-address sources, scheduled corpus refresh | Done |

## License

Released under the [MIT License](LICENSE).
