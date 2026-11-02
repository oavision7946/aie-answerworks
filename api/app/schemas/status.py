from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Level = Literal["ok", "degraded"]


class Readiness(BaseModel):
    status: Level
    checks: dict[str, str]  # each check is "ok" or "unavailable"


class DatabaseStatus(BaseModel):
    status: Literal["ok", "unavailable"]
    latency_ms: float | None
    revision: str | None  # schema version applied to the database
    head: str | None  # newest schema version in this build
    migrated: bool  # the database schema is up to date
    pgvector: bool | None  # null when the database is not PostgreSQL


class ProviderCalls(BaseModel):
    operation: str  # complete, stream or embed
    ok: int
    error: int
    average_ms: float | None
    last_success_at: datetime | None
    last_error_at: datetime | None


class ProviderStatus(BaseModel):
    name: str
    type: str
    loaded: bool
    reason: str | None  # why a configured provider is not loaded
    default: bool
    models: int
    calls: list[ProviderCalls]


class EmbeddingStatus(BaseModel):
    name: str
    provider: str
    model: str
    dimensions: int
    available: bool


class CorpusStatus(BaseModel):
    name: str
    source_type: str | None
    documents: int
    refresh_minutes: int | None
    last_ingested_at: datetime | None
    last_ingest_error: str | None
    overdue: bool  # a scheduled corpus that has not been ingested within twice its interval


class RequestStatus(BaseModel):
    total: int
    by_status: dict[str, int]
    average_ms: float | None


class SystemStatus(BaseModel):
    status: Level
    version: str
    environment: str
    uptime_seconds: float
    database: DatabaseStatus
    auth_configured: bool
    providers: list[ProviderStatus]
    embedding_models: list[EmbeddingStatus]
    corpora: list[CorpusStatus]
    counts: dict[str, int]
    requests: RequestStatus
