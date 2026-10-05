"""Anthropic Messages API."""

from collections.abc import Iterator
from typing import Any

import anthropic

from app.core.settings import ProviderConfig, RequestConfig
from app.services.llm.base import (
    ChatMessage,
    Completion,
    Provider,
    StreamEnd,
    StreamEvent,
    TextDelta,
    Usage,
)
from app.services.llm.errors import ProviderError, TransientProviderError


def translate_error(exc: Exception) -> ProviderError:
    if isinstance(
        exc,
        (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError),
    ):
        return TransientProviderError(type(exc).__name__)
    if isinstance(exc, anthropic.APIStatusError):
        # 529 is Anthropic's "overloaded" status; it is covered by >= 500.
        if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
            return TransientProviderError(f"{type(exc).__name__} {exc.status_code}")
        return ProviderError(f"{type(exc).__name__} {exc.status_code}")
    return ProviderError(f"{type(exc).__name__}: {exc}")


def usage_from(usage: Any) -> Usage:
    """Anthropic reports cache reads/writes separately from input_tokens; fold them in."""
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return Usage(
        input_tokens=(getattr(usage, "input_tokens", 0) or 0) + cache_read + cache_write,
        cached_input_tokens=cache_read,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )


class AnthropicProvider(Provider):
    def __init__(
        self,
        name: str,
        config: ProviderConfig,
        request: RequestConfig,
        api_key: str,
        http_client: Any = None,
    ) -> None:
        super().__init__(name, config, request)
        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=request.timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    def _kwargs(self, model: str, messages: list[ChatMessage]) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self.request.max_output_tokens,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages if m.role != "system"
            ],
        }
        if system:
            kwargs["system"] = system
        return kwargs

    def complete(self, model: str, messages: list[ChatMessage]) -> Completion:
        try:
            response = self.client.messages.create(**self._kwargs(model, messages))
        except anthropic.AnthropicError as exc:
            raise translate_error(exc) from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        return Completion(text=text, usage=usage_from(response.usage))

    def stream(self, model: str, messages: list[ChatMessage]) -> Iterator[StreamEvent]:
        try:
            with self.client.messages.stream(**self._kwargs(model, messages)) as stream:
                for text in stream.text_stream:
                    yield TextDelta(text)
                final = stream.get_final_message()
        except anthropic.AnthropicError as exc:
            raise translate_error(exc) from exc
        yield StreamEnd(usage_from(final.usage))
