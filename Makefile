.PHONY: install install-api install-ui run-api run-ui test test-api test-ui lint format migrate docs clean

API_DIR := api
UI_DIR  := ui

install: install-api install-ui

install-api:
	cd $(API_DIR) && pip install -e ".[dev]"

install-ui:
	cd $(UI_DIR) && pip install -e ".[dev]"

run-api:
	cd $(API_DIR) && uvicorn app.main:app --reload --port 8000

run-ui:
	cd $(UI_DIR) && streamlit run app/main.py --server.port 8501

test: test-api test-ui

test-api:
	cd $(API_DIR) && pytest

test-ui:
	cd $(UI_DIR) && pytest

lint:
	cd $(API_DIR) && ruff check . && ruff format --check .
	cd $(UI_DIR) && ruff check . && ruff format --check .

format:
	cd $(API_DIR) && ruff check --fix . && ruff format .
	cd $(UI_DIR) && ruff check --fix . && ruff format .

migrate:
	cd $(API_DIR) && alembic upgrade head

docs:
	mkdocs build

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name .pytest_cache -type d -prune -exec rm -rf {} +
	rm -rf site
