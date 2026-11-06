"""History-aware chat: build the prompt from stored messages, call the model, store the reply."""

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core import tracing
from app.db.models import Conversation, User
from app.db.repositories import conversation_repo
from app.schemas.ask import AskResponse
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.rag import Citation
from app.services import conversation_service
from app.services.conversation_service import ConversationNotFoundError
from app.services.llm import service
from app.services.llm.base import ChatMessage
from app.services.llm.errors import FAILED, LLMServiceError
from app.services.llm.registry import ProviderRegistry, ResolvedModel
from app.services.rag import retrieval_service, retriever
from app.services.rag.context import RagContext

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class Turn:
    """Everything needed to answer one message, gathered before the provider is called."""

    user_id: uuid.UUID
    conversation_id: uuid.UUID | None
    message: str
    prompt: list[ChatMessage]
    resolved: ResolvedModel
    started_at: datetime
    use_rag: bool = False
    corpus_ids: list[str] | None = None
    citations: list[Citation] = field(default_factory=list)


def _resolve(
    registry: ProviderRegistry, request: ChatRequest, conversation: Conversation | None
) -> ResolvedModel:
    if request.provider is None and request.model is None and conversation and conversation.model:
        try:
            return registry.resolve(conversation.provider, conversation.model)
        except LLMServiceError as exc:
            if exc.status_code != 422:
                raise
            logger.warning(
                "Conversation %s uses a model that is gone; using the default", conversation.id
            )
    return registry.resolve(request.provider, request.model)


def prepare(
    db: Session,
    user: User,
    request: ChatRequest,
    registry: ProviderRegistry,
    history_messages: int,
    rag: RagContext | None = None,
) -> Turn:
    """Validate ownership, pick the model, retrieve passages if asked and build the prompt.

    Raises before any provider call.
    """
    with tracing.span(
        "chat.prepare",
        **{"answerworks.user_id": str(user.id), "answerworks.use_rag": request.use_rag},
    ) as current:
        turn = _prepare(db, user, request, registry, history_messages, rag)
        current.set_attribute("answerworks.provider", turn.resolved.provider.name)
        current.set_attribute("answerworks.model", turn.resolved.model.id)
        current.set_attribute("answerworks.history_messages", len(turn.prompt) - 1)
        current.set_attribute("answerworks.citations", len(turn.citations))
        return turn


def _prepare(
    db: Session,
    user: User,
    request: ChatRequest,
    registry: ProviderRegistry,
    history_messages: int,
    rag: RagContext | None,
) -> Turn:
    started_at = datetime.now(UTC)
    conversation = None
    history: list[ChatMessage] = []
    if request.conversation_id is not None:
        conversation = conversation_service.get(db, user, request.conversation_id)
        stored = conversation_repo.recent_messages(db, conversation.id, history_messages)
        history = [ChatMessage(m.role.value, m.content) for m in stored]
    resolved = _resolve(registry, request, conversation)
    question = request.message
    citations: list[Citation] = []
    if request.use_rag and rag is not None:
        hits = retrieval_service.retrieve(
            db,
            user,
            rag,
            request.message,
            request.embedding,
            request.chunking,
            request.corpus_ids,
        )
        citations = [retrieval_service.citation(hit) for hit in hits]
        if hits:
            question = retriever.grounded_question(request.message, hits)
    return Turn(
        user_id=user.id,
        conversation_id=conversation.id if conversation else None,
        message=request.message,
        prompt=[*history, ChatMessage("user", question)],
        resolved=resolved,
        started_at=started_at,
        use_rag=request.use_rag,
        corpus_ids=[str(i) for i in request.corpus_ids] if request.corpus_ids else None,
        citations=citations,
    )


def _persist(db: Session, turn: Turn, answer: AskResponse) -> ChatResponse:
    with tracing.span("chat.persist", **{"answerworks.use_rag": turn.use_rag}) as current:
        stored = _store(db, turn, answer)
        current.set_attribute("answerworks.conversation_id", str(stored.conversation_id))
        return stored


def _store(db: Session, turn: Turn, answer: AskResponse) -> ChatResponse:
    if turn.conversation_id is None:
        conversation = conversation_repo.create(
            db, turn.user_id, conversation_service.title_from(turn.message), None, None
        )
    else:
        existing = conversation_repo.get_for_user(db, turn.user_id, turn.conversation_id)
        if existing is None:  # deleted while the answer was being generated
            raise ConversationNotFoundError(str(turn.conversation_id))
        conversation = existing
    reply = conversation_repo.add_exchange(
        db,
        conversation,
        turn.message,
        answer.answer,
        provider=answer.provider,
        model=answer.model,
        tokens_used=answer.tokens_used,
        latency_ms=answer.latency_ms,
        cost_usd=answer.cost_usd,
        started_at=turn.started_at,
        retrieved_chunk_ids=[str(c.chunk_id) for c in turn.citations],
        use_rag=turn.use_rag,
        corpus_ids=turn.corpus_ids,
    )
    return ChatResponse(
        conversation_id=conversation.id,
        message_id=reply.id,
        citations=turn.citations,
        **answer.model_dump(),
    )


def reply(db: Session, turn: Turn) -> ChatResponse:
    answer = service.complete_answer(turn.prompt, turn.resolved)
    return _persist(db, turn, answer)


def stream_reply(session_factory: SessionFactory, turn: Turn) -> Iterator[str]:
    """Server-sent events: `delta` per chunk, then `done` with the stored ids (or `error`).

    The request's own session may be closed by the time streaming ends, so the reply is saved
    with a fresh one.
    """
    for event_type, data in service.stream_events(turn.prompt, turn.resolved):
        if event_type != "done":
            yield service.sse_event(event_type, data)
            continue
        try:
            with session_factory() as db:
                stored = _persist(db, turn, AskResponse(**data))
        except ConversationNotFoundError:
            yield service.sse_event("error", {"detail": "Conversation not found."})
        except Exception:
            logger.exception("Could not store the streamed reply")
            yield service.sse_event("error", {"detail": FAILED})
        else:
            yield service.sse_event("done", stored.model_dump(mode="json"))
