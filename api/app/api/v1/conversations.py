import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.permissions import active_user
from app.db.models import Conversation, User
from app.db.repositories import conversation_repo
from app.db.session import get_session
from app.schemas.chat import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
)
from app.services import conversation_service
from app.services.conversation_service import ConversationNotFoundError
from app.services.llm.errors import LLMServiceError
from app.services.llm.registry import ProviderRegistry, get_registry

router = APIRouter(prefix="/conversations", tags=["conversations"])
Db = Annotated[Session, Depends(get_session)]
Me = Annotated[User, Depends(active_user)]
Registry = Annotated[ProviderRegistry, Depends(get_registry)]
NOT_FOUND = HTTPException(status_code=404, detail="Conversation not found.")


@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(
    body: ConversationCreate, db: Db, user: Me, registry: Registry
) -> Conversation:
    try:
        return conversation_service.create(db, user, body, registry)
    except LLMServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    db: Db,
    user: Me,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Conversation]:
    """Your conversations, most recently active first."""
    return conversation_repo.list_for_user(db, user.id, limit, offset)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, db: Db, user: Me) -> Conversation:
    try:
        return conversation_service.get(db, user, conversation_id)
    except ConversationNotFoundError:
        raise NOT_FOUND from None


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, db: Db, user: Me
) -> Conversation:
    try:
        return conversation_service.rename(db, user, conversation_id, body)
    except ConversationNotFoundError:
        raise NOT_FOUND from None


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, db: Db, user: Me) -> None:
    try:
        conversation_service.delete(db, user, conversation_id)
    except ConversationNotFoundError:
        raise NOT_FOUND from None
