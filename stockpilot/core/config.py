"""
Central configuration loader and manager for StockNova AI.
Loads settings.yaml, accounts_config.json, and handles secure encrypted credentials from local SQLite.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
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
        if not accounts_file.exists():
            example_file = CONFIG_DIR / "accounts_config.example.json"
            if example_file.exists():
                accounts_file.write_text(example_file.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                default_data = {
                    "system_settings": {
                        "project_name": "StockNova AI",
                        "generation_priority": ["video", "image"],
                        "image_model": "nano banana pro"
                    },
                    "credit_strategy": {
                        "free_tier": {"daily_points_per_account": 50},
                        "plus_pool": {"total_credits": 200},
                        "pro_pool": {"total_credits": 1000}
                    },
                    "accounts": []
                }
                accounts_file.write_text(json.dumps(default_data, indent=2), encoding="utf-8")

        if accounts_file.exists():
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    cls._accounts = json.load(f) or {}
            except Exception:
                cls._accounts = {}

        keys_file = CONFIG_DIR / "api_keys.yaml"
        if keys_file.exists():
            try:
                with open(keys_file, "r", encoding="utf-8") as f:
                    cls._api_keys = yaml.safe_load(f) or {}
            except Exception:
                cls._api_keys = {}

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
        """
        Returns active Gemini API keys.
        Prioritizes encrypted keys stored in the local SQLite database.
        Falls back to api_keys.yaml or GEMINI_API_KEY environment variable.
        """
        keys: list[str] = []

        # 1. Query local SQLite database (encrypted)
        try:
            from stockpilot.core.database import Database
            from stockpilot.core.security import SecurityVault

            db = Database()
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT api_key FROM gemini_keys WHERE status = 'active';")
                for row in cursor.fetchall():
                    raw_k = row["api_key"]
                    if raw_k:
                        decrypted = SecurityVault.decrypt(raw_k).strip()
                        if decrypted and decrypted != "YOUR_API_KEY_HERE" and decrypted not in keys:
                            keys.append(decrypted)
        except Exception:
            pass

        if keys:
            return keys

        # 2. Fallback to local config/api_keys.yaml
        if not cls._initialized:
            cls.load()
        keys_list = cls._api_keys.get("gemini", [])
        for k in keys_list:
            if isinstance(k, dict) and "key" in k:
                val = str(k["key"]).strip()
                if val and val != "YOUR_API_KEY_HERE" and val not in keys:
                    keys.append(val)

        # 3. Fallback to environment variable
        env_key = os.getenv("GEMINI_API_KEY")
        if env_key and env_key.strip() not in keys:
            keys.append(env_key.strip())

        return keys

    @classmethod
    def get_ftp_password(cls) -> str:
        """Retrieves and decrypts the FTP password from local SQLite database or settings."""
        try:
            from stockpilot.core.database import Database
            from stockpilot.core.security import get_secure_credential

            db = Database()
            cred = get_secure_credential(db, "ftp")
            if cred and cred.get("secret"):
                return cred["secret"]
        except Exception:
            pass
        return cls.get("ftp.password", "")

    @classmethod
    def get_freepik_password(cls) -> str:
        """Retrieves and decrypts the Freepik password from local SQLite database or settings."""
        try:
            from stockpilot.core.database import Database
            from stockpilot.core.security import get_secure_credential

            db = Database()
            cred = get_secure_credential(db, "freepik")
            if cred and cred.get("secret"):
                return cred["secret"]
        except Exception:
            pass
        return cls.get("freepik.password", "")


# Auto-load on import
Config.load()
