"""Server-sent-events variant of /ask."""

import json
import logging
import time
from collections.abc import Iterator

from pydantic import ValidationError

from app.schemas.ask import AskRequest, AskResponse, ModelOutput
from app.services.llm import openai_service
from app.services.llm.costs import compute_cost_usd

logger = logging.getLogger(__name__)


def sse_event(event_type: str, data: dict[str, object]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def stream_answer(request: AskRequest) -> Iterator[str]:
    started_at = time.perf_counter()
    force_bad_first_response = request.force_bad_first_response or request.force_bad
    max_attempts = openai_service.settings.max_attempts

    stream_client = openai_service.client
    if stream_client is None:
        logger.error("Streaming requested without a configured OpenAI client")
        yield sse_event("error", {"detail": openai_service.NOT_CONFIGURED})
        return

    for attempt in range(max_attempts):
        answer_parts: list[str] = []
        try:
            response = stream_client.chat.completions.create(
                model=request.model,
                messages=[{"role": "user", "content": request.question}],
                stream=True,
                stream_options={"include_usage": True},
                timeout=openai_service.settings.timeout_seconds,
            )
            usage = None
            for chunk in response:
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None)
                if isinstance(content, str):
                    answer_parts.append(content)
                    if not (force_bad_first_response and attempt == 0):
                        yield sse_event("delta", {"content": content})

            if force_bad_first_response and attempt == 0:
                logger.warning(
                    "OpenAI streaming response was deliberately rejected by the test control"
                )
                yield sse_event("error", {"detail": openai_service.UNUSABLE})
                return

            try:
                model_output = ModelOutput(answer="".join(answer_parts))
            except ValidationError:
                logger.warning(
                    "OpenAI streaming response failed output validation on attempt %d", attempt + 1
                )
                if attempt + 1 < max_attempts:
                    continue
                yield sse_event("error", {"detail": openai_service.UNUSABLE})
                return

            if usage is None:
                logger.error("OpenAI streaming response contained no usage metadata")
                yield sse_event("error", {"detail": openai_service.INCOMPLETE})
                return

            input_tokens, cached_input_tokens, output_tokens, total_tokens = (
                openai_service.usage_counts(usage)
            )
            completion = AskResponse(
                answer=model_output.answer,
                model=request.model,
                tokens_used=total_tokens,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                cost_usd=compute_cost_usd(
                    request.model, input_tokens, cached_input_tokens, output_tokens
                ),
            )
            yield sse_event("done", completion.model_dump())
            return
        except Exception as exc:
            transient = openai_service.is_transient_openai_error(exc)
            if transient and not answer_parts and attempt + 1 < max_attempts:
                delay = openai_service.retry_delay(attempt)
                logger.warning(
                    "Transient OpenAI streaming failure (%s), attempt %d/%d; "
                    "retrying in %.1f seconds",
                    type(exc).__name__,
                    attempt + 1,
                    max_attempts,
                    delay,
                )
                time.sleep(delay)
                continue
            logger.exception("OpenAI streaming request failed on attempt %d", attempt + 1)
            detail = openai_service.UNAVAILABLE if transient else openai_service.FAILED
            yield sse_event("error", {"detail": detail})
            return
