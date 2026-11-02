# Build from the repository root:  docker build -f api/Dockerfile -t answerworks-api .
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# The app finds config/ two levels above api/app/core, so keep this layout.
WORKDIR /srv/answerworks/api

COPY api/pyproject.toml api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY api/ ./
COPY config/ /srv/answerworks/config/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN useradd --system --no-create-home answerworks
USER answerworks

ENV PATH="/srv/answerworks/api/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# Apply migrations, then serve. Safe to repeat: migrations that are already applied are skipped.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
