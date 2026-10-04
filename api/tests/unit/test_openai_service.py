import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import APIConnectionError, APIStatusError

from app.services.llm import openai_service as svc
from tests.helpers import fake_usage


def status_error(code):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return APIStatusError("boom", response=httpx.Response(code, request=request), body=None)


class TestTransientErrors(unittest.TestCase):
    def test_classifies_errors(self):
        request = httpx.Request("POST", "https://x")
        self.assertTrue(svc.is_transient_openai_error(APIConnectionError(request=request)))
        for code in (408, 409, 429, 500, 503):
            with self.subTest(code=code):
                self.assertTrue(svc.is_transient_openai_error(status_error(code)))
        for code in (400, 401, 404):
            with self.subTest(code=code):
                self.assertFalse(svc.is_transient_openai_error(status_error(code)))
        self.assertFalse(svc.is_transient_openai_error(RuntimeError("x")))


class TestHelpers(unittest.TestCase):
    def test_retry_delay_doubles(self):
        base = svc.settings.retry_base_delay_seconds
        self.assertEqual([svc.retry_delay(i) for i in range(3)], [base, base * 2, base * 4])

    def test_usage_counts_reads_cached_tokens(self):
        usage = fake_usage(total=10, prompt=6, completion=4, cached=2)
        self.assertEqual(svc.usage_counts(usage), (6, 2, 4, 10))

    def test_usage_counts_tolerates_missing_fields(self):
        self.assertEqual(svc.usage_counts(SimpleNamespace()), (0, 0, 0, 0))
        self.assertEqual(
            svc.usage_counts(SimpleNamespace(prompt_tokens=3, completion_tokens=2)), (3, 0, 2, 5)
        )


class TestCreateChatCompletion(unittest.TestCase):
    def test_requires_configured_client(self):
        with patch.object(svc, "client", None), self.assertRaises(RuntimeError):
            svc.create_chat_completion(model="gpt-4o-mini", messages=[])

    def test_non_transient_error_is_not_retried(self):
        with (
            self.assertLogs(svc.logger, level="ERROR"),
            patch.object(
                svc.client.chat.completions, "create", side_effect=status_error(401)
            ) as create,
            patch.object(svc.time, "sleep") as sleep,
            self.assertRaises(APIStatusError),
        ):
            svc.create_chat_completion(model="gpt-4o-mini", messages=[])

        self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()


class TestLLMServiceError(unittest.TestCase):
    def test_carries_status_and_detail(self):
        error = svc.LLMServiceError(502, "nope")
        self.assertEqual((error.status_code, error.detail, str(error)), (502, "nope", "nope"))


if __name__ == "__main__":
    unittest.main()
