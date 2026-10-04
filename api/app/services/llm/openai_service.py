"""OpenAI chat completions: client, retry with backoff, and the non-streaming /ask flow."""

import logging
import os
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from pydantic import ValidationError

from app.core.config import get_llm_settings, load_env
from app.schemas.ask import AskRequest, AskResponse, ModelOutput
from app.services.llm.costs import compute_cost_usd

logger = logging.getLogger(__name__)
settings = get_llm_settings()

NOT_CONFIGURED = "The AI service is not configured. Please contact support."
UNAVAILABLE = "The AI service is temporarily unavailable. Please try again shortly."
FAILED = "The AI service could not complete your request. Please try again."
INCOMPLETE = "The AI service returned an incomplete response. Please try again."
UNUSABLE = "The AI service returned an unusable response. Please try again."

load_env()
api_key = os.getenv("OPENAI_API_KEY")
client = (
    OpenAI(api_key=api_key, timeout=settings.timeout_seconds, max_retries=0) if api_key else None
)


class LLMServiceError(Exception):
    """A failure with a user-safe message and the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def is_transient_openai_error(error: Exception) -> bool:
    if isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    return isinstance(error, APIStatusError) and (
        error.status_code in (408, 409, 429) or error.status_code >= 500
    )


def retry_delay(attempt: int) -> float:
    return float(settings.retry_base_delay_seconds * (2**attempt))


def usage_counts(usage: Any) -> tuple[int, int, int, int]:
    """Return (input, cached_input, output, total) token counts from an OpenAI usage object."""
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    cached_input_tokens = 0
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    if prompt_details is not None:
        cached_input_tokens = getattr(prompt_details, "cached_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", input_tokens + output_tokens)
    return input_tokens, cached_input_tokens, output_tokens, total_tokens


def create_chat_completion(**kwargs: Any) -> Any:
    openai_client = client
    if openai_client is None:
        raise RuntimeError("OpenAI client is not configured")

    max_attempts = settings.max_attempts
    for attempt in range(max_attempts):
        try:
            return openai_client.chat.completions.create(
                timeout=settings.timeout_seconds,
                **kwargs,
            )
        except Exception as exc:
            if not is_transient_openai_error(exc):
                logger.exception("OpenAI request failed with a non-retryable error")
                raise
            if attempt + 1 == max_attempts:
                logger.exception("OpenAI request failed after %d attempts", max_attempts)
                raise
            delay = retry_delay(attempt)
            logger.warning(
                "Transient OpenAI failure (%s), attempt %d/%d; retrying in %.1f seconds",
                type(exc).__name__,
                attempt + 1,
                max_attempts,
                delay,
            )
            time.sleep(delay)
    logger.error("OpenAI request exited the retry loop without a response")  # pragma: no cover
    raise RuntimeError("OpenAI request could not be completed")  # pragma: no cover


def answer_question(request: AskRequest) -> AskResponse:
    """Ask the model, validating its output and retrying once on an invalid answer."""
    tokens_used = 0
    cost_usd = 0.0
    model_output = None
    force_bad_first_response = request.force_bad_first_response or request.force_bad
    started_at = time.perf_counter()

    for attempt in range(2):
        try:
            response = create_chat_completion(
                model=request.model,
                messages=[{"role": "user", "content": request.question}],
            )
        except Exception as exc:
            if is_transient_openai_error(exc):
                raise LLMServiceError(503, UNAVAILABLE) from exc
            raise LLMServiceError(502, FAILED) from exc

        if not getattr(response, "choices", None):
            logger.error("OpenAI returned no choices on attempt %d", attempt + 1)
            raise LLMServiceError(502, INCOMPLETE)

        message = getattr(response.choices[0], "message", None)
        content = getattr(message, "content", None)
        if content is None:
            logger.error("OpenAI returned empty message content on attempt %d", attempt + 1)
            raise LLMServiceError(502, INCOMPLETE)

        usage = getattr(response, "usage", None)
        if usage is None:
            logger.error("OpenAI returned no usage metadata on attempt %d", attempt + 1)
            raise LLMServiceError(502, INCOMPLETE)

        input_tokens, cached_input_tokens, output_tokens, total_tokens = usage_counts(usage)
        tokens_used += total_tokens

        try:
            cost_usd += compute_cost_usd(
                request.model, input_tokens, cached_input_tokens, output_tokens
            )
            if force_bad_first_response and attempt == 0:
                content = ""
            model_output = ModelOutput(answer=content)
            break
        except ValidationError:
            logger.warning("OpenAI response failed output validation on attempt %d/2", attempt + 1)
            if force_bad_first_response or attempt == 1:
                raise LLMServiceError(502, UNUSABLE) from None

    if model_output is None:  # pragma: no cover
        logger.error("OpenAI returned no validated response")
        raise LLMServiceError(502, UNUSABLE)

    return AskResponse(
        answer=model_output.answer,
        model=request.model,
        tokens_used=tokens_used,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        cost_usd=cost_usd,
    )
