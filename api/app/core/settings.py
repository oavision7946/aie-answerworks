"""Validated application settings: config/*.yaml (non-secret) plus environment/.env (secrets)."""

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import REPO_ROOT, clear_config_cache, load_env, load_yaml


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- providers.yaml ---------------------------------------------------------------------------


class ModelConfig(_Strict):
    id: str
    label: str


class ProviderConfig(_Strict):
    type: Literal["anthropic", "openai", "openai_compatible"]
    enabled: bool = False
    api_key_env: str | None = None
    base_url: str | None = None
    default_model: str
    models: list[ModelConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def default_model_must_be_listed(self) -> "ProviderConfig":
        if self.default_model not in {m.id for m in self.models}:
            raise ValueError(f"default_model {self.default_model!r} is not in models")
        return self


class ProvidersConfig(_Strict):
    default_provider: str
    providers: dict[str, ProviderConfig]

    @model_validator(mode="after")
    def default_provider_must_be_enabled(self) -> "ProvidersConfig":
        provider = self.providers.get(self.default_provider)
        if provider is None:
            raise ValueError(f"default_provider {self.default_provider!r} is not defined")
        if not provider.enabled:
            raise ValueError(f"default_provider {self.default_provider!r} is not enabled")
        return self

    @property
    def enabled(self) -> dict[str, ProviderConfig]:
        return {name: p for name, p in self.providers.items() if p.enabled}


# --- rag.yaml ---------------------------------------------------------------------------------


class EmbeddingsConfig(_Strict):
    provider: str
    model: str
    dimensions: int = Field(gt=0)


class ChunkingConfig(_Strict):
    size: int = Field(gt=0)
    overlap: int = Field(ge=0)

    @model_validator(mode="after")
    def overlap_must_be_smaller_than_size(self) -> "ChunkingConfig":
        if self.overlap >= self.size:
            raise ValueError("chunking.overlap must be smaller than chunking.size")
        return self


class RetrievalConfig(_Strict):
    top_k: int = Field(gt=0)
    min_score: float = Field(ge=0.0, le=1.0)


class VectorStoreConfig(_Strict):
    type: Literal["pgvector"]


class RagConfig(_Strict):
    embeddings: EmbeddingsConfig
    chunking: ChunkingConfig
    retrieval: RetrievalConfig
    vector_store: VectorStoreConfig
    supported_formats: list[str] = Field(min_length=1)


# --- app.yaml ---------------------------------------------------------------------------------


class AppInfo(_Strict):
    name: str
    environment: Literal["development", "test", "production"]


class CorsConfig(_Strict):
    allow_origins: list[str] = []


class AuthConfig(_Strict):
    access_token_ttl_minutes: int = Field(gt=0)
    refresh_token_ttl_days: int = Field(gt=0)


class LimitsConfig(_Strict):
    max_upload_mb: int = Field(gt=0)


class LLMConfig(_Strict):
    default_model: str
    timeout_seconds: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    retry_base_delay_seconds: float = Field(ge=0)


class AppConfig(_Strict):
    app: AppInfo
    cors: CorsConfig
    auth: AuthConfig
    limits: LimitsConfig
    llm: LLMConfig


# --- corpora.yaml -----------------------------------------------------------------------------


class CorpusConfig(_Strict):
    name: str
    description: str = ""
    source: dict[str, str]
    public: bool = False


class CorporaConfig(_Strict):
    corpora: list[CorpusConfig] = []

    @model_validator(mode="after")
    def names_must_be_unique(self) -> "CorporaConfig":
        names = [c.name for c in self.corpora]
        if len(names) != len(set(names)):
            raise ValueError("corpus names must be unique")
        return self


# --- environment / .env -----------------------------------------------------------------------


class EnvSettings(BaseSettings):
    """Secrets and deployment-specific values. Never read from YAML."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://answerworks:answerworks@localhost:5432/answerworks"
    jwt_secret: str = ""
    api_base_url: str = "http://localhost:8000"


class Settings(BaseModel):
    app: AppConfig
    providers: ProvidersConfig
    rag: RagConfig
    corpora: CorporaConfig
    env: EnvSettings

    @model_validator(mode="after")
    def cross_references_must_resolve(self) -> "Settings":
        if self.rag.embeddings.provider not in self.providers.providers:
            raise ValueError(
                f"rag.embeddings.provider {self.rag.embeddings.provider!r} "
                "is not defined in providers.yaml"
            )
        return self

    def missing_provider_keys(self) -> dict[str, str]:
        """Enabled providers whose api_key_env is set in config but absent from the environment."""
        return {
            name: p.api_key_env
            for name, p in self.providers.enabled.items()
            if p.api_key_env and p.type != "openai_compatible" and not os.getenv(p.api_key_env)
        }


def load_settings() -> Settings:
    load_env()
    return Settings(
        app=AppConfig.model_validate(load_yaml("app.yaml")),
        providers=ProvidersConfig.model_validate(load_yaml("providers.yaml")),
        rag=RagConfig.model_validate(load_yaml("rag.yaml")),
        corpora=CorporaConfig.model_validate(load_yaml("corpora.yaml")),
        env=EnvSettings(),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()


def reset_settings() -> None:
    get_settings.cache_clear()
    clear_config_cache()
