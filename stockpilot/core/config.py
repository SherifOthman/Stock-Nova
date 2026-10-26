"""
Central configuration loader and manager for Google Dots.
Loads settings.yaml, accounts_config.json, api_keys.yaml, and handles key encryption.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(r"d:\Stock Automation")
CONFIG_DIR = PROJECT_ROOT / "config"


class Config:
    """Singleton Configuration Manager."""

    _settings: dict[str, Any] = {}
    _accounts: dict[str, Any] = {}
    _api_keys: dict[str, Any] = {}
    _initialized: bool = False

    @classmethod
    def load(cls) -> None:
        """Loads all configuration files from the config directory."""
        settings_file = CONFIG_DIR / "settings.yaml"
        if settings_file.exists():
            with open(settings_file, "r", encoding="utf-8") as f:
                cls._settings = yaml.safe_load(f) or {}

        accounts_file = CONFIG_DIR / "accounts_config.json"
        if accounts_file.exists():
            with open(accounts_file, "r", encoding="utf-8") as f:
                cls._accounts = json.load(f) or {}

        keys_file = CONFIG_DIR / "api_keys.yaml"
        if keys_file.exists():
            with open(keys_file, "r", encoding="utf-8") as f:
                cls._api_keys = yaml.safe_load(f) or {}

        cls._initialized = True

    @classmethod
    def get(cls, key_path: str, default: Any = None) -> Any:
        """Retrieves a configuration value using dot notation (e.g. 'paths.database')."""
        if not cls._initialized:
            cls.load()

        keys = key_path.split(".")
        val: Any = cls._settings

        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    @classmethod
    def get_path(cls, key_path: str, default: Path | None = None) -> Path:
        """Returns a path configuration item as a pathlib.Path."""
        val = cls.get(key_path)
        if val:
            return Path(val)
        return default or Path()

    @classmethod
    def get_accounts_config(cls) -> dict[str, Any]:
        """Returns the full accounts_config.json data."""
        if not cls._initialized:
            cls.load()
        return cls._accounts

    @classmethod
    def get_api_keys(cls) -> list[str]:
        """Returns raw Gemini API keys configured."""
        if not cls._initialized:
            cls.load()
        keys_list = cls._api_keys.get("gemini", [])
        return [k["key"] for k in keys_list if isinstance(k, dict) and "key" in k and k["key"] != "YOUR_API_KEY_HERE"]


# Auto-load on import
Config.load()
