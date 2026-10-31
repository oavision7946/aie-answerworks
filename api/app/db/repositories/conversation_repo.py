"""Conversation and message queries. Every lookup is scoped by the owning user."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, MessageRole


def create(
    db: Session, user_id: uuid.UUID, title: str, provider: str | None, model: str | None
) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title, provider=provider, model=model)
    db.add(conversation)
    db.commit()
    return conversation


def get_for_user(
    db: Session, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    return db.scalar(query)


def list_for_user(
    db: Session, user_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[Conversation]:
    query = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query))


def save(db: Session, conversation: Conversation) -> Conversation:
    db.add(conversation)
    db.commit()
    return conversation


def delete(db: Session, conversation: Conversation) -> None:
    db.delete(conversation)
    db.commit()


def recent_messages(db: Session, conversation_id: uuid.UUID, limit: int) -> list[Message]:
    """The last `limit` messages, oldest first."""
    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.role)
        .limit(limit)
    )
    return list(reversed(list(db.scalars(query))))


def add_exchange(
    db: Session,
    conversation: Conversation,
    question: str,
    answer: str,
    *,
    provider: str,
    model: str,
    tokens_used: int,
    latency_ms: int,
    cost_usd: float | None,
    started_at: datetime,
    retrieved_chunk_ids: list[str] | None = None,
    use_rag: bool = False,
    corpus_ids: list[str] | None = None,
) -> Message:
    """Store a user message and the assistant reply together, so a failed call leaves no trace."""
    answered_at = max(datetime.now(UTC), started_at + timedelta(microseconds=1))
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=question,
            created_at=started_at,
        )
    )
    reply = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=answer,
        provider=provider,
        model=model,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        retrieved_chunk_ids=retrieved_chunk_ids or [],
        created_at=answered_at,
    )
    db.add(reply)
    conversation.provider = provider
    conversation.model = model
    conversation.use_rag = use_rag
    conversation.corpus_ids = corpus_ids or []
    conversation.updated_at = answered_at
    db.add(conversation)
    db.commit()
    return reply
