"""HTTP contract of /health, /models and /ask (ported from aie-log-analysis tests/test_main.py)."""

import unittest
from unittest.mock import call, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.llm import openai_service as svc
from tests.helpers import fake_response, sse_frames, stream_chunks, timeout_error

SETTINGS = svc.settings
LOGGER = "app.services.llm.openai_service"
STREAM_LOGGER = "app.services.llm.streaming"


class TestHealthAndModels(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_models_returns_configured_models(self):
        response = self.client.get("/models")

        self.assertEqual(response.status_code, 200)
        self.assertIn("gpt-4o-mini", response.json()["models"])

    def test_get_ask_explains_post_usage(self):
        response = self.client.get("/ask")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            response.json()["detail"],
            "/ask accepts POST requests with a JSON body. "
            "Use the chat app or open /docs to submit a question.",
        )
        self.assertEqual(response.headers["allow"], "POST")

    def test_unknown_route_returns_json_404(self):
        response = self.client.get("/nope")

        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())


class TestAsk(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_ask_includes_tokens_used(self):
        with patch.object(
            svc.client.chat.completions, "create", return_value=fake_response("Hello from OpenAI")
        ) as create:
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer"], "Hello from OpenAI")
        self.assertEqual(body["tokens_used"], 123)
        self.assertEqual(body["model"], "gpt-4o-mini")
        self.assertGreater(body["cost_usd"], 0)
        self.assertEqual(create.call_args.kwargs["model"], "gpt-4o-mini")
        self.assertEqual(create.call_args.kwargs["timeout"], SETTINGS.timeout_seconds)

    def test_ask_retries_transient_failure_with_exponential_backoff(self):
        with (
            patch.object(
                svc.client.chat.completions,
                "create",
                side_effect=[timeout_error(), fake_response("Recovered response")],
            ) as create,
            patch.object(svc.time, "sleep") as sleep,
        ):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Recovered response")
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].kwargs["timeout"], SETTINGS.timeout_seconds)
        sleep.assert_called_once_with(SETTINGS.retry_base_delay_seconds)

    def test_ask_returns_safe_error_and_logs_after_transient_retries_exhausted(self):
        errors = [timeout_error() for _ in range(SETTINGS.max_attempts)]
        with (
            self.assertLogs(LOGGER, level="WARNING") as captured,
            patch.object(svc.client.chat.completions, "create", side_effect=errors) as create,
            patch.object(svc.time, "sleep") as sleep,
        ):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The AI service is temporarily unavailable. Please try again shortly.",
        )
        self.assertEqual(create.call_count, SETTINGS.max_attempts)
        self.assertEqual(sleep.call_args_list, [call(0.5), call(1.0)])
        self.assertTrue(any("failed after 3 attempts" in m for m in captured.output))

    def test_ask_logs_unexpected_provider_error_without_exposing_it(self):
        with (
            self.assertLogs(LOGGER, level="ERROR") as captured,
            patch.object(
                svc.client.chat.completions,
                "create",
                side_effect=RuntimeError("provider internals must stay private"),
            ),
        ):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "The AI service could not complete your request. Please try again.",
        )
        self.assertNotIn("provider internals", response.text)
        self.assertTrue(any("provider internals must stay private" in m for m in captured.output))

    def test_ask_returns_error_when_openai_has_no_choices(self):
        empty = type("R", (), {"choices": [], "usage": None})()
        with patch.object(svc.client.chat.completions, "create", return_value=empty):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "The AI service returned an incomplete response. Please try again.",
        )

    def test_ask_returns_error_when_content_is_none(self):
        with patch.object(svc.client.chat.completions, "create", return_value=fake_response(None)):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 502)

    def test_ask_returns_error_when_usage_is_missing(self):
        no_usage = type("R", (), {"choices": fake_response("Hi").choices, "usage": None})()
        with patch.object(svc.client.chat.completions, "create", return_value=no_usage):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 502)
        self.assertIn("incomplete response", response.json()["detail"])

    def test_ask_rejects_invalid_request_before_calling_openai(self):
        with (
            self.assertLogs("app.api.errors", level="WARNING") as captured,
            patch.object(svc.client.chat.completions, "create") as create,
        ):
            response = self.client.post("/ask", json={"question": "   "})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "Invalid request. Check the question and selected model, then try again.",
        )
        self.assertTrue(any("Request validation failed" in m for m in captured.output))
        create.assert_not_called()

    def test_ask_rejects_unknown_model_and_extra_fields(self):
        with patch.object(svc.client.chat.completions, "create") as create:
            unknown_model = self.client.post("/ask", json={"question": "Hi", "model": "nope"})
            extra_field = self.client.post("/ask", json={"question": "Hi", "surprise": 1})

        self.assertEqual(unknown_model.status_code, 422)
        self.assertEqual(extra_field.status_code, 422)
        create.assert_not_called()

    def test_ask_forwards_selected_model(self):
        with patch.object(
            svc.client.chat.completions, "create", return_value=fake_response("Hello")
        ) as create:
            response = self.client.post("/ask", json={"question": "Hi", "model": "gpt-4o"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "gpt-4o")
        self.assertEqual(create.call_args.kwargs["model"], "gpt-4o")

    def test_ask_returns_error_for_forced_bad_first_response(self):
        with patch.object(
            svc.client.chat.completions, "create", return_value=fake_response("Valid")
        ) as create:
            response = self.client.post(
                "/ask", json={"question": "Hi", "force_bad_first_response": True}
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "The AI service returned an unusable response. Please try again.",
        )
        self.assertEqual(create.call_count, 1)

    def test_ask_accepts_demo_page_force_bad_field(self):
        with patch.object(
            svc.client.chat.completions, "create", return_value=fake_response("Valid")
        ) as create:
            response = self.client.post(
                "/ask", json={"question": "Hi", "model": "gpt-4o-mini", "force_bad": True}
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(create.call_count, 1)

    def test_ask_retries_after_unforced_invalid_response(self):
        responses = [fake_response(""), fake_response("Recovered response")]
        with patch.object(svc.client.chat.completions, "create", side_effect=responses) as create:
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Recovered response")
        self.assertEqual(response.json()["tokens_used"], 246)
        self.assertEqual(create.call_count, 2)

    def test_ask_fails_when_both_responses_are_invalid(self):
        responses = [fake_response(""), fake_response("   ")]
        with patch.object(svc.client.chat.completions, "create", side_effect=responses):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 502)
        self.assertIn("unusable response", response.json()["detail"])

    def test_ask_returns_503_when_client_not_configured(self):
        with patch.object(svc, "client", None):
            response = self.client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"], "The AI service is not configured. Please contact support."
        )

    def test_unexpected_error_returns_generic_500(self):
        client = TestClient(app, raise_server_exceptions=False)
        with (
            self.assertLogs("app.api.errors", level="ERROR"),
            patch.object(svc, "answer_question", side_effect=ValueError("secret detail")),
        ):
            response = client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"], "The request could not be completed. Please try again."
        )
        self.assertNotIn("secret detail", response.text)


