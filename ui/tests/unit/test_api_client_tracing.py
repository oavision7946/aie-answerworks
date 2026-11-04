"""Every call to the API is a client span, and its trace context goes out as `traceparent`."""

import json
import re
import unittest

import httpx
import respx
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from app import config, tracing
from app.clients import api_client

BASE = config.API_BASE_URL.rstrip("/")
GPT = api_client.ModelInfo(provider="openai", id="gpt-4o", label="GPT-4o")
TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-0[1-3]$")
RESULT = {"answer": "ok", "provider": "openai", "model": "gpt-4o", "tokens_used": 1}
PAIR = {"access_token": "a", "refresh_token": "r"}
ME = {
    "id": "u-1",
    "email": "ana@example.com",
    "role": "user",
    "is_active": True,
    "must_change_password": False,
}

# Processors cannot be detached from the provider, so one recorder serves every test.
exporter = InMemorySpanExporter()
tracing.init_tracing()
provider = trace.get_tracer_provider()
provider.add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[attr-defined]


def sse(*events):
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


class TestTraceparent(unittest.TestCase):
    def setUp(self):
        exporter.clear()

    @respx.mock
    def test_each_kind_of_call_sends_a_traceparent_matching_its_span(self):
        respx.post(f"{BASE}/auth/login").respond(json=PAIR)
        respx.get(f"{BASE}/models").respond(json={"models": []})
        respx.post(f"{BASE}/ask").respond(json=RESULT)
        respx.get(f"{BASE}/auth/me").respond(json=ME)
        calls = {
            "POST /auth": lambda: api_client.login("ana@example.com", "pw"),
            "GET /models": lambda: api_client.get_models(token="t"),
            "POST /ask": lambda: api_client.call_api("hi", GPT, False, token="t"),
            "GET /auth": lambda: api_client.get_me("t"),
        }
        for name, call in calls.items():
            with self.subTest(call=name):
                exporter.clear()
                respx.calls.reset()

                call()

                (span,) = exporter.get_finished_spans()
                sent = TRACEPARENT.match(respx.calls.last.request.headers["traceparent"])
                self.assertEqual(span.name, name)
                self.assertEqual(span.kind, SpanKind.CLIENT)
                self.assertEqual(span.attributes["http.response.status_code"], 200)
                self.assertEqual(sent.group(1), f"{span.context.trace_id:032x}")
                self.assertEqual(sent.group(2), f"{span.context.span_id:016x}")

    @respx.mock
    def test_a_streaming_call_is_one_span_for_the_whole_stream(self):
        stream = respx.post(f"{BASE}/ask").respond(
            text=sse(("delta", {"content": "Hi"}), ("done", RESULT)),
            headers={"content-type": "text/event-stream"},
        )

        api_client.call_streaming_api("hi", GPT, False, lambda _: None, token="t")

        (span,) = exporter.get_finished_spans()
        self.assertEqual(span.name, "POST /ask")
        self.assertTrue(TRACEPARENT.match(stream.calls.last.request.headers["traceparent"]))

    @respx.mock
    def test_separate_actions_are_separate_traces_and_nested_ones_share_a_trace(self):
        respx.get(f"{BASE}/models").respond(json={"models": []})

        api_client.get_models(token="t")
        api_client.get_models(token="t")
        first, second = exporter.get_finished_spans()
        self.assertNotEqual(first.context.trace_id, second.context.trace_id)

        exporter.clear()
        with trace.get_tracer("test").start_as_current_span("user action"):
            api_client.get_models(token="t")
            api_client.get_models(token="t")
        a, b, parent = exporter.get_finished_spans()
        self.assertEqual({a.context.trace_id, b.context.trace_id}, {parent.context.trace_id})

    @respx.mock
    def test_span_names_leave_out_ids_and_query_strings(self):
        respx.get(f"{BASE}/conversations/c-1").respond(json={})

        try:
            api_client._send("GET", "/conversations/c-1?limit=5", "t")
        except RuntimeError:
            pass

        (span,) = exporter.get_finished_spans()
        self.assertEqual(span.name, "GET /conversations")
        self.assertEqual(span.attributes["url.path"], "/conversations/c-1")

    @respx.mock
    def test_server_errors_mark_the_span_and_so_do_unreachable_servers(self):
        respx.get(f"{BASE}/auth/me").respond(503, json={"detail": "down"})
        with self.assertRaises(RuntimeError):
            api_client.get_me("t")
        (span,) = exporter.get_finished_spans()
        self.assertEqual(span.status.status_code, StatusCode.ERROR)
        self.assertEqual(span.attributes["http.response.status_code"], 503)

        exporter.clear()
        respx.get(f"{BASE}/auth/me").mock(side_effect=httpx.ConnectError("no route"))
        with self.assertRaises(RuntimeError):
            api_client.get_me("t")
        (span,) = exporter.get_finished_spans()
        self.assertEqual(span.status.status_code, StatusCode.ERROR)

    @respx.mock
    def test_no_token_means_no_authorization_header_but_still_a_traceparent(self):
        route = respx.post(f"{BASE}/auth/login").respond(json=PAIR)

        api_client.login("ana@example.com", "pw")

        headers = route.calls.last.request.headers
        self.assertNotIn("authorization", headers)
        self.assertIn("traceparent", headers)

    def test_initialising_twice_keeps_the_first_provider(self):
        before = trace.get_tracer_provider()

        tracing.init_tracing("other-name")

        self.assertIs(trace.get_tracer_provider(), before)


if __name__ == "__main__":
    unittest.main()
