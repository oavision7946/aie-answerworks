"""Deterministic provider for tests, demos and E2E runs. No network, no key."""

import hashlib
import math
import re
from collections import deque
from collections.abc import Iterator

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

Step = str | Exception | Completion

DEFAULT_EMBEDDING_DIMENSIONS = 64


def embed_text(text: str, dimensions: int) -> list[float]:
    """Hashed bag of words, L2-normalised: texts that share words get a high cosine similarity."""
    vector = [0.0] * dimensions
    for word in re.findall(r"\w+", text.lower()):
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


class FakeProvider(Provider):
    """Echoes the last user message. Tests can script the next calls with `script(...)`.

    A scripted step is a string (the answer), a Completion, or an exception to raise. Streaming
    consumes the same script: a string is split on spaces, an exception is raised before any delta.
    """

    def __init__(self, name: str, config: ProviderConfig, request: RequestConfig) -> None:
        super().__init__(name, config, request)
        self._steps: deque[Step] = deque()
        self.calls: list[tuple[str, list[ChatMessage]]] = []
        self.embed_calls: list[tuple[str, list[str]]] = []

    def script(self, *steps: Step) -> "FakeProvider":
        self._steps.extend(steps)
        return self

    def _next(self, messages: list[ChatMessage]) -> Completion:
        step = self._steps.popleft() if self._steps else self._echo(messages)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, Completion):
            return step
        return Completion(text=step, usage=self._usage(messages, step))

    @staticmethod
    def _echo(messages: list[ChatMessage]) -> str:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return f"Echo: {last_user}"

    @staticmethod
    def _usage(messages: list[ChatMessage], answer: str) -> Usage:
        prompt_words = sum(len(m.content.split()) for m in messages)
        return Usage(input_tokens=prompt_words, output_tokens=len(answer.split()))

    def embed(
        self, model: str, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """Deterministic embeddings; the model name only labels them. Calls are recorded."""
        self.embed_calls.append((model, list(texts)))
        return [embed_text(text, dimensions or DEFAULT_EMBEDDING_DIMENSIONS) for text in texts]

    def complete(self, model: str, messages: list[ChatMessage]) -> Completion:
        self.calls.append((model, messages))
        return self._next(messages)

    def stream(self, model: str, messages: list[ChatMessage]) -> Iterator[StreamEvent]:
        self.calls.append((model, messages))
        completion = self._next(messages)
        words = completion.text.split(" ")
        for index, word in enumerate(words):
            yield TextDelta(word if index == len(words) - 1 else word + " ")
        yield StreamEnd(completion.usage)
