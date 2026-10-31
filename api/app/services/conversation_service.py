"""Conversation management for the signed-in user. Other users' conversations do not exist here."""

import uuid

from sqlalchemy.orm import Session

from app.db.models import Conversation, User
from app.db.repositories import conversation_repo
from app.schemas.chat import ConversationCreate, ConversationUpdate
from app.services.llm.registry import ProviderRegistry

DEFAULT_TITLE = "New conversation"
TITLE_LENGTH = 60


class ConversationNotFoundError(Exception):
    """Missing, or owned by someone else (deliberately indistinguishable)."""


def title_from(message: str) -> str:
    text = " ".join(message.split())
    return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"


def get(db: Session, user: User, conversation_id: uuid.UUID) -> Conversation:
    conversation = conversation_repo.get_for_user(db, user.id, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(str(conversation_id))
    return conversation


def create(
    db: Session, user: User, body: ConversationCreate, registry: ProviderRegistry
) -> Conversation:
    provider = model = None
    if body.provider or body.model:
        # Raises LLMServiceError(422) for an unknown choice.
        resolved = registry.resolve(body.provider, body.model)
        provider, model = resolved.provider.name, resolved.model.id
    return conversation_repo.create(db, user.id, body.title or DEFAULT_TITLE, provider, model)


def rename(
    db: Session, user: User, conversation_id: uuid.UUID, body: ConversationUpdate
) -> Conversation:
    conversation = get(db, user, conversation_id)
    conversation.title = body.title
    return conversation_repo.save(db, conversation)


def delete(db: Session, user: User, conversation_id: uuid.UUID) -> None:
    conversation_repo.delete(db, get(db, user, conversation_id))
