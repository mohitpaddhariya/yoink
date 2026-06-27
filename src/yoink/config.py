"""yoink runtime configuration: a small JSON file plus env overrides.

Precedence (high → low): environment (``YOINK_MODEL`` / ``YOINK_TIMEOUT``), the config
file, then defaults. Config file path: ``$YOINK_CONFIG``, else ``~/.config/yoink/config.json``.
Written by ``install.py`` at first-time setup; read by the broker on every recall.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-4-5"  # recall is extraction; cheapest model that passes the gate
DEFAULT_TIMEOUT = 120.0


def config_path() -> Path:
    override = os.environ.get("YOINK_CONFIG")
    return Path(override) if override else (Path.home() / ".config" / "yoink" / "config.json")


@dataclass(frozen=True)
class Config:
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT


def _read_file() -> dict:
    try:
        data = json.loads(config_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_config() -> Config:
    data = _read_file()
    model = os.environ.get("YOINK_MODEL") or data.get("model") or DEFAULT_MODEL
    raw_timeout = os.environ.get("YOINK_TIMEOUT") or data.get("timeout") or DEFAULT_TIMEOUT
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return Config(model=str(model), timeout=timeout)


def save_config(*, model: str | None = None) -> Path:
    """Merge the model into the config file (creating it) and return its path."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_file()
    if model is not None:
        current["model"] = model
    path.write_text(json.dumps(current, indent=2) + "\n")
    return path
