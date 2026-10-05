import json
import unittest

import httpx
import respx

from app import config
from app.clients import api_client

BASE = config.API_BASE_URL.rstrip("/")
GPT = api_client.ModelInfo(provider="openai", id="gpt-4o", label="GPT-4o")
BARE = api_client.ModelInfo(provider="", id="gpt-4o-mini", label="gpt-4o-mini")
RESULT = {
    "answer": "Block is healthy",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "tokens_used": 123,
    "latency_ms": 5,
    "cost_usd": 0.0001,
}


def sse(*events):
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


class TestModelInfo(unittest.TestCase):
    def test_key_and_display_include_provider_when_known(self):
        self.assertEqual((GPT.key, GPT.display), ("openai/gpt-4o", "GPT-4o · openai"))
        self.assertEqual((BARE.key, BARE.display), ("gpt-4o-mini", "gpt-4o-mini"))


class TestGetModels(unittest.TestCase):
    @respx.mock
    def test_returns_models_from_api(self):
        respx.get(f"{BASE}/models").respond(
            json={
                "default_provider": "openai",
                "default_model": "gpt-4o",
                "models": [{"provider": "openai", "id": "gpt-4o", "label": "GPT-4o"}],
            }
        )

        models = api_client.get_models()

        self.assertEqual(models.models, [GPT])
        self.assertEqual((models.default_provider, models.default_model), ("openai", "gpt-4o"))

    @respx.mock
    def test_falls_back_when_api_is_down(self):
        respx.get(f"{BASE}/models").mock(side_effect=httpx.ConnectError("down"))

        self.assertEqual(api_client.get_models().models, [BARE])

    @respx.mock
    def test_falls_back_on_http_error_and_bad_payload(self):
        route = respx.get(f"{BASE}/models")
        for response in (
            httpx.Response(500),
            httpx.Response(200, json={"unexpected": True}),
            httpx.Response(200, text="not json"),
        ):
            with self.subTest(status=response.status_code):
                route.mock(return_value=response)
                self.assertEqual(api_client.get_models().models, [BARE])


class TestCallApi(unittest.TestCase):
    @respx.mock
    def test_posts_question_and_parses_response(self):
        route = respx.post(f"{BASE}/ask").respond(json=RESULT)

        result = api_client.call_api("Why?", GPT, True)

        self.assertEqual(result.answer, "Block is healthy")
        self.assertEqual(result.tokens_used, 123)
        self.assertEqual(
            json.loads(route.calls.last.request.content),
            {
                "question": "Why?",
                "model": "gpt-4o",
                "provider": "openai",
                "force_bad_first_response": True,
            },
        )

    @respx.mock
    def test_provider_is_omitted_for_the_fallback_model(self):
        route = respx.post(f"{BASE}/ask").respond(json=RESULT)

        api_client.call_api("Why?", BARE, False)

        self.assertNotIn("provider", json.loads(route.calls.last.request.content))

    @respx.mock
    def test_null_cost_is_accepted(self):
        respx.post(f"{BASE}/ask").respond(json={**RESULT, "cost_usd": None})

        self.assertIsNone(api_client.call_api("Why?", GPT, False).cost_usd)

    @respx.mock
    def test_error_response_surfaces_api_detail(self):
        respx.post(f"{BASE}/ask").respond(502, json={"detail": "unusable"})

        with self.assertRaisesRegex(RuntimeError, r"API error \(502\): unusable"):
            api_client.call_api("Why?", GPT, False)

    @respx.mock
    def test_error_response_without_json_uses_body_text(self):
        respx.post(f"{BASE}/ask").respond(500, text="plain failure")

        with self.assertRaisesRegex(RuntimeError, "plain failure"):
            api_client.call_api("Why?", GPT, False)

    @respx.mock
    def test_unexpected_payload_raises_runtime_error(self):
        respx.post(f"{BASE}/ask").respond(json={"nope": 1})

        with self.assertRaisesRegex(RuntimeError, "unexpected response"):
            api_client.call_api("Why?", GPT, False)


class TestCallStreamingApi(unittest.TestCase):
    @respx.mock
    def test_renders_deltas_and_returns_final_result(self):
        route = respx.post(f"{BASE}/ask").respond(
            200,
            text=sse(
                ("delta", {"content": "Block "}),
                ("delta", {"content": "is healthy"}),
                ("done", RESULT),
            ),
        )
        rendered = []

        result = api_client.call_streaming_api("Why?", GPT, False, rendered.append)

        self.assertEqual(rendered, ["Block ", "Block is healthy"])
        self.assertEqual(result.model, "gpt-4o-mini")
        sent = json.loads(route.calls.last.request.content)
        self.assertTrue(sent["stream"])
        self.assertEqual(sent["provider"], "openai")

    @respx.mock
    def test_error_event_raises(self):
        respx.post(f"{BASE}/ask").respond(200, text=sse(("error", {"detail": "model down"})))

        with self.assertRaisesRegex(RuntimeError, "model down"):
            api_client.call_streaming_api("Why?", GPT, False, lambda _: None)

    @respx.mock
    def test_error_event_without_detail_uses_default_message(self):
        respx.post(f"{BASE}/ask").respond(200, text=sse(("error", {})))

        with self.assertRaisesRegex(RuntimeError, "streaming request failed"):
            api_client.call_streaming_api("Why?", GPT, False, lambda _: None)

    @respx.mock
    def test_http_error_status_raises_with_detail(self):
        respx.post(f"{BASE}/ask").respond(422, json={"detail": "Invalid request."})

        with self.assertRaisesRegex(RuntimeError, r"API error \(422\): Invalid request."):
            api_client.call_streaming_api("Why?", GPT, False, lambda _: None)

    @respx.mock
    def test_http_error_status_without_json_uses_body_text(self):
        respx.post(f"{BASE}/ask").respond(500, text="gateway exploded")

        with self.assertRaisesRegex(RuntimeError, "gateway exploded"):
            api_client.call_streaming_api("Why?", GPT, False, lambda _: None)

    @respx.mock
    def test_stream_without_done_event_raises(self):
        respx.post(f"{BASE}/ask").respond(200, text=sse(("delta", {"content": "partial"})))

        with self.assertRaisesRegex(RuntimeError, "ended before completion"):
            api_client.call_streaming_api("Why?", GPT, False, lambda _: None)

    @respx.mock
    def test_malformed_stream_payload_raises(self):
        respx.post(f"{BASE}/ask").respond(200, text="event: delta\ndata: {not json\n\n")

        with self.assertRaisesRegex(RuntimeError, "unexpected streaming response"):
            api_client.call_streaming_api("Why?", GPT, False, lambda _: None)


if __name__ == "__main__":
    unittest.main()
