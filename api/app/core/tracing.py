"""Request correlation: a request id, W3C trace context and the log fields that carry them.

Every request gets an id (taken from `X-Request-ID` when the caller sends a sane one). FastAPI's
own telemetry opens the server span, continuing an incoming `traceparent` header or starting a
trace; this module stamps the request id on every span and puts both ids in log lines. No exporter
is configured here: the provider only creates ids and spans, so the cost without a backend is
negligible.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider

NO_ID = "-"


@dataclass
class RequestIds:
    """The ids of the request being served. `trace_id` is filled in when its first span starts."""

    request_id: str
    trace_id: str = NO_ID


ids_var: ContextVar[RequestIds | None] = ContextVar("request_ids", default=None)

_provider: TracerProvider | None = None


@contextmanager
def request_context(request_id: str) -> Iterator[RequestIds]:
    """Run a block (a request, a scheduler pass) under a request id.

    A span that is already open (FastAPI opens the server span before the middleware runs) is
    stamped here; spans started later are stamped by `RequestCorrelationProcessor`.
    """
    ids = RequestIds(request_id)
    token = ids_var.set(ids)
    try:
        span = trace.get_current_span()
        if span.get_span_context().is_valid:
            span.set_attribute("answerworks.request_id", request_id)
            ids.trace_id = trace.format_trace_id(span.get_span_context().trace_id)
        yield ids
    finally:
        ids_var.reset(token)


def current_request_id() -> str:
    ids = ids_var.get()
    return ids.request_id if ids else NO_ID


def current_trace_id() -> str:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        return trace.format_trace_id(context.trace_id)
    ids = ids_var.get()
    return ids.trace_id if ids else NO_ID


class RequestCorrelationProcessor(SpanProcessor):
    """Stamp the request id on every span, and remember the trace id for the request."""

    def on_start(self, span: Span, parent_context: otel_context.Context | None = None) -> None:
        ids = ids_var.get()
        if ids is None:
            return
        span.set_attribute("answerworks.request_id", ids.request_id)
        if ids.trace_id == NO_ID:
            ids.trace_id = trace.format_trace_id(span.get_span_context().trace_id)

    def on_end(self, span: ReadableSpan) -> None:
        pass


def init_tracing(service_name: str) -> None:
    """Install the process-wide tracer provider once; later calls change nothing."""
    global _provider
    if _provider is None:
        _provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        _provider.add_span_processor(RequestCorrelationProcessor())
        trace.set_tracer_provider(_provider)


def add_span_processor(processor: SpanProcessor) -> None:
    """Attach an exporter pipeline (or a test recorder) to the provider."""
    init_tracing("answerworks")
    assert _provider is not None
    _provider.add_span_processor(processor)


def tracer() -> trace.Tracer:
    return trace.get_tracer("answerworks")


class CorrelationFilter(logging.Filter):
    """Give every record `request_id` and `trace_id`, unless the caller already set them."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = current_request_id()
        if not hasattr(record, "trace_id"):
            record.trace_id = current_trace_id()
        return True


LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s [request=%(request_id)s trace=%(trace_id)s] %(message)s"
)


def configure_logging(default_level: str = "WARNING") -> None:
    """Send application logs to stderr with the correlation fields. `LOG_LEVEL` sets the level."""
    root = logging.getLogger()
    if not any(isinstance(f, CorrelationFilter) for h in root.handlers for f in h.filters):
        handler = logging.StreamHandler()
        handler.addFilter(CorrelationFilter())
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
    root.setLevel((os.environ.get("LOG_LEVEL") or default_level).upper())  # empty = unset
