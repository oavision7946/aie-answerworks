import logging
import time
import unittest
from unittest.mock import patch

from app.services.llm.base import ChatMessage, StreamEnd, TextDelta, Usage
from app.services.llm.errors import ProviderError, TransientProviderError
from app.services.llm.retry import call_with_retry, retry_delay
from tests.helpers import REQUEST, completion, fake_provider

LOGGER = logging.getLogger("test.retry")


class TestRetry(unittest.TestCase):
    def test_delay_doubles_each_attempt(self):
        self.assertEqual([retry_delay(REQUEST, i) for i in range(3)], [0.5, 1.0, 2.0])

    def test_returns_first_success_without_sleeping(self):
        with patch.object(time, "sleep") as sleep:
            self.assertEqual(call_with_retry(lambda: 7, REQUEST, LOGGER, "x"), 7)
        sleep.assert_not_called()

    def test_retries_transient_then_succeeds(self):
        outcomes = [TransientProviderError("t"), TransientProviderError("t"), "ok"]

        def call():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with self.assertLogs(LOGGER, level="WARNING"), patch.object(time, "sleep") as sleep:
            self.assertEqual(call_with_retry(call, REQUEST, LOGGER, "x"), "ok")
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.5, 1.0])

    def test_gives_up_after_max_attempts(self):
        calls = []

        def call():
            calls.append(1)
            raise TransientProviderError("t")

        with (
            self.assertLogs(LOGGER),
            patch.object(time, "sleep"),
            self.assertRaises(TransientProviderError),
        ):
            call_with_retry(call, REQUEST, LOGGER, "x")
        self.assertEqual(len(calls), REQUEST.max_attempts)

    def test_does_not_retry_other_errors(self):
        calls = []

        def call():
            calls.append(1)
            raise ProviderError("bad")

        with (
            self.assertLogs(LOGGER),
            patch.object(time, "sleep") as sleep,
            self.assertRaises(ProviderError),
        ):
            call_with_retry(call, REQUEST, LOGGER, "x")
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()


class TestFakeProvider(unittest.TestCase):
    def setUp(self):
        self.provider = fake_provider()
        self.messages = [ChatMessage("system", "be brief"), ChatMessage("user", "hello world")]

    def test_echoes_last_user_message_with_word_count_usage(self):
        result = self.provider.complete("priced", self.messages)

        self.assertEqual(result.text, "Echo: hello world")
        self.assertEqual(result.usage, Usage(input_tokens=4, output_tokens=3))

    def test_echo_without_user_message(self):
        self.assertEqual(self.provider.complete("priced", []).text, "Echo: ")

    def test_scripted_steps_are_consumed_in_order(self):
        self.provider.script("one", completion("two"), ProviderError("boom"))

        self.assertEqual(self.provider.complete("m", self.messages).text, "one")
        self.assertEqual(self.provider.complete("m", self.messages).text, "two")
        with self.assertRaises(ProviderError):
            self.provider.complete("m", self.messages)
        self.assertEqual(self.provider.complete("m", self.messages).text, "Echo: hello world")

    def test_stream_yields_word_deltas_then_usage(self):
        events = list(self.provider.script("a b c").stream("m", self.messages))

        self.assertEqual([e.content for e in events[:-1]], ["a ", "b ", "c"])
        self.assertIsInstance(events[0], TextDelta)
        self.assertIsInstance(events[-1], StreamEnd)
        self.assertEqual(events[-1].usage.output_tokens, 3)

    def test_models_and_default(self):
        self.assertEqual([m.id for m in self.provider.list_models()], ["priced", "free"])
        self.assertEqual(self.provider.default_model.id, "priced")
        with self.assertRaises(KeyError):
            self.provider.model("ghost")


if __name__ == "__main__":
    unittest.main()
