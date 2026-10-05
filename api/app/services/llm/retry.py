import logging
import time
from collections.abc import Callable

from app.core.settings import RequestConfig
from app.services.llm.errors import TransientProviderError


def retry_delay(config: RequestConfig, attempt: int) -> float:
    return float(config.retry_base_delay_seconds * (2**attempt))


def log_retry(
    logger: logging.Logger, label: str, exc: Exception, attempt: int, config: RequestConfig
) -> float:
    delay = retry_delay(config, attempt)
    logger.warning(
        "Transient %s failure (%s), attempt %d/%d; retrying in %.1f seconds",
        label,
        type(exc).__name__,
        attempt + 1,
        config.max_attempts,
        delay,
    )
    return delay


def call_with_retry[T](
    call: Callable[[], T], config: RequestConfig, logger: logging.Logger, label: str
) -> T:
    """Run call(), retrying TransientProviderError with exponential backoff."""
    for attempt in range(config.max_attempts):
        try:
            return call()
        except TransientProviderError as exc:
            if attempt + 1 == config.max_attempts:
                logger.exception("%s request failed after %d attempts", label, config.max_attempts)
                raise
            time.sleep(log_retry(logger, label, exc, attempt, config))
        except Exception:
            logger.exception("%s request failed with a non-retryable error", label)
            raise
    raise AssertionError("unreachable")  # pragma: no cover