class TestAskStreaming(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def post_stream(self, **extra):
        return self.client.post("/ask", json={"question": "Hi", "stream": True, **extra})

    def test_streams_deltas_and_completion_metadata(self):
        with patch.object(
            svc.client.chat.completions, "create", return_value=stream_chunks("Hello ", "there")
        ) as create:
            response = self.post_stream()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")
        frames = sse_frames(response.text)
        self.assertEqual([event for event, _ in frames], ["delta", "delta", "done"])
        self.assertEqual([p["content"] for _, p in frames[:2]], ["Hello ", "there"])
        self.assertEqual(frames[2][1]["answer"], "Hello there")
        self.assertEqual(frames[2][1]["tokens_used"], 123)
        self.assertTrue(create.call_args.kwargs["stream"])
        self.assertEqual(create.call_args.kwargs["stream_options"], {"include_usage": True})
        self.assertEqual(create.call_args.kwargs["timeout"], SETTINGS.timeout_seconds)

    def test_ignores_chunks_without_text(self):
        chunks = stream_chunks("Hi", None, "!")
        with patch.object(svc.client.chat.completions, "create", return_value=chunks):
            response = self.post_stream()

        frames = sse_frames(response.text)
        self.assertEqual(frames[-1][1]["answer"], "Hi!")

    def test_retries_transient_failure_before_first_delta(self):
        with (
            patch.object(
                svc.client.chat.completions,
                "create",
                side_effect=[timeout_error(), stream_chunks("Recovered")],
            ) as create,
            patch.object(svc.time, "sleep") as sleep,
        ):
            response = self.post_stream()

        self.assertEqual(response.status_code, 200)
        self.assertIn('"answer": "Recovered"', response.text)
        self.assertEqual(create.call_count, 2)
        sleep.assert_called_once_with(SETTINGS.retry_base_delay_seconds)

    def test_returns_safe_error_and_logs_after_retries_exhausted(self):
        errors = [timeout_error() for _ in range(SETTINGS.max_attempts)]
        with (
            self.assertLogs(STREAM_LOGGER, level="WARNING") as captured,
            patch.object(svc.client.chat.completions, "create", side_effect=errors) as create,
            patch.object(svc.time, "sleep") as sleep,
        ):
            response = self.post_stream()

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", response.text)
        self.assertIn("The AI service is temporarily unavailable.", response.text)
        self.assertNotIn("APITimeoutError", response.text)
        self.assertEqual(create.call_count, SETTINGS.max_attempts)
        self.assertEqual(sleep.call_args_list, [call(0.5), call(1.0)])
        self.assertTrue(
            any("OpenAI streaming request failed on attempt 3" in m for m in captured.output)
        )

    def test_non_transient_error_is_reported_without_retry(self):
        with (
            self.assertLogs(STREAM_LOGGER, level="ERROR"),
            patch.object(
                svc.client.chat.completions, "create", side_effect=RuntimeError("private")
            ) as create,
        ):
            response = self.post_stream()

        self.assertEqual(create.call_count, 1)
        self.assertIn("could not complete your request", response.text)
        self.assertNotIn("private", response.text)

    def test_forced_bad_first_response_emits_error_without_deltas(self):
        with (
            self.assertLogs(STREAM_LOGGER, level="WARNING"),
            patch.object(
                svc.client.chat.completions, "create", return_value=stream_chunks("Valid")
            ),
        ):
            response = self.post_stream(force_bad_first_response=True)

        self.assertEqual([event for event, _ in sse_frames(response.text)], ["error"])
        self.assertNotIn("event: delta", response.text)

    def test_blank_answer_is_retried_then_succeeds(self):
        streams = [stream_chunks(" "), stream_chunks("Better")]
        with (
            self.assertLogs(STREAM_LOGGER, level="WARNING"),
            patch.object(svc.client.chat.completions, "create", side_effect=streams) as create,
        ):
            response = self.post_stream()

        self.assertEqual(create.call_count, 2)
        self.assertEqual(sse_frames(response.text)[-1][1]["answer"], "Better")

    def test_blank_answer_every_attempt_emits_unusable_error(self):
        streams = [stream_chunks(" ") for _ in range(SETTINGS.max_attempts)]
        with (
            self.assertLogs(STREAM_LOGGER, level="WARNING"),
            patch.object(svc.client.chat.completions, "create", side_effect=streams),
        ):
            response = self.post_stream()

        self.assertIn("unusable response", sse_frames(response.text)[-1][1]["detail"])

    def test_missing_usage_emits_incomplete_error(self):
        with (
            self.assertLogs(STREAM_LOGGER, level="ERROR"),
            patch.object(
                svc.client.chat.completions,
                "create",
                return_value=stream_chunks("Hi", usage=False),
            ),
        ):
            response = self.post_stream()

        self.assertIn("incomplete response", sse_frames(response.text)[-1][1]["detail"])

    def test_stream_generator_reports_missing_client(self):
        from app.schemas.ask import AskRequest
        from app.services.llm.streaming import stream_answer

        with self.assertLogs(STREAM_LOGGER, level="ERROR"), patch.object(svc, "client", None):
            events = list(stream_answer(AskRequest(question="Hi", stream=True)))

        self.assertEqual(len(events), 1)
        self.assertIn("not configured", events[0])


if __name__ == "__main__":
    unittest.main()
