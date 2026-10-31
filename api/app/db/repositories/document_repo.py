"""Document and chunk queries."""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document


@dataclass(frozen=True)
class IndexSummary:
    """One distinct way a document has been indexed, with how many chunks it produced."""

    embedding_name: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    chunking_name: str
    chunking_method: str
    chunk_size: int
    chunk_overlap: int
    chunk_count: int


INDEX_COLUMNS = (
    Chunk.embedding_name,
    Chunk.embedding_provider,
    Chunk.embedding_model,
    Chunk.embedding_dimensions,
    Chunk.chunking_name,
    Chunk.chunking_method,
    Chunk.chunk_size,
    Chunk.chunk_overlap,
)


def save(db: Session, document: Document) -> Document:
    db.add(document)
    db.commit()
    return document


def delete(db: Session, document: Document) -> None:
    db.delete(document)
    db.commit()


def get(db: Session, document_id: uuid.UUID, visible: ColumnElement[bool]) -> Document | None:
    return db.scalar(select(Document).where(Document.id == document_id, visible))


def get_in_corpus(db: Session, corpus_id: uuid.UUID, filename: str) -> Document | None:
    return db.scalar(
        select(Document).where(Document.corpus_id == corpus_id, Document.filename == filename)
    )


def list_where(
    db: Session, condition: ColumnElement[bool], limit: int = 100, offset: int = 0
) -> list[Document]:
    query = (
        select(Document)
        .where(condition)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query))


def index_summaries(
    db: Session, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[IndexSummary]]:
    rows = db.execute(
        select(Chunk.document_id, *INDEX_COLUMNS, func.count())
        .where(Chunk.document_id.in_(document_ids))
        .group_by(Chunk.document_id, *INDEX_COLUMNS)
        .order_by(Chunk.embedding_name, Chunk.chunking_name)
    )
    summaries: dict[uuid.UUID, list[IndexSummary]] = {}
    for document_id, *fields in rows:
        summaries.setdefault(document_id, []).append(IndexSummary(*fields))
    return summaries


def chunks_of(db: Session, document_id: uuid.UUID, limit: int, offset: int) -> list[Chunk]:
    query = (
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.embedding_name, Chunk.chunking_name, Chunk.chunk_index)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query))
