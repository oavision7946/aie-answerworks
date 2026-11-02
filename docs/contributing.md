# Contributing

## Set up

```bash
make install            # uv sync in api/ and ui/
make test               # both suites
make lint
```

Install the pre-commit hooks once with `pre-commit install`; they run ruff and mypy for each package, like `make lint` plus the type check.

## Conventions

- Tests ship with the change. Keep each package at or above 85% coverage.
- Routes stay thin: logic goes in services, queries in repositories, and nothing outside `services/llm` imports a provider SDK.
- Every route needs a token unless it is deliberately open; the contract test fails otherwise.
- Do not commit `.env`, keys or personal data. Use the fake provider for demos and tests.
- A changed database model needs an Alembic migration (a test fails when they drift): `cd api && uv run alembic revision --autogenerate -m "..."`.
- A changed API needs `make openapi` and a look at the diff of `docs/openapi.json`.

## Build the documentation

```bash
cd api && uv run --with mkdocs-material mkdocs build -f ../mkdocs.yml
```

The site is written to `site/` (ignored by git). Use `mkdocs serve` instead of `mkdocs build` to preview it with live reload.

## Continuous integration

The workflows in `.github/workflows/` run ruff, mypy and the tests for each package (Python 3.13, dependencies from `uv.lock` with uv). They are started manually from the Actions tab; the commented `push` and `pull_request` triggers at the top of each file turn automatic runs back on.
