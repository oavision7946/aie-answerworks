"""Configuration loading: YAML from the repo-level config/ directory, secrets from .env."""

import os
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


def clear_config_cache() -> None:
    load_yaml.cache_clear()
