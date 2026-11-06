"""The tracing module: what is exported, what is stripped, and how spans are made."""

import unittest
from unittest.mock import MagicMock, patch

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.core import tracing
from app.core.settings import TracingConfig
from app.services.llm import registry
from tests.tracing_helpers import clear, exporter

SECRET = "SECRET-TEXT-" + "x" * 600


def recorded_provider():
    """A provider that keeps finished spans, with its tracer."""
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    return provider.get_tracer("test"), memory


class TestSanitize(unittest.TestCase):
    def finished(self):
        tracer, memory = recorded_provider()
        with tracer.start_as_current_span("op", record_exception=False) as span:
            span.set_attribute("url.query", "q=SECRET")
            span.set_attribute("http.request.header.authorization", "Bearer SECRET")
            span.set_attribute("http.route", "/chat")
            span.set_attribute("db.statement", SECRET)
            span.set_attribute("answerworks.rows", 3)
            span.record_exception(ValueError("SECRET in the message"))
            span.add_event("note", {"detail": SECRET, "n": 1})
            span.set_status(Status(StatusCode.ERROR, "failed because of SECRET"))
        (finished,) = memory.get_finished_spans()
        return finished

    def test_content_bearing_attributes_are_dropped_and_the_rest_kept(self):
        clean = tracing.sanitize(self.finished())

        self.assertNotIn("url.query", clean.attributes)
        self.assertNotIn("http.request.header.authorization", clean.attributes)
        self.assertEqual(clean.attributes["http.route"], "/chat")
        self.assertEqual(clean.attributes["answerworks.rows"], 3)

    def test_long_strings_are_clipped(self):
        clean = tracing.sanitize(self.finished())

        self.assertEqual(len(clean.attributes["db.statement"]), tracing.MAX_VALUE_CHARS)

    def test_exception_events_keep_only_the_type_and_other_events_are_clipped(self):
        events = {e.name: e for e in tracing.sanitize(self.finished()).events}

        self.assertEqual(dict(events["exception"].attributes), {"exception.type": "ValueError"})
        self.assertEqual(len(events["note"].attributes["detail"]), tracing.MAX_VALUE_CHARS)
        self.assertEqual(events["note"].attributes["n"], 1)

    def test_the_status_keeps_its_code_but_not_its_description(self):
        clean = tracing.sanitize(self.finished())

        self.assertEqual(clean.status.status_code, StatusCode.ERROR)
        self.assertIsNone(clean.status.description)

    def test_identity_is_preserved(self):
        original = self.finished()

        clean = tracing.sanitize(original)

        for field in ("name", "context", "parent", "kind", "start_time", "end_time"):
            self.assertEqual(getattr(clean, field), getattr(original, field))
        self.assertEqual(clean.instrumentation_scope, original.instrumentation_scope)

    def test_the_exporter_hands_clean_spans_to_the_one_it_wraps(self):
        inner = InMemorySpanExporter()
        exporter = tracing.SanitizingSpanExporter(inner)

        exporter.export([self.finished()])

        (sent,) = inner.get_finished_spans()
        self.assertNotIn("url.query", sent.attributes)
        self.assertTrue(exporter.force_flush())
        exporter.shutdown()


class TestBuildProvider(unittest.TestCase):
    def spans_from(self, provider, name="op"):
        with provider.get_tracer("test").start_as_current_span(name):
            pass
        provider.force_flush()

    def test_without_config_or_when_disabled_nothing_is_exported(self):
        for config in (None, TracingConfig()):
            with self.subTest(config=config):
                memory = InMemorySpanExporter()
                provider = tracing.build_provider("svc", config, span_exporter=memory)

                self.spans_from(provider)

                self.assertEqual(memory.get_finished_spans(), ())

    def test_enabled_exports_spans_with_the_service_name(self):
        memory = InMemorySpanExporter()
        provider = tracing.build_provider(
            "svc", TracingConfig(enabled=True), "production", span_exporter=memory
        )

        self.spans_from(provider)

        (span,) = memory.get_finished_spans()
        self.assertEqual(span.resource.attributes["service.name"], "svc")
        self.assertEqual(span.resource.attributes["deployment.environment.name"], "production")

    def test_exported_spans_are_sanitized(self):
        memory = InMemorySpanExporter()
        provider = tracing.build_provider("svc", TracingConfig(enabled=True), span_exporter=memory)

        with provider.get_tracer("t").start_as_current_span("op") as span:
            span.set_attribute("url.query", "q=SECRET")
        provider.force_flush()

        self.assertNotIn("url.query", memory.get_finished_spans()[0].attributes)

    def test_the_sample_ratio_applies_to_new_traces_but_not_to_a_callers_decision(self):
        memory = InMemorySpanExporter()
        provider = tracing.build_provider(
            "svc", TracingConfig(enabled=True, sample_ratio=0.0), span_exporter=memory
        )
        tracer = provider.get_tracer("t")

        with tracer.start_as_current_span("new trace"):
            pass
        remote = trace.SpanContext(1, 2, True, trace.TraceFlags(trace.TraceFlags.SAMPLED))
        context = trace.set_span_in_context(trace.NonRecordingSpan(remote))
        with tracer.start_as_current_span("continued", context=context):
            pass
        provider.force_flush()

        self.assertEqual([s.name for s in memory.get_finished_spans()], ["continued"])

    def test_the_otlp_exporter_posts_to_the_traces_path_of_the_endpoint(self):
        config = TracingConfig(
            enabled=True, otlp_endpoint="http://collector:4318/", export_timeout_seconds=2
        )
        target = "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"

        with patch(target) as otlp:
            otlp.return_value = InMemorySpanExporter()
            tracing.build_provider("svc", config)

        otlp.assert_called_once_with(endpoint="http://collector:4318/v1/traces", timeout=2)

    def test_the_request_id_is_stamped_on_spans_started_inside_a_request(self):
        memory = InMemorySpanExporter()
        provider = tracing.build_provider("svc", None)
        provider.add_span_processor(SimpleSpanProcessor(memory))

        with tracing.request_context("req-1"):
            self.spans_from(provider)
        self.spans_from(provider, "outside")

        inside, outside = memory.get_finished_spans()
        self.assertEqual(inside.attributes["answerworks.request_id"], "req-1")
        self.assertNotIn("answerworks.request_id", outside.attributes)


