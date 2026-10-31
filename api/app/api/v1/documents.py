import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.permissions import active_user
from app.db.models import Chunk, User
from app.db.session import get_session
from app.schemas.rag import ChunkOut, DocumentOut, IndexRequest
from app.services.rag import document_service
from app.services.rag.context import RagContext, get_rag_context
from app.services.rag.errors import RagError

router = APIRouter(prefix="/documents", tags=["documents"])
Db = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(active_user)]
Context = Annotated[RagContext, Depends(get_rag_context)]


def http_error(exc: RagError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    db: Db,
    user: CurrentUser,
    ctx: Context,
    file: Annotated[UploadFile, File(description="A PDF, TXT or Markdown file")],
    embedding: Annotated[str | None, Form(description="Embedding model name (rag.yaml)")] = None,
    chunking: Annotated[str | None, Form(description="Chunking strategy name (rag.yaml)")] = None,
    corpus_id: Annotated[
        uuid.UUID | None, Form(description="Add to a shared corpus (administrators only)")
    ] = None,
) -> DocumentOut:
    """Upload and index a document. It is private to you unless `corpus_id` is given."""
    try:
        # Read one byte past the limit so an oversized file is rejected without loading all of it.
        limit = ctx.settings.app.limits.max_upload_mb * 1024 * 1024
        data = file.file.read(limit + 1)
        document = document_service.upload(
            db,
            user,
            ctx,
            filename=file.filename or "document",
            data=data,
            corpus_id=corpus_id,
            embedding=embedding,
            chunking=chunking,
        )
        return document_service.describe(db, document)
    except RagError as exc:
        raise http_error(exc) from exc


@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Db,
    user: CurrentUser,
    corpus_id: Annotated[
        uuid.UUID | None, Query(description="List a shared corpus instead of your uploads")
    ] = None,
) -> list[DocumentOut]:
    try:
        return document_service.list_documents(db, user, corpus_id)
    except RagError as exc:
        raise http_error(exc) from exc


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, db: Db, user: CurrentUser) -> DocumentOut:
    try:
        return document_service.describe(db, document_service.get(db, user, document_id))
    except RagError as exc:
        raise http_error(exc) from exc


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def list_chunks(
    document_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Chunk]:
    """The stored chunks with the embedding model and splitter recorded on each."""
    try:
        return document_service.chunks(db, user, document_id, limit, offset)
    except RagError as exc:
        raise http_error(exc) from exc


@router.post("/{document_id}/index", response_model=DocumentOut)
def index_document(
    document_id: uuid.UUID, body: IndexRequest, db: Db, user: CurrentUser, ctx: Context
) -> DocumentOut:
    """Index the document again with another embedding model or splitter. Existing indexes stay."""
    try:
        document = document_service.reindex(
            db, user, ctx, document_id, body.embedding, body.chunking
        )
        return document_service.describe(db, document)
    except RagError as exc:
        raise http_error(exc) from exc


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, db: Db, user: CurrentUser) -> None:
    try:
        document_service.delete(db, user, document_id)
    except RagError as exc:
        raise http_error(exc) from exc
