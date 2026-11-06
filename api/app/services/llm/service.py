"""Chat flow on top of any Provider: retry, output validation, usage and cost reporting."""

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from opentelemetry.trace import Span, Status, StatusCode
from pydantic import ValidationError

from app.core import tracing
from app.core.telemetry import telemetry
from app.schemas.ask import AskRequest, AskResponse, ModelOutput
from app.services.llm.base import ChatMessage, Completion, StreamEnd, TextDelta, Usage
from app.services.llm.costs import compute_cost_usd
from app.services.llm.errors import (
    FAILED,
    INCOMPLETE,
    UNAVAILABLE,
    UNUSABLE,
    IncompleteResponseError,
    LLMServiceError,
    TransientProviderError,
)
from app.services.llm.registry import ResolvedModel
from app.services.llm.retry import call_with_retry, log_retry

logger = logging.getLogger(__name__)


def _record_usage(current: Span, usage: Usage, provider: str, model: str) -> None:
    current.set_attribute("answerworks.tokens.input", usage.input_tokens)
    current.set_attribute("answerworks.tokens.output", usage.output_tokens)
    telemetry.tokens_used(provider, model, usage.input_tokens, usage.output_tokens)


def _complete(resolved: ResolvedModel, messages: list[ChatMessage]) -> Completion:
    provider = resolved.provider
    started = time.perf_counter()
    try:
        with tracing.span(
            "llm.complete",
            **{"answerworks.provider": provider.name, "answerworks.model": resolved.model.id},
        ) as current:
            completion = call_with_retry(
                lambda: provider.complete(resolved.model.id, messages),
                resolved.request,
                logger,
                f"{provider.name} completion",
            )
            _record_usage(current, completion.usage, provider.name, resolved.model.id)
        telemetry.provider_call(provider.name, "complete", True, time.perf_counter() - started)
        return completion
    except TransientProviderError as exc:
        telemetry.provider_call(provider.name, "complete", False, time.perf_counter() - started)
        raise LLMServiceError(503, UNAVAILABLE) from exc
    except IncompleteResponseError as exc:
        telemetry.provider_call(provider.name, "complete", False, time.perf_counter() - started)
        logger.error("%s returned an incomplete response: %s", provider.name, exc)
        raise LLMServiceError(502, INCOMPLETE) from exc
    except Exception as exc:  # ProviderError or anything unexpected: never leak details
        telemetry.provider_call(provider.name, "complete", False, time.perf_counter() - started)
        raise LLMServiceError(502, FAILED) from exc


def answer_question(request: AskRequest, resolved: ResolvedModel) -> AskResponse:
    """Ask the model one standalone question."""
    return complete_answer(
        [ChatMessage("user", request.question)],
        resolved,
        force_bad_first_response=request.force_bad_first_response or request.force_bad,
    )


def complete_answer(
    messages: list[ChatMessage], resolved: ResolvedModel, force_bad_first_response: bool = False
) -> AskResponse:
    """Ask the model, validating its output and retrying once on an invalid answer."""
    tokens_used = 0
    cost_usd: float | None = 0.0
    model_output = None
    started_at = time.perf_counter()

    for attempt in range(2):
        completion = _complete(resolved, messages)
        tokens_used += completion.usage.total_tokens
        cost = compute_cost_usd(resolved.model.pricing, completion.usage)
        cost_usd = None if cost is None else (cost_usd or 0.0) + cost

        text = "" if force_bad_first_response and attempt == 0 else completion.text
        try:
            model_output = ModelOutput(answer=text)
            break
        except ValidationError:
            logger.warning("Model response failed output validation on attempt %d/2", attempt + 1)
            if force_bad_first_response or attempt == 1:
                raise LLMServiceError(502, UNUSABLE) from None

    if model_output is None:  # pragma: no cover
        raise LLMServiceError(502, UNUSABLE)

    return AskResponse(
        answer=model_output.answer,
        provider=resolved.provider.name,
        model=resolved.model.id,
        tokens_used=tokens_used,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        cost_usd=cost_usd,
    )


