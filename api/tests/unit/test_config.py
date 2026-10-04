import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import config


class TestConfig(unittest.TestCase):
    def tearDown(self):
        config.clear_config_cache()

    def test_llm_settings_come_from_app_yaml(self):
        settings = config.get_llm_settings()

        self.assertEqual(settings.default_model, "gpt-4o-mini")
        self.assertEqual(settings.timeout_seconds, 20.0)
        self.assertEqual(settings.max_attempts, 3)
        self.assertEqual(settings.retry_base_delay_seconds, 0.5)

    def test_model_costs_come_from_model_costs_yaml(self):
        costs = config.load_model_costs()

        self.assertEqual(
            costs["gpt-4o-mini"],
            {"input_tokens": 0.15, "cached_input": 0.075, "output_tokens": 0.6},
        )
        self.assertIn(config.get_llm_settings().default_model, costs)

    def test_config_dir_can_be_overridden_by_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "model_costs.yaml").write_text(
                "models:\n  only-model: {input_tokens: 1, cached_input: 1, output_tokens: 1}\n"
            )
            with patch.dict(os.environ, {"ANSWERWORKS_CONFIG_DIR": tmp}):
                config.clear_config_cache()
                self.assertEqual(config.config_dir(), Path(tmp))
                self.assertEqual(list(config.load_model_costs()), ["only-model"])

    def test_empty_yaml_file_loads_as_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty.yaml").write_text("")
            with patch.dict(os.environ, {"ANSWERWORKS_CONFIG_DIR": tmp}):
                self.assertEqual(config.load_yaml("empty.yaml"), {})

    def test_default_config_dir_is_repo_config(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANSWERWORKS_CONFIG_DIR", None)
            self.assertEqual(config.config_dir(), config.REPO_ROOT / "config")
            self.assertTrue((config.REPO_ROOT / "config" / "app.yaml").is_file())

    def test_load_env_does_not_override_real_environment(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "from-env"}):
            config.load_env()
            self.assertEqual(os.environ["OPENAI_API_KEY"], "from-env")


if __name__ == "__main__":
    unittest.main()
