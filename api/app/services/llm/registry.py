"""Builds providers from config/providers.yaml and resolves a request to provider + model."""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from app.core.settings import ModelConfig, ProviderConfig, RequestConfig, Settings, get_settings
from app.schemas.ask import ModelInfo
from app.services.llm.base import Provider
from app.services.llm.errors import INVALID_REQUEST, NOT_CONFIGURED, LLMServiceError
from app.services.llm.providers.anthropic_provider import AnthropicProvider
from app.services.llm.providers.fake import FakeProvider
from app.services.llm.providers.openai_provider import LocalProvider, OpenAIProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedModel:
    provider: Provider
    model: ModelConfig
    request: RequestConfig


def build_provider(
    name: str, config: ProviderConfig, request: RequestConfig, api_key: str | None
) -> Provider | None:
    """Instantiate one provider, or None when a required API key is missing."""
    match config.type:
        case "fake":
            return FakeProvider(name, config, request)
        case "openai_compatible":
            return LocalProvider(name, config, request, api_key)
        case "openai" | "anthropic" if not api_key:
            logger.warning(
                "Provider %r is enabled but %s is not set; skipping it", name, config.api_key_env
            )
            return None
        case "openai":
            return OpenAIProvider(name, config, request, api_key or "")
        case _:
            return AnthropicProvider(name, config, request, api_key or "")


class ProviderRegistry:
    def __init__(
        self, providers: dict[str, Provider], default_provider: str, request: RequestConfig
    ) -> None:
        self.providers = providers
        self.request = request
        # The configured default may have been skipped (missing key): fall back to any provider.
        self.default_provider = (
            default_provider if default_provider in providers else next(iter(providers), "")
        )

    def models(self) -> list[ModelInfo]:
        return [
            ModelInfo(provider=name, id=m.id, label=m.label)
            for name, provider in self.providers.items()
            for m in provider.list_models()
        ]

    def default_model(self) -> ModelInfo | None:
        provider = self.providers.get(self.default_provider)
        if provider is None:
            return None
        model = provider.default_model
        return ModelInfo(provider=provider.name, id=model.id, label=model.label)

    def resolve(self, provider: str | None, model: str | None) -> ResolvedModel:
        """Map the optional (provider, model) of a request to a concrete provider and model.

        Raises LLMServiceError: 503 when nothing is configured, 422 for an unknown choice.
        """
        if not self.providers:
            raise LLMServiceError(503, NOT_CONFIGURED)
        if provider is not None:
            candidates = [self.providers[provider]] if provider in self.providers else []
        else:
            # The default provider is searched first so a bare model id resolves predictably.
            ordered = [self.default_provider, *self.providers]
            candidates = [self.providers[n] for n in dict.fromkeys(ordered)]
        for candidate in candidates:
            wanted = model or candidate.config.default_model
            try:
                return ResolvedModel(candidate, candidate.model(wanted), self.request)
            except KeyError:
                continue
        raise LLMServiceError(422, INVALID_REQUEST)


def build_registry(settings: Settings) -> ProviderRegistry:
    providers: dict[str, Provider] = {}
    for name, config in settings.providers.enabled.items():
        api_key = os.getenv(config.api_key_env) if config.api_key_env else None
        provider = build_provider(name, config, settings.providers.request, api_key)
        if provider is not None:
            providers[name] = provider
    if not providers:
        logger.error("No LLM providers are available; /ask will return 503")
    return ProviderRegistry(
        providers, settings.providers.default_provider, settings.providers.request
    )


@lru_cache
def get_registry() -> ProviderRegistry:
    return build_registry(get_settings())
