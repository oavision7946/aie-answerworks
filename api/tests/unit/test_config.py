import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import config


class TestConfig(unittest.TestCase):
    def tearDown(self):
        config.clear_config_cache()

    def test_config_dir_can_be_overridden_by_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.yaml").write_text("key: value\n")
            with patch.dict(os.environ, {"ANSWERWORKS_CONFIG_DIR": tmp}):
                config.clear_config_cache()
                self.assertEqual(config.config_dir(), Path(tmp))
                self.assertEqual(config.load_yaml("x.yaml"), {"key": "value"})

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