class TestSpanHelper(unittest.TestCase):
    def test_attributes_are_set_and_none_is_left_out(self):
        tracing.init_tracing("test")
        clear()
        with tracing.span("work", **{"answerworks.a": 1, "answerworks.b": None}):
            pass

        (span,) = exporter.get_finished_spans()
        self.assertEqual(dict(span.attributes), {"answerworks.a": 1})

    def test_a_failure_marks_the_span_with_the_exception_type_and_never_its_message(self):
        clear()
        with self.assertRaises(ValueError):
            with tracing.span("work"):
                raise ValueError("SECRET in the message")

        (span,) = exporter.get_finished_spans()
        self.assertEqual(span.status.status_code, StatusCode.ERROR)
        self.assertIsNone(span.status.description)
        self.assertEqual(span.attributes["error.type"], "ValueError")
        self.assertEqual(span.events, ())


class TestIterateInSpan(unittest.TestCase):
    def test_the_span_is_active_only_while_the_generator_works(self):
        tracer, _ = recorded_provider()
        current = tracer.start_span("stream")
        seen = []

        def source():
            for i in range(2):
                seen.append(trace.get_current_span() is current)
                yield i

        results = []
        for item in tracing.iterate_in_span(current, source()):
            results.append((item, trace.get_current_span() is current))

        self.assertEqual(seen, [True, True])
        self.assertEqual(results, [(0, False), (1, False)])


class TestPropagation(unittest.TestCase):
    def test_traceparent_is_added_inside_a_span(self):
        tracer, _ = recorded_provider()
        request = httpx.Request("POST", "http://models.local/v1/chat")

        with tracer.start_as_current_span("llm"):
            tracing.inject_trace_context(request)

        self.assertRegex(request.headers["traceparent"], r"^00-[0-9a-f]{32}-[0-9a-f]{16}-0\d$")

    def test_no_client_is_built_unless_exporting(self):
        with patch.object(tracing, "_exporting", False):
            self.assertIsNone(tracing.propagating_client())
        with patch.object(tracing, "_exporting", True):
            client = tracing.propagating_client()
            self.addCleanup(client.close)
            self.assertIn(tracing.inject_trace_context, client.event_hooks["request"])

    def test_only_local_providers_get_the_propagating_client(self):
        client = object()
        with patch.object(tracing, "propagating_client", return_value=client):
            with (
                patch.object(registry, "LocalProvider") as local,
                patch.object(registry, "OpenAIProvider") as hosted,
            ):
                config = MagicMock(type="openai_compatible")
                registry.build_provider("local", config, MagicMock(), None)
                config = MagicMock(type="openai")
                registry.build_provider("openai", config, MagicMock(), "key")

        self.assertIs(local.call_args.args[4], client)
        self.assertEqual(len(hosted.call_args.args), 4)  # no tracing client for third parties


class TestEngineInstrumentation(unittest.TestCase):
    def setUp(self):
        clear()
        self.addCleanup(clear)
        self.engine = create_engine("sqlite://")

    def queries(self):
        return [s for s in exporter.get_finished_spans() if s.name == "db.query"]

    def test_nothing_is_traced_unless_exporting(self):
        with patch.object(tracing, "_exporting", False):
            tracing.instrument_engine(self.engine)
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        self.assertEqual(self.queries(), [])

    def test_each_statement_is_a_span_with_its_text_and_never_its_values(self):
        with patch.object(tracing, "_exporting", True):
            tracing.instrument_engine(self.engine)
            tracing.instrument_engine(self.engine)  # twice: still one span per statement
        with self.engine.connect() as connection:
            connection.execute(text("SELECT :value"), {"value": "SECRET-VALUE"})

        (query,) = self.queries()
        self.assertEqual(query.attributes["db.system"], "sqlite")
        self.assertEqual(query.attributes["db.operation.name"], "SELECT")
        self.assertIn("SELECT", query.attributes["db.query.text"])
        self.assertNotIn("SECRET-VALUE", str(dict(query.attributes)))

    def test_a_failing_statement_is_marked_with_the_error_type_only(self):
        with patch.object(tracing, "_exporting", True):
            tracing.instrument_engine(self.engine)
        with self.assertRaises(OperationalError):
            with self.engine.connect() as connection:
                connection.execute(text("SELECT * FROM no_such_table"))

        (query,) = self.queries()
        self.assertEqual(query.status.status_code, StatusCode.ERROR)
        self.assertEqual(query.attributes["error.type"], "OperationalError")
        self.assertIsNone(query.status.description)

    def test_a_statement_with_no_words_still_gets_an_operation_name(self):
        self.assertEqual(tracing._operation("   "), "SQL")
        self.assertEqual(tracing._operation("insert into t values (1)"), "INSERT")

    def test_an_error_outside_a_statement_is_ignored(self):
        context = MagicMock(connection=None)

        tracing._fail_query(context)  # must not raise
        tracing._end_query(MagicMock(info={}))


if __name__ == "__main__":
    unittest.main()
