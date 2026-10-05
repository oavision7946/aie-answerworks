"""Real SDK adapters against an injected mock transport: no network, real SDK parsing."""

import json
import unittest

import httpx2

from app.core.settings import ModelConfig, ProviderConfig
from app.services.llm.base import ChatMessage, StreamEnd, TextDelta, Usage
from app.services.llm.errors import IncompleteResponseError, ProviderError, TransientProviderError
from app.services.llm.providers.anthropic_provider import AnthropicProvider
from app.services.llm.providers.openai_provider import LocalProvider, OpenAIProvider
from tests.helpers import REQUEST, sse_body


class Upstream:
    """Stands in for the provider's HTTP API: records requests, replies as scripted."""

    def __init__(self):
        self.requests = []
        self._reply = httpx2.Response(200, json={})

    def reply(self, status=200, json_body=None, text=None, error=None):
        if error is not None:
            self._reply = error
        elif text is not None:
            self._reply = httpx2.Response(
                status, text=text, headers={"content-type": "text/event-stream"}
            )
        else:
            self._reply = httpx2.Response(status, json=json_body)
        return self

    def __call__(self, request):
        self.requests.append(request)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply

    @property
    def last(self):
        return self.requests[-1]

    def client(self):
        return httpx2.Client(transport=httpx2.MockTransport(self))


OPENAI_URL = "https://api.openai.com/v1/chat/completions"
LOCAL_URL = "http://localhost:11434/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MESSAGES = [ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")]


def config(type_, **extra):
    return ProviderConfig(
        type=type_,
        enabled=True,
        default_model="m",
        models=[ModelConfig(id="m", label="M")],
        **extra,
    )


def openai_completion(content="Hello", usage=True, **kw):
    body = {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }
    if usage:
        body["usage"] = {
            "prompt_tokens": 100,
            "completion_tokens": 23,
            "total_tokens": 123,
            "prompt_tokens_details": {"cached_tokens": 40},
        }
    body.update(kw)
    return body


def openai_chunks(*texts, usage=True):
    def chunk(delta, usage_=None, choices=True):
        body = {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}] if choices else [],
        }
        if usage_:
            body["usage"] = usage_
        return "data: " + json.dumps(body) + "\n\n"

    out = [chunk({"role": "assistant"})] + [chunk({"content": t}) for t in texts]
    if usage:
        out.append(
            chunk(
                {}, {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}, choices=False
            )
        )
    return "".join(out) + "data: [DONE]\n\n"


class TestOpenAIProvider(unittest.TestCase):
    def setUp(self):
        self.up = Upstream()
        self.provider = OpenAIProvider(
            "openai",
            config("openai", api_key_env="K"),
            REQUEST,
            "sk-test",
            http_client=self.up.client(),
        )

    def test_complete_maps_text_and_usage(self):
        self.up.reply(json_body=openai_completion("Hello"))

        result = self.provider.complete("m", MESSAGES)

        self.assertEqual(result.text, "Hello")
        self.assertEqual(
            result.usage, Usage(input_tokens=100, cached_input_tokens=40, output_tokens=23)
        )
        self.assertEqual(str(self.up.last.url), OPENAI_URL)
        sent = json.loads(self.up.last.content)
        self.assertEqual(sent["model"], "m")
        self.assertEqual(sent["messages"][0], {"role": "system", "content": "Be brief."})
        self.assertEqual(self.up.last.headers["authorization"], "Bearer sk-test")

    def test_error_statuses_are_classified(self):
        cases = {
            429: TransientProviderError,
            500: TransientProviderError,
            503: TransientProviderError,
            408: TransientProviderError,
            401: ProviderError,
            400: ProviderError,
        }
        for status, expected in cases.items():
            self.up.reply(status, {"error": {"message": "x"}})
            with self.subTest(status=status), self.assertRaises(ProviderError) as raised:
                self.provider.complete("m", MESSAGES)
            self.assertIs(type(raised.exception), expected)

    def test_connection_errors_and_timeouts_are_transient(self):
        for error in (httpx2.ConnectError("down"), httpx2.ReadTimeout("slow")):
            self.up.reply(error=error)
            with (
                self.subTest(error=type(error).__name__),
                self.assertRaises(TransientProviderError),
            ):
                self.provider.complete("m", MESSAGES)

    def test_incomplete_payloads_raise_incomplete(self):
        for body in (
            openai_completion(choices=[]),
            openai_completion(content=None),
            openai_completion(usage=False),
        ):
            self.up.reply(json_body=body)
            with self.subTest(), self.assertRaises(IncompleteResponseError):
                self.provider.complete("m", MESSAGES)

    def test_stream_yields_deltas_then_usage(self):
        self.up.reply(text=openai_chunks("Hel", "lo"))

        events = list(self.provider.stream("m", MESSAGES))

        self.assertEqual([e.content for e in events if isinstance(e, TextDelta)], ["Hel", "lo"])
        self.assertEqual(events[-1], StreamEnd(Usage(10, 0, 2)))
        sent = json.loads(self.up.last.content)
        self.assertEqual((sent["stream"], sent["stream_options"]), (True, {"include_usage": True}))

    def test_stream_without_usage_ends_with_none(self):
        self.up.reply(text=openai_chunks("x", usage=False))

        self.assertEqual(list(self.provider.stream("m", MESSAGES))[-1], StreamEnd(None))

    def test_stream_errors_are_translated(self):
        self.up.reply(429, {"error": {"message": "slow down"}})

        with self.assertRaises(TransientProviderError):
            list(self.provider.stream("m", MESSAGES))

    def test_non_sdk_exceptions_become_provider_errors(self):
        from app.services.llm.providers.openai_provider import translate_error

        self.assertIs(type(translate_error(ValueError("odd"))), ProviderError)


