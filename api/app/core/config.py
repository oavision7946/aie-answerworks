"""Configuration loading: YAML from the repo-level config/ directory, secrets from .env."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    """Directory holding config/*.yaml; override with ANSWERWORKS_CONFIG_DIR."""
    override = os.environ.get("ANSWERWORKS_CONFIG_DIR")
    return Path(override) if override else REPO_ROOT / "config"


def load_env() -> None:
    """Load secrets from the repo-level .env without overriding real environment variables."""
    load_dotenv(REPO_ROOT / ".env")


@lru_cache
def load_yaml(name: str) -> dict[str, Any]:
    with (config_dir() / name).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


@dataclass(frozen=True)
class LLMSettings:
    default_model: str
    timeout_seconds: float
    max_attempts: int
    retry_base_delay_seconds: float


@lru_cache
def get_llm_settings() -> LLMSettings:
    llm = load_yaml("app.yaml")["llm"]
    return LLMSettings(
        default_model=str(llm["default_model"]),
        timeout_seconds=float(llm["timeout_seconds"]),
        max_attempts=int(llm["max_attempts"]),
        retry_base_delay_seconds=float(llm["retry_base_delay_seconds"]),
    )


@lru_cache
def load_model_costs() -> dict[str, dict[str, float]]:
    models: dict[str, dict[str, float]] = load_yaml("model_costs.yaml")["models"]
    return models


def clear_config_cache() -> None:
    load_yaml.cache_clear()
    get_llm_settings.cache_clear()
    load_model_costs.cache_clear()
