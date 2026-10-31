import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.conversation import utcnow

# pgvector on PostgreSQL; plain JSON on SQLite so the unit tests need no extension.
EmbeddingType = Vector().with_variant(JSON(), "sqlite")


class DocumentStatus(enum.StrEnum):
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    """An uploaded or ingested file. Owned by one user, or part of one corpus (never both)."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "(owner_id IS NULL) <> (corpus_id IS NULL)", name="exactly_one_of_owner_and_corpus"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None
    )
    corpus_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("corpora.id", ondelete="CASCADE"), index=True, default=None
    )
    filename: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda e: [m.value for m in e])
    )
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # The extracted text, kept so the document can be indexed again with another model or splitter.
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(Base):
    """One piece of a document with its embedding and a record of how both were produced."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingType)

    # How the embedding was made: only vectors from the same model are comparable.
    embedding_name: Mapped[str] = mapped_column(String(100))
    embedding_provider: Mapped[str] = mapped_column(String(100))
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_dimensions: Mapped[int] = mapped_column(Integer)
    # How the text was split.
    chunking_name: Mapped[str] = mapped_column(String(100))
    chunking_method: Mapped[str] = mapped_column(String(50))
    chunk_size: Mapped[int] = mapped_column(Integer)
    chunk_overlap: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="chunks")
