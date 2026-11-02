"""Is the system able to do its job? Cheap checks for orchestrators, detail for dashboards."""

import logging
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib import metadata
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.core.telemetry import telemetry
from app.db.repositories import corpus_repo, stats_repo
from app.schemas.status import (
    CorpusStatus,
    DatabaseStatus,
    EmbeddingStatus,
    ProviderCalls,
    ProviderStatus,
    Readiness,
    RequestStatus,
    SystemStatus,
)
from app.services.llm.registry import ProviderRegistry

logger = logging.getLogger(__name__)

API_ROOT = Path(__file__).resolve().parents[2]


@lru_cache
def schema_head() -> str | None:
    """The newest migration shipped with this build."""
    config = Config()
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def version() -> str:
    try:
        return metadata.version("answerworks-api")
    except metadata.PackageNotFoundError:  # pragma: no cover (running without an install)
        return "unknown"


def database(engine: Engine) -> DatabaseStatus:
    head = schema_head()
    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            latency = round((time.perf_counter() - started) * 1000, 1)
            revision = _revision(connection)
            pgvector = _has_pgvector(connection)
    except Exception:
        logger.error("Database check failed", exc_info=True)
        return DatabaseStatus(
            status="unavailable",
            latency_ms=None,
            revision=None,
            head=head,
            migrated=False,
            pgvector=None,
        )
    return DatabaseStatus(
        status="ok",
        latency_ms=latency,
        revision=revision,
        head=head,
        migrated=revision == head,
        pgvector=pgvector,
    )


def _revision(connection: Connection) -> str | None:
    try:
        value = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return None if value is None else str(value)
    except Exception:
        connection.rollback()
        return None


def _has_pgvector(connection: Connection) -> bool | None:
    if connection.dialect.name == "postgresql":  # pragma: no cover (see test_pgvector_store)
        query = text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return connection.execute(query).scalar() is not None
    return None


def readiness(engine: Engine, settings: Settings, registry: ProviderRegistry) -> Readiness:
    """What the API needs to serve requests. Messages stay generic: this route is public."""
    return _readiness(database(engine), settings, registry)


def _readiness(db: DatabaseStatus, settings: Settings, registry: ProviderRegistry) -> Readiness:
    checks = {
        "database": "ok" if db.status == "ok" else "unavailable",
        "migrations": "ok" if db.migrated else "unavailable",
        "auth": "ok" if settings.env.jwt_secret else "unavailable",
        "providers": "ok" if registry.providers else "unavailable",
    }
    if db.pgvector is not None:  # pragma: no cover (PostgreSQL only; see test_pgvector_store)
        checks["pgvector"] = "ok" if db.pgvector else "unavailable"
    ready = all(value == "ok" for value in checks.values())
    return Readiness(status="ok" if ready else "degraded", checks=checks)


def _providers(settings: Settings, registry: ProviderRegistry) -> list[ProviderStatus]:
    stats = telemetry.snapshot()["providers"]
    result = []
    for name, config in settings.providers.enabled.items():
        loaded = registry.providers.get(name)
        reason = None
        if loaded is None:
            reason = f"{config.api_key_env} is not set" if config.api_key_env else "not available"
        calls = [
            ProviderCalls(
                operation=operation,
                ok=s.ok,
                error=s.error,
                average_ms=round(s.seconds / (s.ok + s.error) * 1000, 1),
                last_success_at=s.last_success_at,
                last_error_at=s.last_error_at,
            )
            for (provider, operation), s in sorted(stats.items())
            if provider == name
        ]
        result.append(
            ProviderStatus(
                name=name,
                type=config.type,
                loaded=loaded is not None,
                reason=reason,
                default=name == registry.default_provider,
                models=len(config.models),
                calls=calls,
            )
        )
    return result


def _corpora(db: Session, now: datetime) -> list[CorpusStatus]:
    corpora = corpus_repo.list_where(db)
    counts = corpus_repo.document_counts(db, [c.id for c in corpora])
    result = []
    for c in corpora:
        last = c.last_ingested_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        overdue = False
        if c.refresh_minutes and c.source_config:
            deadline = timedelta(minutes=2 * c.refresh_minutes)
            overdue = last is None or now - last > deadline
        result.append(
            CorpusStatus(
                name=c.name,
                source_type=c.source_config.get("type"),
                documents=counts.get(c.id, 0),
                refresh_minutes=c.refresh_minutes,
                last_ingested_at=last,
                last_ingest_error=c.last_ingest_error,
                overdue=overdue,
            )
        )
    return result


