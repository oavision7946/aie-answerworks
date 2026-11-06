import importlib
import os
import unittest
from unittest.mock import patch

from app import config


class TestTracingSettings(unittest.TestCase):
    def reloaded(self, **env):
        with patch.dict(os.environ, env):
            return importlib.reload(config)

    def tearDown(self):
        importlib.reload(config)

    def test_off_by_default_and_for_empty_values(self):
        with patch.dict(os.environ):
            os.environ.pop("TRACING_ENABLED", None)
            self.assertFalse(importlib.reload(config).TRACING_ENABLED)
        for value in ("", "no"):
            with self.subTest(value=value):
                self.assertFalse(self.reloaded(TRACING_ENABLED=value).TRACING_ENABLED)

    def test_enabled_by_common_truthy_words(self):
        for word in ("1", "true", "TRUE", " yes "):
            with self.subTest(word=word):
                self.assertTrue(self.reloaded(TRACING_ENABLED=word).TRACING_ENABLED)

    def test_an_empty_endpoint_means_the_default_and_a_trailing_slash_is_dropped(self):
        self.assertEqual(self.reloaded(OTLP_ENDPOINT="").OTLP_ENDPOINT, "http://localhost:4318")
        self.assertEqual(
            self.reloaded(OTLP_ENDPOINT="http://collector:4318/").OTLP_ENDPOINT,
            "http://collector:4318",
        )


if __name__ == "__main__":
    unittest.main()
