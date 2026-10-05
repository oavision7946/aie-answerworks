"""HTTP contract of /models and /ask, driven through the provider registry with fake providers."""

import time
import unittest
from unittest.mock import call, patch

from fastapi.testclient import TestClient

from app.core.settings import ModelConfig
from app.main import app
from app.services.llm.errors import IncompleteResponseError, ProviderError, TransientProviderError
from app.services.llm.registry import ProviderRegistry, get_registry
from tests.helpers import (
    REQUEST,
    completion,
    fake_provider,
    make_registry,
    sse_frames,
)

SERVICE_LOG = "app.services.llm.service"


class ApiTestCase(unittest.TestCase):
    def use(self, *providers, default=None):
        registry = make_registry(*providers, default=default)
        app.dependency_overrides[get_registry] = lambda: registry
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        return registry

    def setUp(self):
        self.provider = fake_provider()
        self.use(self.provider)


class TestModels(ApiTestCase):
    def test_lists_models_with_provider_and_defaults(self):
        self.use(fake_provider("a"), fake_provider("b"), default="b")

        body = self.client.get("/models").json()

        self.assertEqual(body["default_provider"], "b")
        self.assertEqual(body["default_model"], "priced")
        self.assertEqual(
            [(m["provider"], m["id"], m["label"]) for m in body["models"]],
            [
                ("a", "priced", "Priced"),
                ("a", "free", "Free"),
                ("b", "priced", "Priced"),
                ("b", "free", "Free"),
            ],
        )

    def test_no_providers_returns_empty_list(self):
        app.dependency_overrides[get_registry] = lambda: ProviderRegistry({}, "x", REQUEST)

        body = self.client.get("/models").json()

        self.assertEqual(body, {"default_provider": None, "default_model": None, "models": []})

    def test_get_ask_explains_post_usage(self):
        response = self.client.get("/ask")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers["allow"], "POST")
        self.assertIn("accepts POST", response.json()["detail"])

    def test_unknown_route_returns_json_404(self):
        self.assertEqual(self.client.get("/nope").status_code, 404)


