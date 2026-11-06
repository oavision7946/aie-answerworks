"""Recorders for the spans a test produces: as created, and as they would be exported."""

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.tracing import SanitizingSpanExporter, add_span_processor

# Processors cannot be detached from the provider, so these serve every test.
exporter = InMemorySpanExporter()
sanitized = InMemorySpanExporter()
add_span_processor(SimpleSpanProcessor(exporter))
add_span_processor(SimpleSpanProcessor(SanitizingSpanExporter(sanitized)))


def clear() -> None:
    exporter.clear()
    sanitized.clear()
