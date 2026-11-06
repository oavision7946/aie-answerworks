"""Request correlation and tracing: ids, spans, the exporter and what may leave the process.

Every request gets an id (taken from `X-Request-ID` when the caller sends a sane one). FastAPI's
own telemetry opens the server span, continuing an incoming `traceparent` header or starting a
trace; this module stamps the request id on every span, puts both ids in log lines, and, when
`config/monitoring.yaml` turns tracing on, exports spans over OTLP.

Spans carry ids, route templates, model names, sizes, counts and timings. They never carry
prompts, answers, document text or email addresses. Code that adds spans keeps to that, and the
exporter drops anything that could slip through (query strings, exception messages, headers).
"""

import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import event

from app.core.settings import TracingConfig

NO_ID = "-"


@dataclass
class RequestIds:
    """The ids of the request being served. `trace_id` is filled in when its first span starts."""

    request_id: str
    trace_id: str = NO_ID


ids_var: ContextVar[RequestIds | None] = ContextVar("request_ids", default=None)

_provider: TracerProvider | None = None
_exporting = False


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


MAX_VALUE_CHARS = 512
# Attributes that can hold user-supplied content, and header-like prefixes, never leave the process.
_DROPPED_ATTRIBUTES = frozenset({"url.query", "http.target", "http.url", "url.full"})
_DROPPED_PREFIXES = ("http.request.header.", "http.response.header.", "http.request.body")


def _clip(value: Any) -> Any:
    return value[:MAX_VALUE_CHARS] if isinstance(value, str) else value


def _keep(key: str) -> bool:
    return key not in _DROPPED_ATTRIBUTES and not key.startswith(_DROPPED_PREFIXES)


def _attributes(source: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: _clip(value) for key, value in (source or {}).items() if _keep(key)}


def _event(event: Event) -> Event:
    if event.name == "exception":  # the type is useful; the message and stack can hold anything
        kept = {k: v for k, v in (event.attributes or {}).items() if k == "exception.type"}
        return Event(event.name, kept, event.timestamp)
    return Event(event.name, _attributes(event.attributes), event.timestamp)


def sanitize(span: ReadableSpan) -> ReadableSpan:
    """A copy of the span that is safe to send out: see the module docstring."""
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=_attributes(span.attributes),
        events=[_event(event) for event in span.events],
        links=span.links,
        kind=span.kind,
        status=Status(span.status.status_code),  # no description: it may quote an exception
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class SanitizingSpanExporter(SpanExporter):
    """Passes every span through `sanitize` before the wrapped exporter sees it."""

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self.inner.export([sanitize(span) for span in spans])

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def build_provider(
    service_name: str,
    config: TracingConfig | None = None,
    environment: str = "",
    span_exporter: SpanExporter | None = None,
) -> TracerProvider:
    """A tracer provider that creates ids and spans, and exports them only when `config` says so."""
    attributes = {"service.name": service_name}
    if environment:
        attributes["deployment.environment.name"] = environment
    exporting = config is not None and config.enabled
    sampler = ParentBased(TraceIdRatioBased(config.sample_ratio)) if config and exporting else None
    provider = TracerProvider(resource=Resource.create(attributes), sampler=sampler)
    provider.add_span_processor(RequestCorrelationProcessor())
    if config is not None and exporting:
        exporter = span_exporter
        if exporter is None:  # imported here so a disabled setup never loads the exporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(
                endpoint=f"{config.otlp_endpoint}/v1/traces", timeout=config.export_timeout_seconds
            )
        provider.add_span_processor(BatchSpanProcessor(SanitizingSpanExporter(exporter)))
    return provider


def init_tracing(
    service_name: str, config: TracingConfig | None = None, environment: str = ""
) -> None:
    """Install the process-wide tracer provider once; later calls change nothing."""
    global _provider, _exporting
    if _provider is None:
        _provider = build_provider(service_name, config, environment)
        _exporting = config is not None and config.enabled
        trace.set_tracer_provider(_provider)


def is_exporting() -> bool:
    return _exporting


def add_span_processor(processor: SpanProcessor) -> None:
    """Attach an extra processor, for example a test recorder."""
    init_tracing("answerworks")
    assert _provider is not None
    _provider.add_span_processor(processor)


def _operation(statement: str) -> str:
    words = statement.split(None, 1)
    return words[0].upper() if words else "SQL"


def _start_query(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
    current = tracer().start_span(
        "db.query",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "db.system": conn.dialect.name,
            "db.operation.name": _operation(statement),
            "db.query.text": _clip(statement),  # the statement with placeholders, never the values
        },
    )
    conn.info.setdefault("answerworks.spans", []).append(current)


def _end_query(conn: Any, *args: Any) -> None:
    spans = conn.info.get("answerworks.spans")
    if spans:
        spans.pop().end()


def _fail_query(context: Any) -> None:
    spans = context.connection.info.get("answerworks.spans") if context.connection else None
    if spans:
        failed = spans.pop()
        failed.set_attribute("error.type", type(context.original_exception).__name__)
        failed.set_status(Status(StatusCode.ERROR))
        failed.end()


def instrument_engine(engine: Any) -> None:
    """Trace each SQL statement as a span when exporting: its text, never the bound values."""
    if not _exporting or event.contains(engine, "before_cursor_execute", _start_query):
        return
    event.listen(engine, "before_cursor_execute", _start_query)
    event.listen(engine, "after_cursor_execute", _end_query)
    event.listen(engine, "handle_error", _fail_query)


def inject_trace_context(request: httpx.Request) -> None:
    """httpx request hook: send `traceparent` so the receiving server can join the trace."""
    propagate.inject(request.headers)


def propagating_client() -> Any:
    """An OpenAI SDK HTTP client that sends `traceparent`, or None when not exporting.

    Used only for providers on the operator's own network (a local model server). Third-party
    APIs never receive our trace ids.
    """
    if not _exporting:
        return None
    from openai import DefaultHttpxClient

    return DefaultHttpxClient(event_hooks={"request": [inject_trace_context]})


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """A child span of the current one. Attributes set to None are left out.

    A failure marks the span as an error with its exception type only (never the message).
    """
    with tracer().start_as_current_span(
        name, record_exception=False, set_status_on_exception=False
    ) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        try:
            yield current
        except Exception as exc:
            current.set_attribute("error.type", type(exc).__name__)
            current.set_status(Status(StatusCode.ERROR))
            raise


def iterate_in_span[T](current: trace.Span, items: Iterator[T]) -> Iterator[T]:
    """Run each step of `items` with `current` as the active span.

    For generators, which hand control back to the caller between steps: the span is active only
    while the generator itself works, so calls it makes (an HTTP request) join the trace.
    """
    while True:
        token = otel_context.attach(trace.set_span_in_context(current))
        try:
            item = next(items)
        except StopIteration:
            return
        finally:
            otel_context.detach(token)
        yield item


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
