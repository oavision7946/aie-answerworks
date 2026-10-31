import uuid
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
)

from app.db.models import MessageRole


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: StrictStr = Field(min_length=1, max_length=20000)
    # Omitted: start a new conversation, titled from this message.
    conversation_id: uuid.UUID | None = None
    # Both optional: omitted -> the conversation's last model, or the registry default.
    provider: StrictStr | None = None
    model: StrictStr | None = None
    stream: StrictBool = False

    @field_validator("message", mode="before")
    @classmethod
    def message_must_not_be_blank(cls, value: Any) -> Any:
        value = _strip(value)
        if value == "":
            raise ValueError("message must not be blank")
        return value


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    provider: str
    model: str
    tokens_used: int
    latency_ms: int
    cost_usd: float | None  # null when the model has no pricing configured


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    provider: StrictStr | None = None
    model: StrictStr | None = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: Any) -> Any:
        return _strip(value)


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr = Field(min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: Any) -> Any:
        return _strip(value)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    provider: str | None
    model: str | None
    tokens_used: int | None
    latency_ms: int | None
    cost_usd: float | None
    retrieved_chunk_ids: list[str]
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    provider: str | None
    model: str | None
    use_rag: bool
    corpus_ids: list[str]
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