class TestAsk(ApiTestCase):
    def ask(self, **payload):
        return self.client.post("/ask", json={"question": "Hi", **payload})

    def test_answer_reports_provider_model_tokens_and_cost(self):
        self.provider.script(completion("Hello", input_tokens=1_000_000, output_tokens=100_000))

        response = self.ask()

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["answer"], "Hello")
        self.assertEqual(body["provider"], "fake")
        self.assertEqual(body["model"], "priced")
        self.assertEqual(body["tokens_used"], 1_100_000)
        self.assertAlmostEqual(body["cost_usd"], 1.0 + 1.0)
        self.assertEqual(self.provider.calls[0][0], "priced")

    def test_default_scripted_echo(self):
        self.assertEqual(self.ask().json()["answer"], "Echo: Hi")

    def test_model_without_pricing_reports_null_cost(self):
        body = self.ask(model="free").json()

        self.assertEqual(body["model"], "free")
        self.assertIsNone(body["cost_usd"])

    def test_explicit_provider_and_bare_model_resolution(self):
        a, b = fake_provider("a"), fake_provider("b", default_model="free")
        self.use(a, b, default="a")

        self.assertEqual(self.ask(provider="b").json()["model"], "free")
        self.assertEqual(self.ask(provider="b", model="priced").json()["provider"], "b")
        self.assertEqual(self.ask(model="free").json()["provider"], "a")
        self.assertEqual(len(a.calls), 1)

    def test_bare_model_found_only_on_a_later_provider(self):
        a = fake_provider("a")
        b = fake_provider(
            "b",
            models=[ModelConfig(id="only-b", label="B")],
            default_model="only-b",
        )
        self.use(a, b, default="a")

        self.assertEqual(self.ask(model="only-b").json()["provider"], "b")

    def test_retries_transient_failure_with_exponential_backoff(self):
        self.provider.script(TransientProviderError("timeout"), "Recovered response")
        with patch.object(time, "sleep") as sleep:
            response = self.ask()

        self.assertEqual(response.json()["answer"], "Recovered response")
        self.assertEqual(len(self.provider.calls), 2)
        sleep.assert_called_once_with(REQUEST.retry_base_delay_seconds)

    def test_returns_503_and_logs_after_transient_retries_exhausted(self):
        self.provider.script(*[TransientProviderError("t") for _ in range(REQUEST.max_attempts)])
        with (
            self.assertLogs(SERVICE_LOG, level="WARNING") as captured,
            patch.object(time, "sleep") as sleep,
        ):
            response = self.ask()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The AI service is temporarily unavailable. Please try again shortly.",
        )
        self.assertEqual(len(self.provider.calls), REQUEST.max_attempts)
        self.assertEqual(sleep.call_args_list, [call(0.5), call(1.0)])
        self.assertTrue(any("failed after 3 attempts" in m for m in captured.output))

    def test_unexpected_provider_error_is_logged_but_not_exposed(self):
        self.provider.script(ProviderError("provider internals must stay private"))
        with self.assertLogs(SERVICE_LOG, level="ERROR") as captured:
            response = self.ask()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "The AI service could not complete your request. Please try again.",
        )
        self.assertNotIn("provider internals", response.text)
        self.assertTrue(any("provider internals must stay private" in m for m in captured.output))
        self.assertEqual(len(self.provider.calls), 1)

    def test_incomplete_provider_response_returns_502(self):
        self.provider.script(IncompleteResponseError("no usage"))
        with self.assertLogs(SERVICE_LOG, level="ERROR"):
            response = self.ask()

        self.assertEqual(response.status_code, 502)
        self.assertIn("incomplete response", response.json()["detail"])

    def test_rejects_invalid_requests_before_calling_a_provider(self):
        payloads = [
            {"question": "   "},
            {"question": "Hi", "model": "nope"},
            {"question": "Hi", "provider": "nope"},
            {"question": "Hi", "provider": "fake", "model": "nope"},
            {"question": "Hi", "surprise": 1},
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertLogs("app.api.errors", level="WARNING"):
                response = self.client.post("/ask", json=payload)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(
                response.json()["detail"],
                "Invalid request. Check the question and selected model, then try again.",
            )
        self.assertEqual(self.provider.calls, [])

    def test_forced_bad_first_response_is_rejected_without_retry(self):
        for field in ("force_bad_first_response", "force_bad"):
            with self.subTest(field=field), self.assertLogs(SERVICE_LOG, level="WARNING"):
                response = self.ask(**{field: True})
            self.assertEqual(response.status_code, 502)
            self.assertIn("unusable response", response.json()["detail"])
        self.assertEqual(len(self.provider.calls), 2)  # one call per request, no retry

    def test_blank_answer_is_retried_once_and_tokens_accumulate(self):
        self.provider.script(completion(""), completion("Recovered"))
        with self.assertLogs(SERVICE_LOG, level="WARNING"):
            body = self.ask().json()

        self.assertEqual(body["answer"], "Recovered")
        self.assertEqual(body["tokens_used"], 246)
        self.assertEqual(len(self.provider.calls), 2)

    def test_two_blank_answers_return_502(self):
        self.provider.script(completion(""), completion("   "))
        with self.assertLogs(SERVICE_LOG, level="WARNING"):
            response = self.ask()

        self.assertEqual(response.status_code, 502)

    def test_no_available_providers_returns_503(self):
        app.dependency_overrides[get_registry] = lambda: ProviderRegistry({}, "x", REQUEST)

        response = self.ask()

        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["detail"])

    def test_unexpected_error_returns_generic_500(self):
        client = TestClient(app, raise_server_exceptions=False)
        with (
            self.assertLogs("app.api.errors", level="ERROR"),
            patch("app.api.v1.ask.service.answer_question", side_effect=ValueError("secret")),
        ):
            response = client.post("/ask", json={"question": "Hi"})

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", response.text)


