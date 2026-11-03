# AnswerWorks: instructions for Claude Code

FastAPI API (`api/`) and Streamlit UI (`ui/`), PostgreSQL with pgvector, YAML config in `config/`, secrets in `.env`. Python 3.13, `uv`. Each of `api/` and `ui/` is its own uv project. The README and `docs/` describe the system; read them before changing behavior.

## Commands (run from the repo root)

- `make install`: `uv sync` in both packages
- `make test`: both test suites. No database, keys or network needed. Coverage gate is 85%.
- `make lint` / `make format`: ruff for `api/`, `ui/` and `tests_e2e/`
- `cd api && uv run mypy app scripts` and `cd ui && uv run mypy app`: strict typing
- `make migrate`, `make create-admin`, `make run-api`, `make run-ui`, `make db-up`
- `make openapi`: rewrite `docs/openapi.json` after an intended API change (a contract test compares against it)
- `make test-e2e`: needs the Docker stack described in `docs/testing.md`

## Conventions

- Match the surrounding code: naming, comment density, idiom. Tests use `unittest` style (run by pytest); HTTP is mocked with `respx`, the UI is tested with Streamlit `AppTest`.
- A change is not done until `make test`, `make lint` and mypy pass, and docs (README, `docs/`) reflect user-visible behavior.
- Database changes need an Alembic migration in `api/migrations/versions/` and a test; check it on SQLite and, when `TEST_POSTGRES_URL` is set, on PostgreSQL. Those Postgres tests drop tables, so point them only at a scratch database.
- Providers, models, prices, corpora and RAG settings live in `config/*.yaml`. Secrets and deployment values live only in `.env`; never commit `.env` or paste keys into code, docs or tests.
- Tests must not reach a real provider or the network.

## Git

- Commit or push only when asked. Review `git diff --cached` first.
- Pre-commit hooks (`pre-commit install --hook-type pre-commit --hook-type commit-msg`) run lint, typing and a private-material check. Do not bypass them with `--no-verify`.
