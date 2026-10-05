import os
import unittest
from unittest.mock import patch

from app.core import settings
from app.core.settings import ProvidersConfig
from app.services.llm import registry
from app.services.llm.errors import LLMServiceError
from app.services.llm.providers.anthropic_provider import AnthropicProvider
from app.services.llm.providers.fake import FakeProvider
from app.services.llm.providers.openai_provider import LocalProvider, OpenAIProvider
from tests.helpers import REQUEST, fake_provider, make_registry, provider_config


def build(providers_yaml_overrides=None, env=None):
    """Registry built from the shipped providers.yaml with optional env keys / overrides."""
    settings.reset_settings()
    loaded = settings.load_settings()
    if providers_yaml_overrides:
        data = loaded.providers.model_dump()
        providers_yaml_overrides(data)
        loaded = loaded.model_copy(update={"providers": ProvidersConfig.model_validate(data)})
    with patch.dict(os.environ, env or {}):
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LOCAL_LLM_API_KEY"):
            if not (env and key in env):
                os.environ.pop(key, None)
        return registry.build_registry(loaded)


class TestBuildRegistry(unittest.TestCase):
    def tearDown(self):
        settings.reset_settings()
        registry.get_registry.cache_clear()

    def test_enabled_providers_with_keys_are_built(self):
        built = build(env={"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "o"})

        self.assertEqual(list(built.providers), ["anthropic", "openai"])
        self.assertIsInstance(built.providers["anthropic"], AnthropicProvider)
        self.assertIsInstance(built.providers["openai"], OpenAIProvider)
        self.assertEqual(built.default_provider, "anthropic")

    def test_providers_without_keys_are_skipped_with_a_warning(self):
        with self.assertLogs(registry.logger, level="WARNING") as captured:
            built = build(env={"OPENAI_API_KEY": "o"})

        self.assertEqual(list(built.providers), ["openai"])
        self.assertTrue(any("ANTHROPIC_API_KEY" in m for m in captured.output))

    def test_default_falls_back_when_the_default_provider_is_skipped(self):
        with self.assertLogs(registry.logger, level="WARNING"):
            built = build(env={"OPENAI_API_KEY": "o"})

        self.assertEqual(built.default_provider, "openai")
        self.assertEqual(built.default_model().id, "gpt-4o-mini")

    def test_no_keys_means_no_providers(self):
        with self.assertLogs(registry.logger, level="WARNING") as captured:
            built = build()

        self.assertEqual(built.providers, {})
        self.assertIsNone(built.default_model())
        self.assertEqual(built.models(), [])
        self.assertTrue(any("No LLM providers" in m for m in captured.output))
        with self.assertRaises(LLMServiceError) as raised:
            built.resolve(None, None)
        self.assertEqual(raised.exception.status_code, 503)

    def test_local_and_fake_providers_need_no_key(self):
        def enable(data):
            data["providers"]["local"]["enabled"] = True
            data["providers"]["fake"]["enabled"] = True

        with self.assertLogs(registry.logger, level="WARNING"):
            built = build(enable)

        self.assertIsInstance(built.providers["local"], LocalProvider)
        self.assertIsInstance(built.providers["fake"], FakeProvider)

    def test_get_registry_is_cached_and_built_from_settings(self):
        registry.get_registry.cache_clear()
        with patch.object(registry, "build_registry", return_value="R") as build_mock:
            self.assertEqual(registry.get_registry(), "R")
            self.assertEqual(registry.get_registry(), "R")
        build_mock.assert_called_once()


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.reg = make_registry(
            fake_provider("a"), fake_provider("b", default_model="free"), default="b"
        )

    def test_defaults_to_default_provider_and_its_default_model(self):
        resolved = self.reg.resolve(None, None)

        self.assertEqual((resolved.provider.name, resolved.model.id), ("b", "free"))
        self.assertIs(resolved.request, REQUEST)

    def test_bare_model_prefers_default_provider(self):
        self.assertEqual(self.reg.resolve(None, "priced").provider.name, "b")

    def test_explicit_provider_and_model(self):
        resolved = self.reg.resolve("a", "free")

        self.assertEqual((resolved.provider.name, resolved.model.id), ("a", "free"))

    def test_explicit_provider_uses_its_own_default_model(self):
        self.assertEqual(self.reg.resolve("a", None).model.id, "priced")

    def test_unknown_provider_or_model_is_422(self):
        for provider, model in (("zzz", None), (None, "zzz"), ("a", "zzz")):
            with (
                self.subTest(provider=provider, model=model),
                self.assertRaises(LLMServiceError) as raised,
            ):
                self.reg.resolve(provider, model)
            self.assertEqual(raised.exception.status_code, 422)

    def test_models_lists_every_provider(self):
        self.assertEqual(
            [(m.provider, m.id) for m in self.reg.models()],
            [("a", "priced"), ("a", "free"), ("b", "priced"), ("b", "free")],
        )


class TestProviderConfigHelper(unittest.TestCase):
    def test_pricing_is_attached_to_the_resolved_model(self):
        reg = make_registry()

        self.assertIsNotNone(reg.resolve(None, "priced").model.pricing)
        self.assertIsNone(reg.resolve(None, "free").model.pricing)
        self.assertEqual(provider_config().default_model, "priced")


if __name__ == "__main__":
    unittest.main()
