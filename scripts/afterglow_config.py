#!/usr/bin/env python3
"""Shared Afterglow Companion System configuration helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE") or Path(__file__).resolve().parents[1]).resolve()
BRAIN = WORKSPACE / "brain"
CONFIG_PATH = Path(os.environ.get("AFTERGLOW_CONFIG") or BRAIN / "afterglow_config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "companion_name": "Companion",
    "user_name": "User",
    "timezone": "America/New_York",
    "models": {
        "pulse": "openrouter/auto",
        "diary": "openrouter/auto",
        "reflection": "openrouter/auto",
        "recall": "local_sqlite_fts",
    },
    "model_runner": {
        "command_template": "",
        "timeout_seconds": 120,
        "notes": "Optional. Template fields: {model}, {session_key}, {prompt_path}, {output_path}. If empty, pulse writes prompt files instead of calling a model.",
    },
    "pulse": {
        "enabled": True,
        "interval_minutes": 72,
        "diary_on_pulse": True,
        "outreach_enabled": False,
        "quiet_hours_start": 22,
        "quiet_hours_end": 7,
    },
    "ui": {
        "host": "127.0.0.1",
        "port": 8765,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict[str, Any]:
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return deep_merge(DEFAULT_CONFIG, raw)
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(deep_merge(DEFAULT_CONFIG, config), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def ensure_config() -> dict[str, Any]:
    config = load_config()
    if not CONFIG_PATH.exists():
        save_config(config)
    return config
