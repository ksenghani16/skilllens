"""Settings: config.yaml plus environment-variable overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class Config(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "qwen2.5:7b-instruct"
    temperature: float = 0.2
    timeout_s: float = 180.0
    max_retries: int = 3
    retry_wait_s: float = 1.0
    repeats: int = 3
    min_drop: float = 0.5
    recovery_threshold: float = 0.5
    bootstrap_samples: int = 2000
    seed: int = 0
    max_failures_shown: int = 4
    max_output_chars: int = 500
    max_causes: int = 3
    max_exhaustive_changes: int = 10
    investigator_attempts: int = 3
    cache_dir: str = ".cache"
    runs_dir: str = "runs"


_ENV = {
    "LLM_BASE_URL": "base_url",
    "LLM_API_KEY": "api_key",
    "SKILLLENS_MODEL": "model",
    "SKILLLENS_TEMPERATURE": "temperature",
}


def load_config(path: Optional[str] = None) -> Config:
    data: dict = {}
    p = Path(path) if path else Path("config.yaml")
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for env_name, field in _ENV.items():
        if os.getenv(env_name):
            data[field] = os.environ[env_name]
    return Config(**data)
