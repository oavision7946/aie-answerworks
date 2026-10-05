.PHONY: db-up db-down db-logs db-destroy install install-api install-ui run-api run-ui test test-api test-ui lint format migrate docs clean

API_DIR := api
UI_DIR  := ui

# Local PostgreSQL (with pgvector) for development. Override on the command line, e.g.
#   make db-up DB_PORT=55432   (then set DATABASE_URL in .env to use the same port)
DB_CONTAINER ?= answerworks-db
DB_IMAGE     ?= pgvector/pgvector:pg17
DB_PORT      ?= 5432
DB_USER      ?= answerworks
DB_PASSWORD  ?= answerworks
DB_NAME      ?= answerworks
DB_VOLUME    ?= answerworks-db-data

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

# Start (creating on first use) the local database and wait until it accepts connections.
db-up:
	@if [ -n "$$(docker ps -q -f name=^$(DB_CONTAINER)$$)" ]; then \
		echo "$(DB_CONTAINER) is already running"; \
	elif [ -n "$$(docker ps -aq -f name=^$(DB_CONTAINER)$$)" ]; then \
		docker start $(DB_CONTAINER) >/dev/null && echo "started existing $(DB_CONTAINER)"; \
	else \
		docker run -d --name $(DB_CONTAINER) \
			-e POSTGRES_USER=$(DB_USER) -e POSTGRES_PASSWORD=$(DB_PASSWORD) -e POSTGRES_DB=$(DB_NAME) \
			-p 127.0.0.1:$(DB_PORT):5432 -v $(DB_VOLUME):/var/lib/postgresql/data \
			$(DB_IMAGE) >/dev/null && echo "created $(DB_CONTAINER) on port $(DB_PORT)"; \
	fi
	@for i in $$(seq 1 30); do \
		docker exec $(DB_CONTAINER) pg_isready -q -U $(DB_USER) -d $(DB_NAME) && exit 0; sleep 1; \
	done; echo "database did not become ready" >&2; exit 1
	@echo "DATABASE_URL=postgresql+psycopg://$(DB_USER):$(DB_PASSWORD)@localhost:$(DB_PORT)/$(DB_NAME)"

# Stop the database; data is kept in the $(DB_VOLUME) volume.
db-down:
	-docker stop $(DB_CONTAINER)

db-logs:
	docker logs -f --tail 100 $(DB_CONTAINER)

# DESTRUCTIVE: remove the container and its data volume.
db-destroy:
	-docker rm -f $(DB_CONTAINER)
	-docker volume rm $(DB_VOLUME)
