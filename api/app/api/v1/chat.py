from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.permissions import active_user
from app.core.settings import Settings, get_settings
from app.db.models import User
from app.db.session import get_engine, get_session
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service
from app.services.conversation_service import ConversationNotFoundError
from app.services.llm.errors import LLMServiceError
from app.services.llm.registry import ProviderRegistry, get_registry

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    db: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(active_user)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ChatResponse | StreamingResponse:
    """Send a message. Without `conversation_id` a new conversation is started.

    With `stream: true` the response is server-sent events (`delta`, then `done` or `error`).
    The exchange is stored only after the model answers successfully.
    """
    try:
        turn = chat_service.prepare(db, user, request, registry, settings.app.chat.history_messages)
        if request.stream:
            return StreamingResponse(
                chat_service.stream_reply(lambda: Session(engine, expire_on_commit=False), turn),
                media_type="text/event-stream",
            )
        return chat_service.reply(db, turn)
    except ConversationNotFoundError:
        raise HTTPException(404, "Conversation not found.") from None
    except LLMServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
