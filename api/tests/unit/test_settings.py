import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from pydantic import ValidationError

from app.core import config, settings
from app.core.settings import (
    ChunkingConfig,
    CorporaConfig,
    ProvidersConfig,
    load_settings,
)

CONFIG = config.REPO_ROOT / "config"


def providers_data():
    return copy.deepcopy(yaml.safe_load((CONFIG / "providers.yaml").read_text()))


class TestRepoConfigIsValid(unittest.TestCase):
    def setUp(self):
        settings.reset_settings()

    def tearDown(self):
        settings.reset_settings()

    def test_shipped_yaml_loads_into_settings(self):
        loaded = settings.get_settings()

        self.assertEqual(loaded.app.app.name, "AnswerWorks")
        self.assertEqual(loaded.providers.default_provider, "anthropic")
        self.assertEqual(list(loaded.providers.enabled), ["anthropic"])
        self.assertEqual(loaded.rag.chunking.size, 800)
        self.assertEqual(loaded.rag.retrieval.top_k, 5)
        self.assertEqual(loaded.corpora.corpora, [])
        self.assertEqual(loaded.app.auth.access_token_ttl_minutes, 15)

    def test_settings_are_cached(self):
        self.assertIs(settings.get_settings(), settings.get_settings())

    def test_env_settings_come_from_environment(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///x.db", "JWT_SECRET": "s3cret"}):
            env = settings.EnvSettings()

        self.assertEqual(env.database_url, "sqlite:///x.db")
        self.assertEqual(env.jwt_secret, "s3cret")

    def test_missing_provider_keys_lists_enabled_providers_without_a_key(self):
        loaded = settings.get_settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assertEqual(loaded.missing_provider_keys(), {"anthropic": "ANTHROPIC_API_KEY"})
            os.environ["ANTHROPIC_API_KEY"] = "k"
            self.assertEqual(loaded.missing_provider_keys(), {})


class TestProvidersValidation(unittest.TestCase):
    def test_valid(self):
        self.assertIn("anthropic", ProvidersConfig.model_validate(providers_data()).providers)

    def test_default_provider_must_exist(self):
        data = providers_data()
        data["default_provider"] = "nope"
        with self.assertRaisesRegex(ValidationError, "not defined"):
            ProvidersConfig.model_validate(data)

    def test_default_provider_must_be_enabled(self):
        data = providers_data()
        data["default_provider"] = "openai"
        with self.assertRaisesRegex(ValidationError, "not enabled"):
            ProvidersConfig.model_validate(data)

    def test_default_model_must_be_listed(self):
        data = providers_data()
        data["providers"]["anthropic"]["default_model"] = "ghost"
        with self.assertRaisesRegex(ValidationError, "not in models"):
            ProvidersConfig.model_validate(data)

    def test_unknown_keys_and_types_are_rejected(self):
        data = providers_data()
        data["providers"]["anthropic"]["typo_field"] = 1
        with self.assertRaises(ValidationError):
            ProvidersConfig.model_validate(data)
        data = providers_data()
        data["providers"]["anthropic"]["type"] = "mystery"
        with self.assertRaises(ValidationError):
            ProvidersConfig.model_validate(data)


class TestOtherValidation(unittest.TestCase):
    def test_chunk_overlap_must_be_smaller_than_size(self):
        ChunkingConfig(size=10, overlap=9)
        with self.assertRaisesRegex(ValidationError, "overlap"):
            ChunkingConfig(size=10, overlap=10)

    def test_corpus_names_must_be_unique(self):
        corpus = {"name": "a", "source": {"type": "filesystem", "path": "./a"}}
        CorporaConfig.model_validate({"corpora": [corpus]})
        with self.assertRaisesRegex(ValidationError, "unique"):
            CorporaConfig.model_validate({"corpora": [corpus, corpus]})

    def test_embeddings_provider_must_exist_in_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("app.yaml", "providers.yaml", "rag.yaml", "corpora.yaml"):
                (Path(tmp) / name).write_text((CONFIG / name).read_text())
            rag = yaml.safe_load((Path(tmp) / "rag.yaml").read_text())
            rag["embeddings"]["provider"] = "ghost"
            (Path(tmp) / "rag.yaml").write_text(yaml.safe_dump(rag))

            with patch.dict(os.environ, {"ANSWERWORKS_CONFIG_DIR": tmp}):
                config.clear_config_cache()
                try:
                    with self.assertRaisesRegex(ValidationError, "embeddings.provider"):
                        load_settings()
                finally:
                    config.clear_config_cache()


if __name__ == "__main__":
    unittest.main()