def sse_event(event_type: str, data: dict[str, object]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def stream_answer(request: AskRequest, resolved: ResolvedModel) -> Iterator[str]:
    """Server-sent events: `delta` per chunk, then `done` (or `error`)."""
    events = stream_events(
        [ChatMessage("user", request.question)],
        resolved,
        force_bad_first_response=request.force_bad_first_response or request.force_bad,
    )
    for event_type, data in events:
        yield sse_event(event_type, data)


def stream_events(
    messages: list[ChatMessage], resolved: ResolvedModel, force_bad_first_response: bool = False
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (event, data) pairs: `delta` per chunk, then one `done` (an AskResponse) or `error`."""
    started_at = time.perf_counter()
    provider = resolved.provider
    max_attempts = resolved.request.max_attempts

    for attempt in range(max_attempts):
        answer_parts: list[str] = []
        usage: Usage | None = None
        attempt_started = time.perf_counter()
        current = tracing.tracer().start_span(
            "llm.stream",
            attributes={
                "answerworks.provider": provider.name,
                "answerworks.model": resolved.model.id,
                "answerworks.attempt": attempt + 1,
            },
        )
        try:
            stream = tracing.iterate_in_span(
                current, iter(provider.stream(resolved.model.id, messages))
            )
            for event in stream:
                if isinstance(event, TextDelta):
                    if not answer_parts:
                        first_token = time.perf_counter() - attempt_started
                        current.set_attribute(
                            "answerworks.time_to_first_token_ms", int(first_token * 1000)
                        )
                        telemetry.observe(
                            "time_to_first_token_seconds",
                            first_token,
                            provider=provider.name,
                            model=resolved.model.id,
                        )
                    answer_parts.append(event.content)
                    if not (force_bad_first_response and attempt == 0):
                        yield "delta", {"content": event.content}
                elif isinstance(event, StreamEnd):
                    usage = event.usage
                    if usage is not None:
                        _record_usage(current, usage, provider.name, resolved.model.id)
            current.set_attribute("answerworks.chunks", len(answer_parts))

            if force_bad_first_response and attempt == 0:
                logger.warning("Streaming response was deliberately rejected by the test control")
                yield "error", {"detail": UNUSABLE}
                return

            try:
                model_output = ModelOutput(answer="".join(answer_parts))
            except ValidationError:
                logger.warning(
                    "Streaming response failed output validation on attempt %d", attempt + 1
                )
                if attempt + 1 < max_attempts:
                    continue
                yield "error", {"detail": UNUSABLE}
                return

            if usage is None:
                logger.error(
                    "Streaming response from %s contained no usage metadata", provider.name
                )
                yield "error", {"detail": INCOMPLETE}
                return

            completion = AskResponse(
                answer=model_output.answer,
                provider=provider.name,
                model=resolved.model.id,
                tokens_used=usage.total_tokens,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                cost_usd=compute_cost_usd(resolved.model.pricing, usage),
            )
            telemetry.provider_call(provider.name, "stream", True, time.perf_counter() - started_at)
            current.end()  # the model call is over; what the caller does next is not part of it
            yield "done", completion.model_dump()
            return
        except Exception as exc:
            current.set_attribute("error.type", type(exc).__name__)
            current.set_status(Status(StatusCode.ERROR))
            telemetry.provider_call(
                provider.name, "stream", False, time.perf_counter() - started_at
            )
            transient = isinstance(exc, TransientProviderError)
            if transient and not answer_parts and attempt + 1 < max_attempts:
                time.sleep(
                    log_retry(logger, f"{provider.name} streaming", exc, attempt, resolved.request)
                )
                continue
            logger.exception(
                "Streaming request to %s failed on attempt %d", provider.name, attempt + 1
            )
            yield "error", {"detail": UNAVAILABLE if transient else FAILED}
            return
        finally:
            if current.is_recording():
                current.end()
