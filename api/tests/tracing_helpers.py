"""A recorder for the spans a test produces."""

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.tracing import add_span_processor

# Processors cannot be detached from the provider, so one recorder serves every test.
exporter = InMemorySpanExporter()
add_span_processor(SimpleSpanProcessor(exporter))
