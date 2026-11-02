# Testing

| Suite | Where | Run | Needs |
|---|---|---|---|
| API | `api/tests` (unit, integration, contract) | `make test-api` | Nothing: SQLite in memory, mocked HTTP |
| Web app | `ui/tests` (client, state, Streamlit `AppTest` pages) | `make test-ui` | Nothing |
| End to end | `tests_e2e` | `make test-e2e` | Running services (below) |

`make test` runs the API and web app suites. Each package must keep at least 85% coverage; `make lint` runs ruff, and `mypy` is strict in both packages. No test reaches a real provider or the network: adapters are tested against mocked HTTP and everything above them uses the built-in fake provider and deterministic fake embeddings.

## Contract test

`api/tests/contract/test_openapi_snapshot.py` compares the live OpenAPI schema with `docs/openapi.json` and checks that every route except the open ones demands a token. Regenerate the snapshot with `make openapi` after an intended change.

## PostgreSQL tests

Migration and pgvector tests are skipped unless `TEST_POSTGRES_URL` points at a scratch database. They drop and recreate tables, so never point it at data you want to keep.

```bash
make db-up
TEST_POSTGRES_URL=postgresql+psycopg://answerworks:answerworks@localhost:5432/scratch make test-api
```

## End-to-end test

`tests_e2e/test_full_flow.py` signs in, creates a user (who must change the temporary password), uploads a document, chats with documents on, reads the conversation back with its sources and checks that another user cannot see any of it. It needs no keys: `tests_e2e/config` holds a config with only the fake provider and fake embedding models.

```bash
export COMPOSE_PROJECT_NAME=aw-e2e API_PORT=18000 UI_PORT=18501 CONFIG_DIR=./tests_e2e/config
docker compose up --build -d
docker compose run --rm -e BOOTSTRAP_ADMIN_EMAIL=e2e-admin@example.com \
  -e BOOTSTRAP_ADMIN_PASSWORD='e2e admin passphrase' api python -m scripts.create_admin
make test-e2e
docker compose down -v
```

The test is skipped when the API is not reachable. `E2E_API_URL`, `E2E_UI_URL`, `E2E_ADMIN_EMAIL` and `E2E_ADMIN_PASSWORD` override the defaults used above.
