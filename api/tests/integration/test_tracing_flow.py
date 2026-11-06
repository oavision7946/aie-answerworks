"""One chat request is one trace through every step, and no content ends up in it."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind, StatusCode

from app.core import tracing
from app.main import app
from app.services.rag import retrieval_service
from tests.rag_helpers import RagTestCase
from tests.tracing_helpers import clear, exporter, sanitized

EXPECTED = {
    "chat.prepare",
    "rag.retrieve",
    "embed.query",
    "embed.batch",
    "vector.search",
    "llm.complete",
    "chat.persist",
}
# Text a user might type or store, which must never appear in a span.
PROMPT = "PROMPTSECRET where do penguins live"
DOCUMENT = "DOCSECRET Penguins live in Antarctica. They eat fish and krill.\n"
EMAIL = "alice@example.com"


def tree(spans):
    """name -> parent name, for the spans of one trace."""
    by_id = {s.context.span_id: s for s in spans}
    return {
        s.name: by_id[s.parent.span_id].name
        for s in spans
        if s.parent is not None and s.parent.span_id in by_id
    }


def everything(spans) -> str:
    """Every name, attribute, event and status description of the spans, as one string."""
    parts = []
    for s in spans:
        parts += [s.name, json.dumps(dict(s.attributes or {}), default=str)]
        parts += [e.name + json.dumps(dict(e.attributes or {}), default=str) for e in s.events]
        parts.append(s.status.description or "")
    return "\n".join(parts)


class TracingCase(RagTestCase):
    def setUp(self):
        super().setUp()
        clear()
        self.addCleanup(clear)

    def rag_chat(self, **body):
        return self.chat(self.alice, PROMPT, use_rag=True, **body)

    def server_spans(self, spans):
        return [s for s in spans if s.kind == SpanKind.SERVER]


class TestLifecycle(TracingCase):
    def test_a_chat_with_documents_is_one_trace_with_every_step(self):
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        clear()

        response = self.rag_chat()
        spans = exporter.get_finished_spans()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len({s.context.trace_id for s in spans}), 1)
        self.assertTrue(EXPECTED <= {s.name for s in spans}, {s.name for s in spans})
        (server,) = self.server_spans(spans)
        self.assertEqual(server.name, "POST /chat")

    def test_the_steps_nest_the_way_the_request_flows(self):
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        clear()

        self.rag_chat()
        parents = tree(exporter.get_finished_spans())

        self.assertEqual(parents["rag.retrieve"], "chat.prepare")
        self.assertEqual(parents["embed.query"], "rag.retrieve")
        self.assertEqual(parents["embed.batch"], "embed.query")
        self.assertEqual(parents["vector.search"], "rag.retrieve")

    def test_steps_report_counts_and_names_but_not_content(self):
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        clear()

        self.rag_chat()
        spans = {s.name: s for s in exporter.get_finished_spans()}

        retrieve = spans["rag.retrieve"].attributes
        self.assertEqual(retrieve["answerworks.embedding"], "fake-a")
        self.assertGreaterEqual(retrieve["answerworks.hits"], 1)
        self.assertGreaterEqual(spans["vector.search"].attributes["answerworks.rows"], 1)
        self.assertEqual(spans["vector.search"].attributes["db.system"], "sqlite")
        self.assertEqual(spans["embed.batch"].attributes["answerworks.texts"], 1)
        self.assertEqual(spans["chat.prepare"].attributes["answerworks.use_rag"], True)
        self.assertEqual(
            spans["chat.prepare"].attributes["answerworks.user_id"], str(self.alice.id)
        )
        self.assertIn("answerworks.tokens.input", spans["llm.complete"].attributes)
        self.assertIn("answerworks.conversation_id", spans["chat.persist"].attributes)

    def test_without_documents_there_is_no_retrieval(self):
        self.chat(self.alice, "hello")
        names = {s.name for s in exporter.get_finished_spans()}

        self.assertLessEqual({"chat.prepare", "llm.complete", "chat.persist"}, names)
        self.assertFalse({"rag.retrieve", "embed.query", "vector.search"} & names)

    def test_every_span_carries_the_request_id(self):
        self.chat(self.alice, "hello", **{})
        spans = exporter.get_finished_spans()

        ids = {s.attributes.get("answerworks.request_id") for s in spans}

        self.assertEqual(len(ids), 1)
        self.assertNotIn(None, ids)

    def test_a_streamed_answer_is_traced_and_its_model_call_ends_before_it_is_stored(self):
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        clear()

        response = self.rag_chat(stream=True)
        spans = {s.name: s for s in exporter.get_finished_spans()}

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len({s.context.trace_id for s in spans.values()}), 1)
        stream = spans["llm.stream"]
        self.assertIn("answerworks.time_to_first_token_ms", stream.attributes)
        self.assertGreaterEqual(stream.attributes["answerworks.chunks"], 1)
        self.assertLessEqual(stream.end_time, spans["chat.persist"].start_time)
        self.assertEqual(spans["chat.persist"].parent.span_id, spans["POST /chat"].context.span_id)

    def test_a_failed_model_call_marks_the_span_and_the_trace_still_ends(self):
        self.provider.fail_next = True if hasattr(self.provider, "fail_next") else None
        with patch.object(
            self.registry.providers[self.provider.name],
            "complete",
            side_effect=RuntimeError("boom"),
        ):
            response = self.chat(self.alice, "hello")
        spans = {s.name: s for s in exporter.get_finished_spans()}

        self.assertEqual(response.status_code, 502)
        self.assertEqual(spans["llm.complete"].status.status_code, StatusCode.ERROR)
        self.assertEqual(spans["llm.complete"].attributes["error.type"], "RuntimeError")


class TestPrivacy(TracingCase):
    """Nothing a user typed, stored or was shown may appear in what is exported."""

    SECRETS = ("PROMPTSECRET", "DOCSECRET", EMAIL, "ANSWERSECRET")

    def assert_clean(self, spans, *, extra=()):
        text = everything(spans)
        for secret in (*self.SECRETS, *extra):
            self.assertNotIn(secret, text)

    def test_a_chat_with_documents_leaves_no_content_in_any_span(self):
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        clear()
        self.provider.reply = (
            "ANSWERSECRET penguins live in Antarctica" if hasattr(self.provider, "reply") else None
        )

        response = self.rag_chat()

        self.assertEqual(response.status_code, 200, response.text)
        self.assert_clean(exporter.get_finished_spans())
        self.assert_clean(sanitized.get_finished_spans())

    def test_neither_does_a_streamed_chat_or_an_upload_or_a_search(self):
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        self.rag_chat(stream=True)
        self.search(self.alice, PROMPT)

        self.assert_clean(exporter.get_finished_spans())
        self.assert_clean(sanitized.get_finished_spans())

    def test_sql_spans_show_statements_without_the_values_bound_to_them(self):
        with patch.object(tracing, "_exporting", True):
            tracing.instrument_engine(self.engine)
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        clear()

        self.rag_chat()

        sql = [s for s in exporter.get_finished_spans() if s.name == "db.query"]
        self.assertTrue(sql)
        self.assert_clean(exporter.get_finished_spans())
        self.assertTrue(any("INSERT INTO messages" in s.attributes["db.query.text"] for s in sql))

    def test_query_strings_do_not_leave_the_process(self):
        self.client.get("/conversations?limit=5&q=PROMPTSECRET", headers=self.as_user(self.alice))
        raw = [s for s in exporter.get_finished_spans() if "url.query" in (s.attributes or {})]

        self.assertTrue(raw)  # the web framework records it...
        self.assert_clean(sanitized.get_finished_spans())  # ...and the exporter strips it

    def test_unexpected_errors_do_not_put_their_message_in_the_trace(self):
        self.upload(self.alice, "penguins.txt", DOCUMENT)
        clear()
        client = TestClient(app, raise_server_exceptions=False)
        with patch.object(retrieval_service.retriever, "search", side_effect=RuntimeError(PROMPT)):
            with self.assertLogs("app.api.errors", level="ERROR"):
                response = client.post(
                    "/chat",
                    json={"message": PROMPT, "use_rag": True},
                    headers=self.as_user(self.alice),
                )

        self.assertEqual(response.status_code, 500)
        self.assert_clean(exporter.get_finished_spans())
        self.assert_clean(sanitized.get_finished_spans())
        failing = [s for s in exporter.get_finished_spans() if s.name == "rag.retrieve"]
        self.assertEqual(failing[0].attributes["error.type"], "RuntimeError")

    def test_validation_errors_do_not_echo_the_input(self):
        response = self.client.post(
            "/chat",
            json={"message": PROMPT, "use_rag": "PROMPTSECRET"},
            headers=self.as_user(self.alice),
        )

        self.assertEqual(response.status_code, 422)
        self.assert_clean(exporter.get_finished_spans())
        self.assert_clean(sanitized.get_finished_spans())


class TestDisabledByDefault(unittest.TestCase):
    def test_nothing_is_exported_and_no_client_is_replaced_unless_tracing_is_enabled(self):
        self.assertFalse(tracing.is_exporting())
        self.assertIsNone(tracing.propagating_client())


if __name__ == "__main__":
    unittest.main()
