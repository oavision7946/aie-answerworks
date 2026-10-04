.PHONY: install install-api install-ui run-api run-ui test test-api test-ui lint format migrate docs clean

API_DIR := api
UI_DIR  := ui

install: install-api install-ui

install-api:
	cd $(API_DIR) && uv sync --extra dev

install-ui:
	cd $(UI_DIR) && uv sync --extra dev

run-api:
	cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000

run-ui:
	cd $(UI_DIR) && uv run streamlit run app/main.py --server.port 8501

test: test-api test-ui

test-api:
	cd $(API_DIR) && uv run pytest

test-ui:
	cd $(UI_DIR) && uv run pytest

lint:
	cd $(API_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(UI_DIR) && uv run ruff check . && uv run ruff format --check .

format:
	cd $(API_DIR) && uv run ruff check --fix . && uv run ruff format .
	cd $(UI_DIR) && uv run ruff check --fix . && uv run ruff format .

migrate:
	cd $(API_DIR) && uv run alembic upgrade head

docs:
	mkdocs build

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name .pytest_cache -type d -prune -exec rm -rf {} +
	rm -rf site
