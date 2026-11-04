"""Request ids, trace context and log correlation."""

import logging
import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind, StatusCode

from app.api.middleware import request_ids
from app.core import tracing
from app.core.tracing import CorrelationFilter, configure_logging
from app.main import app
from app.services import status_service
from tests.tracing_helpers import exporter

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{TRACE_ID}-{SPAN_ID}-01"


class RequestContextCase(unittest.TestCase):
    def setUp(self):
        exporter.clear()
        # Stands in for the handler filter that configure_logging installs on the root logger.
        errors = logging.getLogger("app.api.errors")
        correlation = CorrelationFilter()
        errors.addFilter(correlation)
        self.addCleanup(errors.removeFilter, correlation)
        self.client = TestClient(app, raise_server_exceptions=False)

    def server_span(self):
        """The one HTTP server span FastAPI opened for the request."""
        (span,) = [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
        return span


class TestRequestId(RequestContextCase):
    def test_every_response_carries_a_generated_id(self):
        first = self.client.get("/health").headers["X-Request-ID"]
        second = self.client.get("/health").headers["X-Request-ID"]

        self.assertRegex(first, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first, second)

    def test_errors_and_unknown_routes_carry_it_too(self):
        for path in ("/no/such/route", "/models", "/ask"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertGreaterEqual(response.status_code, 400)
                self.assertRegex(response.headers["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_a_plain_id_from_the_caller_is_kept(self):
        response = self.client.get("/health", headers={"X-Request-ID": "ticket-42_a.b"})

        self.assertEqual(response.headers["X-Request-ID"], "ticket-42_a.b")

    def test_an_unsafe_id_is_replaced(self):
        for value in ("has space", "x" * 65, "semi;colon", "<script>"):
            with self.subTest(value=value):
                response = self.client.get("/health", headers={"X-Request-ID": value})
                self.assertRegex(response.headers["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_lifespan_events_pass_through(self):
        with TestClient(app) as client:  # startup and shutdown are not HTTP requests
            self.assertEqual(client.get("/health").status_code, 200)

    def test_without_a_request_the_ids_are_empty(self):
        self.assertEqual(tracing.current_request_id(), "-")
        self.assertEqual(tracing.current_trace_id(), "-")
        self.assertEqual(request_ids({}), {"request_id": "-", "trace_id": "-"})


class TestSpans(RequestContextCase):
    def test_a_request_is_one_server_span_named_after_its_route(self):
        response = self.client.get("/health", headers={"X-Request-ID": "abc"})

        span = self.server_span()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(span.name, "GET /health")
        self.assertIsNone(span.parent)
        self.assertEqual(span.attributes["http.route"], "/health")
        self.assertEqual(span.attributes["http.response.status_code"], 200)
        self.assertEqual(span.attributes["answerworks.request_id"], "abc")

    def test_every_span_of_the_request_carries_its_id(self):
        self.client.get("/health", headers={"X-Request-ID": "abc"})

        spans = exporter.get_finished_spans()
        self.assertGreater(len(spans), 1)  # the server span and FastAPI's own operation spans
        self.assertEqual({s.attributes["answerworks.request_id"] for s in spans}, {"abc"})
        self.assertEqual({s.context.trace_id for s in spans}, {spans[0].context.trace_id})

    def test_parameters_stay_out_of_the_span_name(self):
        self.client.get("/conversations/11111111-1111-1111-1111-111111111111")

        span = self.server_span()
        self.assertEqual(span.name, "GET /conversations/{conversation_id}")

    def test_an_incoming_traceparent_is_continued(self):
        self.client.get("/health", headers={"traceparent": TRACEPARENT})

        span = self.server_span()
        self.assertEqual(f"{span.context.trace_id:032x}", TRACE_ID)
        self.assertEqual(f"{span.parent.span_id:016x}", SPAN_ID)

    def test_a_malformed_traceparent_starts_a_new_trace(self):
        self.client.get("/health", headers={"traceparent": "garbage"})

        span = self.server_span()
        self.assertIsNone(span.parent)
        self.assertNotEqual(f"{span.context.trace_id:032x}", TRACE_ID)

    def test_server_errors_mark_the_span(self):
        with patch.object(status_service, "readiness", side_effect=RuntimeError("boom")):
            with self.assertLogs("app.api.errors", level="ERROR"):
                response = self.client.get("/health/ready")

        span = self.server_span()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(span.attributes["http.response.status_code"], 500)
        self.assertEqual(span.status.status_code, StatusCode.ERROR)


class TestLogCorrelation(RequestContextCase):
    def logged(self, headers):
        """The record logged by the validation-error handler, run through the correlation filter."""
        with self.assertLogs("app.api.errors", level="WARNING") as captured:
            self.client.post("/ask", json={}, headers=headers)
        return captured.records[0]

    def test_log_lines_inside_a_request_carry_its_ids(self):
        record = self.logged({"X-Request-ID": "abc", "traceparent": TRACEPARENT})

        self.assertEqual(record.request_id, "abc")
        self.assertEqual(record.trace_id, TRACE_ID)

    def test_each_request_gets_its_own_trace_when_none_is_supplied(self):
        first = self.logged({})
        second = self.logged({})

        self.assertRegex(first.trace_id, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first.trace_id, second.trace_id)
        self.assertNotEqual(first.request_id, second.request_id)

    def test_an_unexpected_error_is_logged_with_the_request_ids(self):
        headers = {"X-Request-ID": "boom-1", "traceparent": TRACEPARENT}
        with patch.object(status_service, "readiness", side_effect=RuntimeError("boom")):
            with self.assertLogs("app.api.errors", level="ERROR") as captured:
                response = self.client.get("/health/ready", headers=headers)

        record = captured.records[0]
        self.assertEqual(response.headers["X-Request-ID"], "boom-1")
        self.assertEqual(record.request_id, "boom-1")
        self.assertEqual(record.trace_id, TRACE_ID)
        self.assertEqual(
            response.json(), {"detail": "The request could not be completed. Please try again."}
        )

    def test_the_formatted_line_shows_both_ids(self):
        record = logging.LogRecord("app.x", logging.WARNING, __file__, 1, "hello", None, None)
        record.request_id, record.trace_id = "abc", TRACE_ID
        formatter = logging.Formatter(tracing.LOG_FORMAT)

        self.assertRegex(formatter.format(record), rf"\[request=abc trace={TRACE_ID}\] hello$")


class TestConfigureLogging(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        configure_logging()  # earlier tests (alembic's logging setup) may have removed the handler
        self.handlers = len(root.handlers)

    def test_it_is_idempotent_and_reads_the_level_from_the_environment(self):
        root = logging.getLogger()

        with patch.dict(os.environ, {"LOG_LEVEL": "debug"}):
            configure_logging()
            configure_logging()
        self.assertEqual(root.level, logging.DEBUG)
        self.assertEqual(len(root.handlers), self.handlers)

        with patch.dict(os.environ, {"LOG_LEVEL": ""}):  # empty, as in a copied .env.example
            configure_logging("ERROR")
        self.assertEqual(root.level, logging.ERROR)

    def test_the_filter_does_not_overwrite_ids_that_were_given(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
        record.request_id = "given"

        CorrelationFilter().filter(record)

        self.assertEqual(record.request_id, "given")
        self.assertEqual(record.trace_id, "-")
        self.assertIsNotNone(re.compile(tracing.LOG_FORMAT.replace("%(", "(")))


if __name__ == "__main__":
    unittest.main()
