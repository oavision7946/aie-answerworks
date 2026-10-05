"""Provider interface and the value types that cross it."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from app.core.settings import ModelConfig, ProviderConfig, RequestConfig


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Usage:
    """input_tokens is the total prompt size and includes cached_input_tokens."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage


@dataclass(frozen=True)
class TextDelta:
    content: str


@dataclass(frozen=True)
class StreamEnd:
    usage: Usage | None


StreamEvent = TextDelta | StreamEnd


class Provider(ABC):
    """One LLM backend. Adapters translate SDK errors into the exceptions in errors.py."""

    def __init__(self, name: str, config: ProviderConfig, request: RequestConfig) -> None:
        self.name = name
        self.config = config
        self.request = request

    @property
    def default_model(self) -> ModelConfig:
        return self.model(self.config.default_model)

    def list_models(self) -> list[ModelConfig]:
        return list(self.config.models)

    def model(self, model_id: str) -> ModelConfig:
        for model in self.config.models:
            if model.id == model_id:
                return model
        raise KeyError(model_id)

    @abstractmethod
    def complete(self, model: str, messages: list[ChatMessage]) -> Completion:
        """Return the full answer. Raise ProviderError subclasses on failure."""

    @abstractmethod
    def stream(self, model: str, messages: list[ChatMessage]) -> Iterator[StreamEvent]:
        """Yield TextDelta items, then one StreamEnd (usage is None if the backend gave none)."""
