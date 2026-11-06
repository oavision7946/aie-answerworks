"""Trace context for the calls the web app makes to the API.

Each API call is a client span, and its `traceparent` header lets the API continue the same trace,
so a trace starts at the user's action rather than at the API. Spans are exported only when
`TRACING_ENABLED` is set; otherwise the provider just creates ids and spans, which costs next to
nothing. Spans hold the method, the path and the status code, never request or response content,
and a failure is recorded as its exception type only.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from app import config

_provider: TracerProvider | None = None


def build_provider(
    service_name: str,
    enabled: bool,
    endpoint: str,
    span_exporter: SpanExporter | None = None,
) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if enabled:
        exporter = span_exporter
        if exporter is None:  # imported here so a disabled setup never loads the exporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=5)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def init_tracing(service_name: str = "answerworks-ui") -> None:
    """Install the process-wide tracer provider once; later calls change nothing."""
    global _provider
    if _provider is None:
        _provider = build_provider(service_name, config.TRACING_ENABLED, config.OTLP_ENDPOINT)
        trace.set_tracer_provider(_provider)


@contextmanager
def client_span(method: str, path: str) -> Iterator[Span]:
    """A span around one API call. The name keeps only the first path segment (no ids)."""
    route = path.split("?", 1)[0]
    first = "/" + route.strip("/").split("/", 1)[0]
    with trace.get_tracer("answerworks.ui").start_as_current_span(
        f"{method} {first}",
        kind=SpanKind.CLIENT,
        record_exception=False,  # an exception message can quote what the user sent
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("http.request.method", method)
        span.set_attribute("url.path", route)
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def record_status(span: Span, status_code: int) -> None:
    span.set_attribute("http.response.status_code", status_code)
    if status_code >= 500:
        span.set_status(Status(StatusCode.ERROR))


def inject(headers: dict[str, str]) -> dict[str, str]:
    """Add `traceparent` for the current span to the request headers."""
    propagate.inject(headers)
    return headers
