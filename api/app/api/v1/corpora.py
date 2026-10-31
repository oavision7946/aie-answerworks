import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import active_user, admin_user
from app.db.models import User
from app.db.session import get_session
from app.schemas.rag import (
    AccessGrant,
    CorpusCreate,
    CorpusOut,
    CorpusUpdate,
    IndexRequest,
    IngestResult,
)
from app.schemas.user import UserOut
from app.services.rag import corpus_service
from app.services.rag.context import RagContext, get_rag_context
from app.services.rag.errors import RagError

router = APIRouter(prefix="/corpora", tags=["corpora"])
Db = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(active_user)]
Admin = Annotated[User, Depends(admin_user)]
Context = Annotated[RagContext, Depends(get_rag_context)]


def http_error(exc: RagError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


@router.get("", response_model=list[CorpusOut])
def list_corpora(db: Db, user: CurrentUser) -> list[CorpusOut]:
    """Corpora you can read: public ones and the ones granted to you (administrators see all)."""
    return corpus_service.list_for(db, user)


@router.post("", response_model=CorpusOut, status_code=201)
def create_corpus(body: CorpusCreate, db: Db, admin: Admin) -> CorpusOut:
    try:
        return corpus_service.describe(db, corpus_service.create(db, admin, body))
    except RagError as exc:
        raise http_error(exc) from exc


@router.patch("/{corpus_id}", response_model=CorpusOut)
def update_corpus(corpus_id: uuid.UUID, body: CorpusUpdate, db: Db, admin: Admin) -> CorpusOut:
    """Change the description or the public flag."""
    try:
        return corpus_service.describe(db, corpus_service.update(db, corpus_id, body))
    except RagError as exc:
        raise http_error(exc) from exc


@router.delete("/{corpus_id}", status_code=204)
def delete_corpus(corpus_id: uuid.UUID, db: Db, admin: Admin) -> None:
    """Delete the corpus with its documents and chunks."""
    try:
        corpus_service.delete(db, corpus_id)
    except RagError as exc:
        raise http_error(exc) from exc


@router.get("/{corpus_id}/access", response_model=list[UserOut])
def list_access(corpus_id: uuid.UUID, db: Db, admin: Admin) -> list[User]:
    """Users who have been granted this corpus (the public flag is separate)."""
    try:
        return corpus_service.granted_users(db, corpus_id)
    except RagError as exc:
        raise http_error(exc) from exc


@router.post("/{corpus_id}/access", status_code=204)
def grant_access(corpus_id: uuid.UUID, body: AccessGrant, db: Db, admin: Admin) -> None:
    try:
        corpus_service.grant(db, corpus_id, body.user_id)
    except RagError as exc:
        raise http_error(exc) from exc


@router.delete("/{corpus_id}/access/{user_id}", status_code=204)
def revoke_access(corpus_id: uuid.UUID, user_id: uuid.UUID, db: Db, admin: Admin) -> None:
    """Takes effect immediately: the user's next retrieval no longer includes this corpus."""
    try:
        corpus_service.revoke(db, corpus_id, user_id)
    except RagError as exc:
        raise http_error(exc) from exc


@router.post("/{corpus_id}/ingest", response_model=IngestResult)
def ingest_corpus(
    corpus_id: uuid.UUID, body: IndexRequest, db: Db, admin: Admin, ctx: Context
) -> IngestResult:
    """Read the corpus' source and index every file with the chosen model and splitter."""
    try:
        return corpus_service.ingest(db, ctx, corpus_id, body.embedding, body.chunking)
    except RagError as exc:
        raise http_error(exc) from exc