class TestAskStreaming(ApiTestCase):
    def post_stream(self, **extra):
        return self.client.post("/ask", json={"question": "Hi", "stream": True, **extra})

    def test_streams_deltas_then_completion_metadata(self):
        self.provider.script(completion("Hello there"))

        response = self.post_stream()

        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")
        frames = sse_frames(response.text)
        self.assertEqual([e for e, _ in frames], ["delta", "delta", "done"])
        self.assertEqual([p["content"] for _, p in frames[:2]], ["Hello ", "there"])
        done = frames[2][1]
        self.assertEqual(done["answer"], "Hello there")
        self.assertEqual(done["tokens_used"], 123)
        self.assertEqual((done["provider"], done["model"]), ("fake", "priced"))
        self.assertGreater(done["cost_usd"], 0)

    def test_unpriced_model_streams_null_cost(self):
        done = sse_frames(self.post_stream(model="free").text)[-1][1]

        self.assertIsNone(done["cost_usd"])

    def test_retries_transient_failure_before_first_delta(self):
        self.provider.script(TransientProviderError("t"), "Recovered")
        with patch.object(time, "sleep") as sleep:
            response = self.post_stream()

        self.assertEqual(sse_frames(response.text)[-1][1]["answer"], "Recovered")
        self.assertEqual(len(self.provider.calls), 2)
        sleep.assert_called_once_with(REQUEST.retry_base_delay_seconds)

    def test_safe_error_after_retries_exhausted(self):
        self.provider.script(*[TransientProviderError("t") for _ in range(REQUEST.max_attempts)])
        with (
            self.assertLogs(SERVICE_LOG, level="WARNING") as captured,
            patch.object(time, "sleep") as sleep,
        ):
            response = self.post_stream()

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", response.text)
        self.assertIn("temporarily unavailable", response.text)
        self.assertEqual(sleep.call_args_list, [call(0.5), call(1.0)])
        self.assertTrue(any("failed on attempt 3" in m for m in captured.output))

    def test_non_transient_error_is_reported_without_retry_or_leak(self):
        self.provider.script(ProviderError("private"))
        with self.assertLogs(SERVICE_LOG, level="ERROR"):
            response = self.post_stream()

        self.assertEqual(len(self.provider.calls), 1)
        self.assertIn("could not complete your request", response.text)
        self.assertNotIn("private", response.text)

    def test_forced_bad_first_response_emits_error_without_deltas(self):
        with self.assertLogs(SERVICE_LOG, level="WARNING"):
            response = self.post_stream(force_bad_first_response=True)

        self.assertEqual([e for e, _ in sse_frames(response.text)], ["error"])

    def test_blank_answer_is_retried_then_succeeds(self):
        self.provider.script(completion(" "), completion("Better"))
        with self.assertLogs(SERVICE_LOG, level="WARNING"):
            response = self.post_stream()

        self.assertEqual(sse_frames(response.text)[-1][1]["answer"], "Better")

    def test_blank_answers_on_every_attempt_emit_unusable_error(self):
        self.provider.script(*[completion(" ") for _ in range(REQUEST.max_attempts)])
        with self.assertLogs(SERVICE_LOG, level="WARNING"):
            response = self.post_stream()

        self.assertIn("unusable response", sse_frames(response.text)[-1][1]["detail"])

    def test_missing_usage_emits_incomplete_error(self):
        from app.services.llm.base import StreamEnd, TextDelta

        self.provider.stream = lambda model, messages: iter([TextDelta("Hi"), StreamEnd(None)])
        with self.assertLogs(SERVICE_LOG, level="ERROR"):
            response = self.post_stream()

        self.assertIn("incomplete response", sse_frames(response.text)[-1][1]["detail"])

    def test_resolution_errors_are_plain_http_errors(self):
        self.assertEqual(self.post_stream(model="nope").status_code, 422)
        app.dependency_overrides[get_registry] = lambda: ProviderRegistry({}, "x", REQUEST)
        self.assertEqual(self.post_stream().status_code, 503)


if __name__ == "__main__":
    unittest.main()
