# Admin guide

## Bootstrap the first admin

Accounts are created by admins, so the first one comes from a script. Set `DATABASE_URL` and `JWT_SECRET` in `.env`, run the migrations, then:

```bash
make migrate
make create-admin
```

The script prompts for an email and password. For non-interactive use, set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` in the environment. It refuses to run if an active admin already exists or the email is taken, and there is no default password. The admin it creates is not forced to change the password.

## Sign in as admin

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "admin@example.com", "password": "..."}'
```

Use the returned `access_token` as a bearer token in the calls below, or use the interactive docs at `/docs`.

## Manage users

All routes need an admin access token.

| Action | Request |
|---|---|
| Create | `POST /admin/users` with `email` and `temporary_password` (optional `role`) |
| List | `GET /admin/users` |
| Change role or active flag | `PATCH /admin/users/{id}` with `role` and/or `is_active` |
| Reset password | `POST /admin/users/{id}/reset-password` with `temporary_password` |

```bash
curl -s -X POST http://localhost:8000/admin/users \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"email": "ana@example.com", "temporary_password": "a-long-temporary-pass"}'
```

Temporary passwords follow the same length rules as normal ones (12 to 128 characters). Share the temporary password with the user over a secure channel. On first sign-in they must set their own password before using the app.

Emails are stored lowercased. Creating a duplicate returns 409.

## From the web app

Signed in as an admin, the **Admin · Users** page does the same without curl: the table lists accounts, **Add a user** creates one with a temporary password and a role, and **Manage a user** changes the role, deactivates or reactivates an account, or resets its password. The API's messages (for example the self-lockout rule) are shown on the page.

## Shared corpora

A corpus is a shared collection of documents. Users can read it when it is public or when you grant them access; nobody else sees it, and revoking takes effect on their next request. You also need a grant (or the public flag) for your own searches to include a corpus.

```bash
# create, upload a file into it, grant a user, then ingest a source folder
curl -s localhost:8000/corpora -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "handbook", "description": "Policies", "is_public": false}'
curl -s localhost:8000/documents -H "Authorization: Bearer $TOKEN" -F file=@policy.md -F corpus_id=$CORPUS_ID
curl -s localhost:8000/corpora/$CORPUS_ID/access -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"user_id\": \"$USER_ID\"}"
curl -s localhost:8000/corpora/$CORPUS_ID/ingest -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"embedding": "openai-small", "chunking": "recursive"}'
```

Corpora declared in `config/corpora.yaml` are created or updated by the command-line tool. A `filesystem` source indexes every supported file (PDF, TXT, Markdown, Word, HTML) under a folder, and a `url` source fetches a list of web addresses:

```bash
make ingest ARGS="--corpus handbook"
make ingest ARGS="--all --embedding openai-large --chunking sentence"   # a second index for the same files
```

Run it again after the files change: documents are matched by their path in the folder (or by `host/path` for web pages), and unchanged ones are not embedded again. A file that cannot be read is kept with status `failed` and a reason, and shows to admins only. Set `refresh_minutes` on a corpus and run `python -m scripts.scheduler` (Compose profile `scheduler`) to refresh it automatically; the Corpora page shows the source, the interval, when it last ran and the last problem. The **Admin · Corpora** page offers the same operations. Details: [Documents and corpora](api/documents.md), [RAG](rag.md).

## Check the system

**Admin · System** in the web app (or `GET /admin/status`) shows whether the database and its schema are current, which providers loaded and why one did not, how each provider's calls have gone since the API started, which embedding models are usable, when each corpus was last ingested, row counts and request totals. For monitoring from outside, see [Observability](observability.md).

## Deactivate a user

```bash
curl -s -X PATCH http://localhost:8000/admin/users/$USER_ID \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"is_active": false}'
```

The user is locked out immediately, even with an unexpired token. You cannot deactivate or demote yourself.

## Known limits

Login attempts are not rate limited.