class TestLocalProvider(unittest.TestCase):
    def setUp(self):
        self.up = Upstream()
        self.config = config("openai_compatible", base_url="http://localhost:11434/v1")
        self.provider = LocalProvider(
            "local", self.config, REQUEST, None, http_client=self.up.client()
        )

    def test_works_without_key_and_without_usage(self):
        self.up.reply(json_body=openai_completion("Hi", usage=False))

        result = self.provider.complete("m", MESSAGES)

        self.assertEqual((result.text, result.usage), ("Hi", Usage()))
        self.assertEqual(str(self.up.last.url), LOCAL_URL)
        self.assertEqual(self.up.last.headers["authorization"], "Bearer not-needed")

    def test_stream_without_usage_reports_zero_usage(self):
        self.up.reply(text=openai_chunks("ok", usage=False))

        self.assertEqual(list(self.provider.stream("m", MESSAGES))[-1], StreamEnd(Usage()))

    def test_uses_the_configured_key_when_given(self):
        provider = LocalProvider(
            "local", self.config, REQUEST, "secret", http_client=self.up.client()
        )
        self.up.reply(json_body=openai_completion())

        provider.complete("m", MESSAGES)

        self.assertEqual(self.up.last.headers["authorization"], "Bearer secret")


def anthropic_message(text="Hello", **usage):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": [{"type": "text", "text": text}] if text is not None else [],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5, **usage},
    }


def anthropic_stream(*texts):
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    **anthropic_message(None),
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 4, "output_tokens": 1},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
    ]
    events += [
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}},
        )
        for t in texts
    ]
    events += [
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 7},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return sse_body(*events)


class TestAnthropicProvider(unittest.TestCase):
    def setUp(self):
        self.up = Upstream()
        self.provider = AnthropicProvider(
            "anthropic",
            config("anthropic", api_key_env="K"),
            REQUEST,
            "sk-ant",
            http_client=self.up.client(),
        )

    def test_complete_sends_system_separately_and_folds_cache_into_usage(self):
        self.up.reply(
            json_body=anthropic_message(
                "Hello", cache_read_input_tokens=30, cache_creation_input_tokens=5
            )
        )

        result = self.provider.complete("m", MESSAGES)

        self.assertEqual(result.text, "Hello")
        self.assertEqual(
            result.usage, Usage(input_tokens=45, cached_input_tokens=30, output_tokens=5)
        )
        sent = json.loads(self.up.last.content)
        self.assertEqual(str(self.up.last.url), ANTHROPIC_URL)
        self.assertEqual(sent["system"], "Be brief.")
        self.assertEqual(sent["messages"], [{"role": "user", "content": "Hi"}])
        self.assertEqual(sent["max_tokens"], REQUEST.max_output_tokens)
        self.assertEqual(self.up.last.headers["x-api-key"], "sk-ant")

    def test_no_system_field_when_there_is_no_system_message(self):
        self.up.reply(json_body=anthropic_message())

        self.provider.complete("m", [ChatMessage("user", "Hi")])

        self.assertNotIn("system", json.loads(self.up.last.content))

    def test_empty_content_yields_empty_text(self):
        self.up.reply(json_body=anthropic_message(None))

        self.assertEqual(self.provider.complete("m", MESSAGES).text, "")

    def test_error_statuses_are_classified(self):
        cases = {
            429: TransientProviderError,
            500: TransientProviderError,
            529: TransientProviderError,
            401: ProviderError,
            400: ProviderError,
        }
        for status, expected in cases.items():
            self.up.reply(status, {"type": "error", "error": {"type": "x", "message": "m"}})
            with self.subTest(status=status), self.assertRaises(ProviderError) as raised:
                self.provider.complete("m", MESSAGES)
            self.assertIs(type(raised.exception), expected)

    def test_connection_errors_are_transient(self):
        self.up.reply(error=httpx2.ConnectError("down"))

        with self.assertRaises(TransientProviderError):
            self.provider.complete("m", MESSAGES)

    def test_stream_yields_deltas_then_final_usage(self):
        self.up.reply(text=anthropic_stream("Hel", "lo"))

        events = list(self.provider.stream("m", MESSAGES))

        self.assertEqual([e.content for e in events if isinstance(e, TextDelta)], ["Hel", "lo"])
        self.assertEqual(
            events[-1], StreamEnd(Usage(input_tokens=14, cached_input_tokens=4, output_tokens=7))
        )

    def test_stream_errors_are_translated(self):
        self.up.reply(
            529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
        )

        with self.assertRaises(TransientProviderError):
            list(self.provider.stream("m", MESSAGES))

    def test_non_sdk_exceptions_become_provider_errors(self):
        from app.services.llm.providers.anthropic_provider import translate_error

        self.assertIs(type(translate_error(KeyError("x"))), ProviderError)


if __name__ == "__main__":
    unittest.main()
