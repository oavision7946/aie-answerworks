"""Trace context for the calls the web app makes to the API.

Each API call is a client span, and its `traceparent` header lets the API continue the same trace,
so a trace starts at the user's action rather than at the API. No exporter is configured here: the
provider only creates ids and spans, so the cost without a backend is negligible.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

_provider: TracerProvider | None = None


def init_tracing(service_name: str = "answerworks-ui") -> None:
    """Install the process-wide tracer provider once; later calls change nothing."""
    global _provider
    if _provider is None:
        _provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        trace.set_tracer_provider(_provider)


@contextmanager
def client_span(method: str, path: str) -> Iterator[Span]:
    """A span around one API call. The name keeps only the first path segment (no ids)."""
    route = path.split("?", 1)[0]
    first = "/" + route.strip("/").split("/", 1)[0]
    with trace.get_tracer("answerworks.ui").start_as_current_span(
        f"{method} {first}", kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("http.request.method", method)
        span.set_attribute("url.path", route)
        yield span


def record_status(span: Span, status_code: int) -> None:
    span.set_attribute("http.response.status_code", status_code)
    if status_code >= 500:
        span.set_status(Status(StatusCode.ERROR))


def inject(headers: dict[str, str]) -> dict[str, str]:
    """Add `traceparent` for the current span to the request headers."""
    propagate.inject(headers)
    return headers
