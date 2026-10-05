"""OpenAI chat completions, and any OpenAI-compatible server (Ollama, vLLM, ...)."""

from collections.abc import Iterator
from typing import Any, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam

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
from app.services.llm.errors import IncompleteResponseError, ProviderError, TransientProviderError


def translate_error(exc: Exception) -> ProviderError:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return TransientProviderError(type(exc).__name__)
    if isinstance(exc, APIStatusError):
        if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
            return TransientProviderError(f"{type(exc).__name__} {exc.status_code}")
        return ProviderError(f"{type(exc).__name__} {exc.status_code}")
    return ProviderError(f"{type(exc).__name__}: {exc}")


def usage_from(usage: Any) -> Usage:
    details = getattr(usage, "prompt_tokens_details", None)
    return Usage(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        cached_input_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


class OpenAIProvider(Provider):
    # Hosted OpenAI always reports usage; local servers may not (see LocalProvider).
    requires_usage = True

    def __init__(
        self,
        name: str,
        config: ProviderConfig,
        request: RequestConfig,
        api_key: str,
        base_url: str | None = None,
        http_client: Any = None,
    ) -> None:
        super().__init__(name, config, request)
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=request.timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    @staticmethod
    def _payload(messages: list[ChatMessage]) -> list[ChatCompletionMessageParam]:
        return cast(
            list[ChatCompletionMessageParam],
            [{"role": m.role, "content": m.content} for m in messages],
        )

    def _usage(self, usage: Any) -> Usage:
        if usage is not None:
            return usage_from(usage)
        if self.requires_usage:
            raise IncompleteResponseError("response had no usage metadata")
        return Usage()

    def complete(self, model: str, messages: list[ChatMessage]) -> Completion:
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=self._payload(messages),
                timeout=self.request.timeout_seconds,
            )
        except OpenAIError as exc:
            raise translate_error(exc) from exc
        if not getattr(response, "choices", None):
            raise IncompleteResponseError("response had no choices")
        content = getattr(response.choices[0].message, "content", None)
        if content is None:
            raise IncompleteResponseError("response had no message content")
        return Completion(text=content, usage=self._usage(getattr(response, "usage", None)))

    def stream(self, model: str, messages: list[ChatMessage]) -> Iterator[StreamEvent]:
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=self._payload(messages),
                stream=True,
                stream_options={"include_usage": True},
                timeout=self.request.timeout_seconds,
            )
            usage = None
            for chunk in response:
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                content = getattr(choices[0].delta, "content", None)
                if isinstance(content, str):
                    yield TextDelta(content)
        except OpenAIError as exc:
            raise translate_error(exc) from exc
        if usage is not None:
            yield StreamEnd(usage_from(usage))
        else:
            yield StreamEnd(None if self.requires_usage else Usage())


class LocalProvider(OpenAIProvider):
    """An OpenAI-compatible server. The API key is optional and usage may be missing."""

    requires_usage = False

    def __init__(
        self,
        name: str,
        config: ProviderConfig,
        request: RequestConfig,
        api_key: str | None,
        http_client: Any = None,
    ) -> None:
        # The SDK refuses an empty key; most local servers ignore the value.
        super().__init__(
            name, config, request, api_key or "not-needed", config.base_url, http_client
        )
