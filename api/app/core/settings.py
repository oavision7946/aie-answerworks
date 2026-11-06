"""Validated application settings: config/*.yaml (non-secret) plus environment/.env (secrets)."""

import os
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import REPO_ROOT, clear_config_cache, config_dir, load_env, load_yaml


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- providers.yaml ---------------------------------------------------------------------------


class Pricing(_Strict):
    """USD per 1M tokens."""

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cached_input: float | None = Field(default=None, ge=0)

    @property
    def cached_input_price(self) -> float:
        return self.input if self.cached_input is None else self.cached_input


class ModelConfig(_Strict):
    id: str
    label: str
    pricing: Pricing | None = None


class RequestConfig(_Strict):
    """Timeout, retry and output limits applied to every provider call."""

    timeout_seconds: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    retry_base_delay_seconds: float = Field(ge=0)
    max_output_tokens: int = Field(gt=0)


class ProviderConfig(_Strict):
    type: Literal["anthropic", "openai", "openai_compatible", "fake"]
    enabled: bool = False
    api_key_env: str | None = None
    # Anthropic only: env var holding a workspace id, for keys not scoped to a workspace.
    workspace_id_env: str | None = None
    base_url: str | None = None
    default_model: str
    models: list[ModelConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_provider(self) -> "ProviderConfig":
        ids = [m.id for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("model ids must be unique within a provider")
        if self.default_model not in ids:
            raise ValueError(f"default_model {self.default_model!r} is not in models")
        if self.type in ("anthropic", "openai") and not self.api_key_env:
            raise ValueError(f"{self.type} providers require api_key_env")
        if self.workspace_id_env and self.type != "anthropic":
            raise ValueError("workspace_id_env is only supported for anthropic providers")
        if self.type == "openai_compatible" and not self.base_url:
            raise ValueError("openai_compatible providers require base_url")
        return self


class ProvidersConfig(_Strict):
    default_provider: str
    request: RequestConfig
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


class EmbeddingModelConfig(_Strict):
    provider: str
    model: str
    dimensions: int = Field(gt=0)


ChunkingMethod = Literal["fixed", "recursive", "paragraph", "sentence"]


class ChunkingConfig(_Strict):
    method: ChunkingMethod
    size: int = Field(gt=0)
    overlap: int = Field(ge=0)

    @model_validator(mode="after")
    def overlap_must_be_smaller_than_size(self) -> "ChunkingConfig":
        if self.overlap >= self.size:
            raise ValueError("chunking overlap must be smaller than size")
        return self


class RetrievalConfig(_Strict):
    top_k: int = Field(gt=0)
    min_score: float = Field(ge=0.0, le=1.0)


class VectorStoreConfig(_Strict):
    type: Literal["pgvector"]


class RagConfig(_Strict):
    embedding_models: dict[str, EmbeddingModelConfig] = Field(min_length=1)
    default_embedding: str
    chunking_strategies: dict[str, ChunkingConfig] = Field(min_length=1)
    default_chunking: str
    retrieval: RetrievalConfig
    vector_store: VectorStoreConfig
    supported_formats: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def defaults_must_exist(self) -> "RagConfig":
        if self.default_embedding not in self.embedding_models:
            raise ValueError(f"default_embedding {self.default_embedding!r} is not defined")
        if self.default_chunking not in self.chunking_strategies:
            raise ValueError(f"default_chunking {self.default_chunking!r} is not defined")
        return self


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


class ChatConfig(_Strict):
    # How many of the most recent stored messages are sent to the model with each new message.
    history_messages: int = Field(gt=0)


class AppConfig(_Strict):
    app: AppInfo
    cors: CorsConfig
    auth: AuthConfig
    chat: ChatConfig
    limits: LimitsConfig


# --- corpora.yaml -----------------------------------------------------------------------------


class FilesystemSourceConfig(_Strict):
    type: Literal["filesystem"]
    path: str


class UrlSourceConfig(_Strict):
    type: Literal["url"]
    # Fetched with GET. Only http and https, and only the addresses listed here: the config is
    # written by the operator, never by users.
    urls: list[str] = Field(min_length=1)

    @field_validator("urls")
    @classmethod
    def urls_must_be_http(cls, urls: list[str]) -> list[str]:
        for url in urls:
            if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
                raise ValueError(f"source url {url!r} must be an http or https address")
        return urls


CorpusSource = Annotated[FilesystemSourceConfig | UrlSourceConfig, Field(discriminator="type")]


class CorpusConfig(_Strict):
    name: str
    description: str = ""
    source: CorpusSource
    public: bool = False
    # Re-ingest with the default embedding model and splitter this often (minutes) when the
    # scheduler runs (`python -m scripts.scheduler`). Omit for manual ingestion only.
    refresh_minutes: int | None = Field(default=None, gt=0)


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
    # Enables GET /metrics (Prometheus). Empty keeps the endpoint off.
    metrics_token: str = ""
    api_base_url: str = "http://localhost:8000"


class TracingConfig(_Strict):
    """Whether and where spans are exported. Off by default; ids still reach logs and headers."""

    enabled: bool = False
    # OTLP over HTTP; "/v1/traces" is appended. Credentials, if any, go in the environment
    # variable OTEL_EXPORTER_OTLP_HEADERS, never in this file.
    otlp_endpoint: str = "http://localhost:4318"
    sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    export_timeout_seconds: float = Field(default=5.0, gt=0)

    @field_validator("otlp_endpoint")
    @classmethod
    def endpoint_is_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value.rstrip("/")


class ServiceNames(_Strict):
    api: str = "answerworks-api"
    scheduler: str = "answerworks-scheduler"


class MonitoringConfig(_Strict):
    tracing: TracingConfig = TracingConfig()
    service_names: ServiceNames = ServiceNames()


class Settings(BaseModel):
    app: AppConfig
    providers: ProvidersConfig
    rag: RagConfig
    corpora: CorporaConfig
    env: EnvSettings
    monitoring: MonitoringConfig = MonitoringConfig()

    @model_validator(mode="after")
    def cross_references_must_resolve(self) -> "Settings":
        for name, embedding in self.rag.embedding_models.items():
            provider = self.providers.providers.get(embedding.provider)
            if provider is None:
                raise ValueError(
                    f"rag.embedding_models.{name}: provider {embedding.provider!r} "
                    "is not defined in providers.yaml"
                )
            if provider.type == "anthropic":
                raise ValueError(
                    f"rag.embedding_models.{name}: anthropic providers cannot create embeddings"
                )
        return self

    def missing_provider_keys(self) -> dict[str, str]:
        """Enabled providers whose api_key_env is set in config but absent from the environment."""
        return {
            name: p.api_key_env
            for name, p in self.providers.enabled.items()
            if p.type in ("anthropic", "openai") and p.api_key_env and not os.getenv(p.api_key_env)
        }


def load_monitoring() -> MonitoringConfig:
    """config/monitoring.yaml; a missing file means everything off."""
    if not (config_dir() / "monitoring.yaml").exists():
        return MonitoringConfig()
    return MonitoringConfig.model_validate(load_yaml("monitoring.yaml"))


def load_settings() -> Settings:
    load_env()
    return Settings(
        app=AppConfig.model_validate(load_yaml("app.yaml")),
        providers=ProvidersConfig.model_validate(load_yaml("providers.yaml")),
        rag=RagConfig.model_validate(load_yaml("rag.yaml")),
        corpora=CorporaConfig.model_validate(load_yaml("corpora.yaml")),
        env=EnvSettings(),
        monitoring=load_monitoring(),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()


def reset_settings() -> None:
    get_settings.cache_clear()
    clear_config_cache()