def system_status(
    db: Session, engine: Engine, settings: Settings, registry: ProviderRegistry
) -> SystemStatus:
    database_status = database(engine)
    ready = _readiness(database_status, settings, registry)
    snapshot = telemetry.snapshot()
    total = snapshot["requests_total"]
    providers = _providers(settings, registry)
    corpora = _corpora(db, datetime.now(UTC)) if database_status.status == "ok" else []
    healthy = ready.status == "ok" and not any(c.overdue for c in corpora)
    return SystemStatus(
        status="ok" if healthy else "degraded",
        version=version(),
        environment=settings.app.app.environment,
        uptime_seconds=round(telemetry.uptime_seconds, 1),
        database=database_status,
        auth_configured=bool(settings.env.jwt_secret),
        providers=providers,
        embedding_models=[
            EmbeddingStatus(
                name=name,
                provider=m.provider,
                model=m.model,
                dimensions=m.dimensions,
                available=m.provider in registry.providers,
            )
            for name, m in settings.rag.embedding_models.items()
        ],
        corpora=corpora,
        counts=stats_repo.counts(db) if database_status.status == "ok" else {},
        requests=RequestStatus(
            total=total,
            by_status=snapshot["requests_by_status"],
            average_ms=round(snapshot["request_seconds"] / total * 1000, 1) if total else None,
        ),
    )


def _number(value: float) -> float | int:
    return int(value) if isinstance(value, bool) else value


def prometheus(db: Session, engine: Engine, settings: Settings, registry: ProviderRegistry) -> str:
    """The same numbers as the status page in the Prometheus text format."""
    status = system_status(db, engine, settings, registry)
    lines: list[str] = []

    def metric(name: str, kind: str, help_text: str, samples: list[tuple[str, float]]) -> None:
        lines.append(f"# HELP answerworks_{name} {help_text}")
        lines.append(f"# TYPE answerworks_{name} {kind}")
        lines.extend(f"answerworks_{name}{labels} {_number(value)}" for labels, value in samples)

    def label(**pairs: str) -> str:
        escaped = {k: v.replace("\\", "\\\\").replace('"', '\\"') for k, v in pairs.items()}
        return "{" + ",".join(f'{k}="{v}"' for k, v in escaped.items()) + "}"

    metric("up", "gauge", "1 while the API process is running.", [("", 1)])
    metric("ready", "gauge", "1 when the API can serve requests.", [("", status.status == "ok")])
    metric(
        "uptime_seconds", "gauge", "Seconds since the API started.", [("", status.uptime_seconds)]
    )
    metric(
        "database_up", "gauge", "1 when the database answers.",
        [("", status.database.status == "ok")],
    )  # fmt: skip
    metric(
        "database_latency_ms", "gauge", "Time of the last database check.",
        [("", status.database.latency_ms or 0)],
    )  # fmt: skip
    metric(
        "provider_loaded", "gauge", "1 when the provider is configured and has its key.",
        [(label(provider=p.name), p.loaded) for p in status.providers],
    )  # fmt: skip
    calls = [(p.name, c) for p in status.providers for c in p.calls]
    metric(
        "provider_calls_total", "counter", "Provider calls since start, by outcome.",
        [
            (label(provider=n, operation=c.operation, outcome=outcome), count)
            for n, c in calls
            for outcome, count in (("ok", c.ok), ("error", c.error))
        ],
    )  # fmt: skip
    metric(
        "requests_total", "counter", "HTTP responses since start, by status class.",
        [(label(status=k), v) for k, v in sorted(status.requests.by_status.items())],
    )  # fmt: skip
    metric(
        "request_duration_seconds_sum", "counter", "Total time spent answering requests.",
        [("", round(telemetry.snapshot()["request_seconds"], 6))],
    )  # fmt: skip
    metric(
        "request_duration_seconds_count", "counter", "Requests timed.",
        [("", status.requests.total)],
    )  # fmt: skip
    metric(
        "rows", "gauge", "Rows stored, by kind.",
        [(label(kind=k), v) for k, v in sorted(status.counts.items())],
    )  # fmt: skip
    metric(
        "corpus_last_ingested_timestamp_seconds", "gauge", "When each corpus was last ingested.",
        [
            (label(corpus=c.name), c.last_ingested_at.timestamp())
            for c in status.corpora
            if c.last_ingested_at
        ],
    )  # fmt: skip
    metric(
        "corpus_overdue", "gauge", "1 when a scheduled corpus missed its refresh.",
        [(label(corpus=c.name), c.overdue) for c in status.corpora],
    )  # fmt: skip
    return "\n".join(lines) + "\n"
