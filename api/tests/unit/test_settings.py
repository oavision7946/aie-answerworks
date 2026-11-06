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
    MonitoringConfig,
    Pricing,
    ProvidersConfig,
    TracingConfig,
    load_monitoring,
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
        self.assertEqual(list(loaded.providers.enabled), ["anthropic", "openai"])
        self.assertEqual(loaded.providers.request.max_attempts, 3)
        gpt = next(m for m in loaded.providers.providers["openai"].models if m.id == "gpt-4o-mini")
        self.assertEqual(gpt.pricing.input, 0.15)
        self.assertEqual(gpt.pricing.cached_input_price, 0.075)
        self.assertEqual(loaded.rag.default_embedding, "openai-small")
        self.assertEqual(loaded.rag.embedding_models["openai-large"].dimensions, 3072)
        self.assertEqual(loaded.rag.chunking_strategies[loaded.rag.default_chunking].size, 800)
        self.assertEqual(
            {c.method for c in loaded.rag.chunking_strategies.values()},
            {"fixed", "recursive", "paragraph", "sentence"},
        )
        self.assertEqual(loaded.rag.retrieval.top_k, 5)
        self.assertEqual(loaded.corpora.corpora, [])
        self.assertEqual(loaded.app.auth.access_token_ttl_minutes, 15)
        self.assertEqual(loaded.app.chat.history_messages, 20)

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
            os.environ.pop("OPENAI_API_KEY", None)
            self.assertEqual(
                loaded.missing_provider_keys(),
                {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"},
            )
            os.environ["ANTHROPIC_API_KEY"] = "k"
            os.environ["OPENAI_API_KEY"] = "k"
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
        data["default_provider"] = "local"
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

    def test_default_model_must_be_unique_and_keys_required(self):
        data = providers_data()
        data["providers"]["openai"]["models"].append(dict(data["providers"]["openai"]["models"][0]))
        with self.assertRaisesRegex(ValidationError, "unique"):
            ProvidersConfig.model_validate(data)

        data = providers_data()
        del data["providers"]["anthropic"]["api_key_env"]
        with self.assertRaisesRegex(ValidationError, "require api_key_env"):
            ProvidersConfig.model_validate(data)

        data = providers_data()
        data["providers"]["openai"]["workspace_id_env"] = "SOME_ID"
        with self.assertRaisesRegex(ValidationError, "only supported for anthropic"):
            ProvidersConfig.model_validate(data)

        data = providers_data()
        del data["providers"]["local"]["base_url"]
        with self.assertRaisesRegex(ValidationError, "require base_url"):
            ProvidersConfig.model_validate(data)

    def test_request_limits_are_validated(self):
        for key, value in (("max_attempts", 0), ("timeout_seconds", 0), ("max_output_tokens", 0)):
            data = providers_data()
            data["request"][key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                ProvidersConfig.model_validate(data)

    def test_pricing_cannot_be_negative_and_cached_defaults_to_input(self):
        pricing = Pricing(input=2.0, output=3.0)
        self.assertEqual(pricing.cached_input_price, 2.0)
        with self.assertRaises(ValidationError):
            Pricing(input=-1, output=1)


class TestOtherValidation(unittest.TestCase):
    def test_chunk_overlap_must_be_smaller_than_size(self):
        ChunkingConfig(method="fixed", size=10, overlap=9)
        with self.assertRaisesRegex(ValidationError, "overlap"):
            ChunkingConfig(method="fixed", size=10, overlap=10)

    def test_corpus_names_must_be_unique(self):
        corpus = {"name": "a", "source": {"type": "filesystem", "path": "./a"}}
        CorporaConfig.model_validate({"corpora": [corpus]})
        with self.assertRaisesRegex(ValidationError, "unique"):
            CorporaConfig.model_validate({"corpora": [corpus, corpus]})

    def test_url_sources_need_http_addresses_and_refresh_must_be_positive(self):
        def corpus(**fields):
            return {"corpora": [{"name": "w", "source": {"type": "url", **fields}}]}

        ok = CorporaConfig.model_validate(corpus(urls=["https://a.test/x", "http://b.test"]))
        self.assertEqual(ok.corpora[0].source.urls[1], "http://b.test")
        for urls in (["ftp://a.test/x"], ["file:///etc/passwd"], ["https://"], ["a.test/x"], []):
            with self.subTest(urls=urls), self.assertRaises(ValidationError):
                CorporaConfig.model_validate(corpus(urls=urls))
        with self.assertRaises(ValidationError):
            CorporaConfig.model_validate(corpus(urls=["https://a.test"], path="x"))

        base = {"name": "a", "source": {"type": "filesystem", "path": "./a"}}
        self.assertIsNone(
            CorporaConfig.model_validate({"corpora": [base]}).corpora[0].refresh_minutes
        )
        self.assertEqual(
            CorporaConfig.model_validate({"corpora": [{**base, "refresh_minutes": 15}]})
            .corpora[0]
            .refresh_minutes,
            15,
        )
        with self.assertRaises(ValidationError):
            CorporaConfig.model_validate({"corpora": [{**base, "refresh_minutes": 0}]})

    def load_with(self, edit):
        """load_settings() against a copy of the shipped config with `edit(rag)` applied."""
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("app.yaml", "providers.yaml", "rag.yaml", "corpora.yaml"):
                (Path(tmp) / name).write_text((CONFIG / name).read_text())
            rag = yaml.safe_load((Path(tmp) / "rag.yaml").read_text())
            edit(rag)
            (Path(tmp) / "rag.yaml").write_text(yaml.safe_dump(rag))

            with patch.dict(os.environ, {"ANSWERWORKS_CONFIG_DIR": tmp}):
                config.clear_config_cache()
                try:
                    return load_settings()
                finally:
                    config.clear_config_cache()

    def test_embedding_provider_must_exist_in_providers(self):
        def edit(rag):
            rag["embedding_models"]["openai-small"]["provider"] = "ghost"

        with self.assertRaisesRegex(ValidationError, "provider 'ghost'"):
            self.load_with(edit)

    def test_anthropic_cannot_create_embeddings(self):
        def edit(rag):
            rag["embedding_models"]["openai-small"]["provider"] = "anthropic"

        with self.assertRaisesRegex(ValidationError, "cannot create embeddings"):
            self.load_with(edit)

    def test_default_embedding_and_chunking_must_be_defined(self):
        with self.assertRaisesRegex(ValidationError, "default_embedding"):
            self.load_with(lambda rag: rag.update(default_embedding="nope"))
        with self.assertRaisesRegex(ValidationError, "default_chunking"):
            self.load_with(lambda rag: rag.update(default_chunking="nope"))


class TestMonitoringConfig(unittest.TestCase):
    def test_defaults_keep_tracing_off(self):
        config = MonitoringConfig()

        self.assertFalse(config.tracing.enabled)
        self.assertEqual(config.tracing.sample_ratio, 1.0)
        self.assertEqual(config.service_names.api, "answerworks-api")

    def test_the_shipped_file_is_valid_and_off(self):
        loaded = MonitoringConfig.model_validate(
            yaml.safe_load((CONFIG / "monitoring.yaml").read_text())
        )

        self.assertFalse(loaded.tracing.enabled)
        self.assertEqual(load_settings().monitoring, loaded)

    def test_a_missing_file_means_everything_off(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"ANSWERWORKS_CONFIG_DIR": folder}):
                self.assertEqual(load_monitoring(), MonitoringConfig())

    def test_the_endpoint_must_be_http_and_loses_a_trailing_slash(self):
        self.assertEqual(
            TracingConfig(otlp_endpoint="https://collector:4318/").otlp_endpoint,
            "https://collector:4318",
        )
        with self.assertRaises(ValidationError):
            TracingConfig(otlp_endpoint="collector:4318")

    def test_ratio_and_timeout_are_bounded_and_unknown_keys_rejected(self):
        for bad in ({"sample_ratio": 1.5}, {"sample_ratio": -0.1}, {"export_timeout_seconds": 0}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                TracingConfig(**bad)
        with self.assertRaises(ValidationError):
            MonitoringConfig.model_validate({"tracing": {"enable": True}})


if __name__ == "__main__":
    unittest.main()
