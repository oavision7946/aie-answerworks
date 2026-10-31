"""Documents for the signed-in user: upload, list, inspect, re-index, delete.

Users manage their own uploads. Administrators additionally manage documents of shared corpora.
Anything a user may not see answers "not found".
"""

import uuid

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, DocumentStatus, Role, User
from app.db.repositories import corpus_repo, document_repo
from app.schemas.rag import DocumentOut, IndexInfo
from app.services.rag import ingestion
from app.services.rag.context import RagContext
from app.services.rag.errors import RagError
from app.services.rag.parsers import ParseError
from app.services.rag.retriever import accessible_corpus_ids, eligible_documents

NOT_FOUND = "Document not found."


def manageable(user: User) -> ColumnElement[bool]:
    """Documents `user` may change: their own uploads, and corpus documents for administrators."""
    if user.role == Role.ADMIN:
        return or_(Document.owner_id == user.id, Document.corpus_id.is_not(None))
    return Document.owner_id == user.id


def visible(user: User) -> ColumnElement[bool]:
    return or_(eligible_documents(user), manageable(user))


def _out(db: Session, documents: list[Document]) -> list[DocumentOut]:
    summaries = document_repo.index_summaries(db, [d.id for d in documents])
    return [
        DocumentOut(
            id=d.id,
            filename=d.filename,
            size_bytes=d.size_bytes,
            status=d.status,
            error=d.error,
            owner_id=d.owner_id,
            corpus_id=d.corpus_id,
            created_at=d.created_at,
            indexes=[IndexInfo.model_validate(s) for s in summaries.get(d.id, [])],
        )
        for d in documents
    ]


def describe(db: Session, document: Document) -> DocumentOut:
    return _out(db, [document])[0]


def get(db: Session, user: User, document_id: uuid.UUID, *, manage: bool = False) -> Document:
    document = document_repo.get(db, document_id, manageable(user) if manage else visible(user))
    if document is None:
        raise RagError(404, NOT_FOUND)
    return document


def upload(
    db: Session,
    user: User,
    ctx: RagContext,
    *,
    filename: str,
    data: bytes,
    corpus_id: uuid.UUID | None,
    embedding: str | None,
    chunking: str | None,
) -> Document:
    """Store and index a file: private by default, or in a corpus (administrators only)."""
    if len(data) > ctx.settings.app.limits.max_upload_mb * 1024 * 1024:
        raise RagError(413, f"The file is larger than {ctx.settings.app.limits.max_upload_mb} MB.")
    if corpus_id is not None:
        if user.role != Role.ADMIN:
            raise RagError(403, "Administrator access is required.")
        if corpus_repo.get(db, corpus_id) is None:
            raise RagError(404, "Corpus not found.")
    spec = ctx.spec(embedding, chunking)
    embedder = ctx.embedder(spec)
    try:
        return ingestion.ingest_file(
            db,
            filename=filename.strip() or "document",
            data=data,
            owner_id=None if corpus_id else user.id,
            corpus_id=corpus_id,
            supported=ctx.settings.rag.supported_formats,
            spec=spec,
            embedder=embedder,
            store=ctx.store,
        )
    except ParseError as exc:
        raise RagError(422, str(exc)) from exc


def list_documents(db: Session, user: User, corpus_id: uuid.UUID | None) -> list[DocumentOut]:
    """Own uploads, or the documents of one corpus the user can read."""
    if corpus_id is None:
        condition = Document.owner_id == user.id
    else:
        is_admin = user.role == Role.ADMIN
        if corpus_repo.get(db, corpus_id) is None or not (
            is_admin or _can_read(db, user, corpus_id)
        ):
            raise RagError(404, "Corpus not found.")
        condition = Document.corpus_id == corpus_id
        if not is_admin:  # only administrators see files that failed to ingest
            condition = and_(condition, Document.status == DocumentStatus.READY)
    return _out(db, document_repo.list_where(db, condition))


def _can_read(db: Session, user: User, corpus_id: uuid.UUID) -> bool:
    return any(c.id == corpus_id for c in corpus_repo.list_where(db, accessible_corpus_ids(user)))


def reindex(
    db: Session,
    user: User,
    ctx: RagContext,
    document_id: uuid.UUID,
    embedding: str | None,
    chunking: str | None,
) -> Document:
    """Add (or refresh) an index made with another embedding model or splitter."""
    document = get(db, user, document_id, manage=True)
    if document.status != DocumentStatus.READY:
        raise RagError(409, "The document could not be read; upload it again.")
    spec = ctx.spec(embedding, chunking)
    ingestion.index_document(db, document, spec, ctx.embedder(spec), ctx.store)
    return document


def delete(db: Session, user: User, document_id: uuid.UUID) -> None:
    document_repo.delete(db, get(db, user, document_id, manage=True))


def chunks(db: Session, user: User, document_id: uuid.UUID, limit: int, offset: int) -> list[Chunk]:
    document = get(db, user, document_id)
    return document_repo.chunks_of(db, document.id, limit, offset)
