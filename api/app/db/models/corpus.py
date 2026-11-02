import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.conversation import utcnow


class Corpus(Base):
    """A shared collection of documents. Visible to users with a grant, or to everyone if public."""

    __tablename__ = "corpora"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # Where ingestion reads files from, e.g. {"type": "filesystem", "path": "..."} or
    # {"type": "url", "urls": [...]}; may be empty.
    source_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Re-ingest this often (minutes) when the scheduler runs; null means manual only.
    refresh_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    # The last time ingestion finished (manual or scheduled), and what went wrong, if anything.
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_ingest_error: Mapped[str | None] = mapped_column(Text, default=None)


class CorpusAccess(Base):
    """An explicit grant of one corpus to one user."""

    __tablename__ = "corpus_access"

    corpus_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corpora.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
