# Testing

| Suite | Where | Run | Needs |
|---|---|---|---|
| API | `api/tests` (unit, integration, contract) | `make test-api` | Nothing: SQLite in memory, mocked HTTP |
| Web app | `ui/tests` (client, state, Streamlit `AppTest` pages) | `make test-ui` | Nothing |
| End to end | `tests_e2e` | `make test-e2e` | Running services (below) |

`make test` runs the API and web app suites. Each package must keep at least 85% coverage; `make lint` runs ruff, and `mypy` is strict in both packages. No test reaches a real provider or the network: adapters are tested against mocked HTTP and everything above them uses the built-in fake provider and deterministic fake embeddings.

## Contract test

`api/tests/contract/test_openapi_snapshot.py` compares the live OpenAPI schema with `docs/openapi.json` and checks that every route except the open ones (`/health`, `/health/ready`, login and refresh) demands a token. Regenerate the snapshot with `make openapi` after an intended change.

## PostgreSQL tests

Migration and pgvector tests are skipped unless `TEST_POSTGRES_URL` points at a scratch database. They drop and recreate tables, so never point it at data you want to keep.

```bash
make db-up
TEST_POSTGRES_URL=postgresql+psycopg://answerworks:answerworks@localhost:5432/scratch make test-api
```

## End-to-end test

`tests_e2e/test_full_flow.py` checks liveness and readiness, signs in, reads the admin status, creates a user (who must change the temporary password), uploads a document, chats with documents on, reads the conversation back with its sources checks that another user cannot see any of it and that the run shows up in the provider counters. It needs no keys: `tests_e2e/config` holds a config with only the fake provider and fake embedding models.

```bash
export COMPOSE_PROJECT_NAME=aw-e2e API_PORT=18000 UI_PORT=18501 CONFIG_DIR=./tests_e2e/config
docker compose up --build -d
export E2E_ADMIN_EMAIL=<admin email> E2E_ADMIN_PASSWORD=<admin password>   # 12 to 128 characters
docker compose run --rm -e BOOTSTRAP_ADMIN_EMAIL="$E2E_ADMIN_EMAIL" \
  -e BOOTSTRAP_ADMIN_PASSWORD="$E2E_ADMIN_PASSWORD" api python -m scripts.create_admin
make test-e2e
docker compose down -v
```

The test is skipped when the API is not reachable or the two admin variables are unset. `E2E_API_URL` and `E2E_UI_URL` override the ports used above. The regular user it creates gets a random email and passwords unless you set `E2E_USER1_EMAIL`, `E2E_USER1_TEMP_PASSWORD` and `E2E_USER1_PASSWORD`.
