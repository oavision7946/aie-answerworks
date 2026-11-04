# Deployment with Docker Compose

`docker-compose.yml` runs the database (PostgreSQL with pgvector), the API and the web app. Each image is built from the repository root with `api/Dockerfile` and `ui/Dockerfile`.

```bash
cp .env.example .env              # set JWT_SECRET and the provider keys you use
docker compose up --build -d
docker compose run --rm api python -m scripts.create_admin     # first admin
```

Open http://localhost:8501 for the web app and http://localhost:8000/docs for the API.

## What the compose file does

- **db:** `pgvector/pgvector:pg17`, data in the `db-data` volume, not published on the host.
- **api:** applies the migrations at start (`alembic upgrade head`), then serves on port 8000. It reads secrets from `.env` and overrides `DATABASE_URL` to point at `db`. `config/` is mounted read-only, so edit the YAML and run `docker compose restart api` to apply a change.
- **ui:** the Streamlit app, with `API_BASE_URL=http://api:8000`. It starts when the API reports healthy.

- **scheduler** (optional, profile `scheduler`): re-ingests corpora that set `refresh_minutes`. Start it with `docker compose --profile scheduler up -d`. A `filesystem` source must be mounted into the container; `url` sources need nothing more.

The images run as a non-root user and have a health check (`/health` for the API, which does not depend on the database, and `/_stcore/health` for the web app). Point a load balancer or orchestrator's *readiness* probe at `/health/ready`. See [Observability](observability.md).

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `API_PORT`, `UI_PORT` | `8000`, `8501` | Host ports |
| `CONFIG_DIR` | `./config` | Config directory to mount |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `answerworks` | Database credentials. Change the password for anything beyond a local machine |

Use another project name (`docker compose -p name ...`) to run a second copy side by side.

## Local model servers

Inside a container, `localhost` is the container itself. For Ollama or another server on the host, set `base_url` to `http://host.docker.internal:<port>` in `providers.yaml`.

## Stop and clean up

```bash
docker compose down               # keeps the database
docker compose down -v            # also deletes the database volume
docker compose down -v --rmi local  # and removes the images built for this project
docker builder prune              # optional: clears the build cache
```

Compose writes nothing into the repository folder (`config/` is mounted read-only), so `make clean` is only for caches left by running tests or the API directly on the host.

The setup has no TLS and the web app serves plain HTTP. Put a reverse proxy with HTTPS in front of both ports before exposing them beyond your own network.
