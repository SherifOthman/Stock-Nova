"""
Central Configuration & Per-User Isolation Manager for StockNova AI.
Guarantees that every user/machine gets its own isolated database, workspace,
encrypted credentials, and adaptive settings without any hardcoded personal paths.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # Graceful fallback when running in minimal container

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _safe_yaml_load(text: str) -> dict[str, Any]:
    if yaml is not None:
        try:
            return yaml.safe_load(text) or {}
        except Exception:
            pass
    try:
        return json.loads(text) or {}
    except Exception:
        return {}


def _safe_yaml_dump(data: dict[str, Any]) -> str:
    if yaml is not None:
        try:
            return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        except Exception:
            pass
    return json.dumps(data, indent=2, ensure_ascii=False)


def _resolve_default_user_data_dir() -> Path:
    """
    Resolves an isolated per-user data directory:
    - On Windows: %LOCALAPPDATA%\\StockNovaAI (or ./data if portable mode is enabled)
    - On Linux/macOS (or preview container): PROJECT_ROOT / 'data'
    """
    portable_flag = PROJECT_ROOT / ".portable"
    if portable_flag.exists():
        p = PROJECT_ROOT / "data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            p = Path(local_appdata) / "StockNovaAI"
            p.mkdir(parents=True, exist_ok=True)
            return p

    p = PROJECT_ROOT / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_default_workspace_dir() -> Path:
    """
    Resolves the default media workspace folder for the current user.
    If an existing workspace folder exists in PROJECT_ROOT / 'workspace', uses it;
    otherwise uses Documents/StockNova Workspace on Windows.
    """
    local_ws = PROJECT_ROOT / "workspace"
    if local_ws.exists():
        return local_ws

    if sys.platform == "win32":
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            docs_ws = Path(user_profile) / "Documents" / "StockNova Workspace"
            docs_ws.mkdir(parents=True, exist_ok=True)
            return docs_ws

    local_ws.mkdir(parents=True, exist_ok=True)
    return local_ws


def _auto_detect_upscayl() -> tuple[Path, Path]:
    """Auto-detects Upscayl binary and models folder across any Windows user account."""
    candidates = []
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        if local_app:
            candidates.append(Path(local_app) / "Programs" / "Upscayl" / "resources")
        candidates.append(Path(prog_files) / "Upscayl" / "resources")
        candidates.append(Path(prog_x86) / "Upscayl" / "resources")

    for res_dir in candidates:
        bin_p = res_dir / "bin" / "upscayl-bin.exe"
        mod_p = res_dir / "models"
        if bin_p.exists():
            return bin_p, mod_p

    default_res = Path(r"C:\Program Files\Upscayl\resources")
    return default_res / "bin" / "upscayl-bin.exe", default_res / "models"


def _auto_detect_chrome_user_data() -> Path:
    """Auto-detects the current Windows user's Chrome User Data folder."""
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            p = Path(local_app) / "Google" / "Chrome" / "User Data"
            if p.exists():
                return p
    return Path()


class Config:
    """Singleton Configuration & Per-User Path Manager."""

    _settings: dict[str, Any] = {}
    _user_overrides: dict[str, Any] = {}
    _accounts: dict[str, Any] = {}
    _api_keys: dict[str, Any] = {}
    _initialized: bool = False

    @classmethod
    def get_project_root(cls) -> Path:
        return PROJECT_ROOT

    @classmethod
    def get_user_data_dir(cls) -> Path:
        return _resolve_default_user_data_dir()

    @classmethod
    def get_workspace_dir(cls) -> Path:
        return cls.get_path("paths.workspace_root", _resolve_default_workspace_dir())

    @classmethod
    def get_user_settings_file(cls) -> Path:
        return cls.get_user_data_dir() / "user_settings.yaml"

    @classmethod
    def get_accounts_file(cls) -> Path:
        user_acc = cls.get_user_data_dir() / "accounts_config.json"
        if user_acc.exists():
            return user_acc
        repo_acc = CONFIG_DIR / "accounts_config.json"
        if repo_acc.exists():
            return repo_acc
        return user_acc

    @classmethod
    def load(cls) -> None:
        """Loads base template settings and merges per-user overrides."""
        settings_file = CONFIG_DIR / "settings.yaml"
        if settings_file.exists():
            try:
                cls._settings = _safe_yaml_load(settings_file.read_text(encoding="utf-8"))
            except Exception:
                cls._settings = {}

        user_settings_file = cls.get_user_settings_file()
        if user_settings_file.exists():
            try:
                cls._user_overrides = _safe_yaml_load(user_settings_file.read_text(encoding="utf-8"))
                cls._deep_merge(cls._settings, cls._user_overrides)
            except Exception:
                cls._user_overrides = {}

        # Populate dynamic per-user paths if blank
        paths_cfg = cls._settings.setdefault("paths", {})
        user_data_dir = cls.get_user_data_dir()

        ws_val = str(paths_cfg.get("workspace_root", "")).strip()
        if not ws_val or "Stock Automation" in ws_val or (sys.platform != "win32" and ":" in ws_val):
            paths_cfg["workspace_root"] = str(_resolve_default_workspace_dir())

        db_val = str(paths_cfg.get("database", "")).strip()
        if not db_val or "Stock Automation" in db_val or (sys.platform != "win32" and ":" in db_val):
            legacy_db = PROJECT_ROOT / "data" / "google_dots.db"
            if legacy_db.exists():
                paths_cfg["database"] = str(legacy_db)
            else:
                paths_cfg["database"] = str(user_data_dir / "stocknova.db")

        logs_val = str(paths_cfg.get("logs_dir", "")).strip()
        if not logs_val or "Stock Automation" in logs_val or (sys.platform != "win32" and ":" in logs_val):
            paths_cfg["logs_dir"] = str(user_data_dir / "logs")

        exif_val = str(paths_cfg.get("exiftool", "")).strip()
        if not exif_val or "Stock Automation" in exif_val:
            paths_cfg["exiftool"] = str(PROJECT_ROOT / "tools" / "exiftool.exe")

        # Auto-detect Upscayl paths if empty
        upscayl_cfg = cls._settings.setdefault("upscayl", {})
        bin_p, mod_p = _auto_detect_upscayl()
        if not upscayl_cfg.get("bin_path") or "eleml" in str(upscayl_cfg.get("bin_path", "")):
            upscayl_cfg["bin_path"] = str(bin_p)
        if not upscayl_cfg.get("models_dir") or "eleml" in str(upscayl_cfg.get("models_dir", "")):
            upscayl_cfg["models_dir"] = str(mod_p)
        upscayl_cfg["default_scale"] = 2

        chrome_cfg = cls._settings.setdefault("chrome", {})
        if not chrome_cfg.get("user_data_dir") or "eleml" in str(chrome_cfg.get("user_data_dir", "")):
            chrome_cfg["user_data_dir"] = str(_auto_detect_chrome_user_data())

        accounts_file = cls.get_accounts_file()
        if not accounts_file.exists():
            default_data = {
                "system_settings": {
                    "project_name": "StockNova AI",
                    "generation_priority": ["video", "image"],
                    "image_model": "nano banana pro",
                },
                "credit_strategy": {
                    "free_tier": {"daily_points_per_account": 50},
                    "plus_pool": {"total_credits": 200, "target_consumption_days": 7},
                    "pro_pool": {"total_credits": 1000, "target_consumption_days": 14},
                },
                "accounts": [],
            }
            accounts_file.parent.mkdir(parents=True, exist_ok=True)
            accounts_file.write_text(json.dumps(default_data, indent=2), encoding="utf-8")

        try:
            with open(accounts_file, "r", encoding="utf-8") as f:
                cls._accounts = json.load(f) or {}
        except Exception:
            cls._accounts = {}

        keys_file = CONFIG_DIR / "api_keys.yaml"
        if keys_file.exists():
            try:
                cls._api_keys = _safe_yaml_load(keys_file.read_text(encoding="utf-8"))
            except Exception:
                cls._api_keys = {}

        cls._initialized = True

    @staticmethod
    def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> None:
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Config._deep_merge(base[k], v)
            else:
                base[k] = v

    @classmethod
    def get(cls, key_path: str, default: Any = None) -> Any:
        if not cls._initialized:
            cls.load()

        keys = key_path.split(".")
        val: Any = cls._settings

        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val if val is not None else default

    @classmethod
    def set(cls, key_path: str, value: Any, persist: bool = True) -> None:
        if not cls._initialized:
            cls.load()

        keys = key_path.split(".")
        target = cls._settings
        override_target = cls._user_overrides

        for k in keys[:-1]:
            target = target.setdefault(k, {})
            override_target = override_target.setdefault(k, {})

        target[keys[-1]] = value
        override_target[keys[-1]] = value

        if persist:
            user_file = cls.get_user_settings_file()
            user_file.parent.mkdir(parents=True, exist_ok=True)
            user_file.write_text(_safe_yaml_dump(cls._user_overrides), encoding="utf-8")

    @classmethod
    def get_path(cls, key_path: str, default: Path | None = None) -> Path:
        val = cls.get(key_path)
        if val and str(val).strip():
            return Path(str(val))
        if default is not None:
            return default
        if key_path == "paths.workspace_root":
            return _resolve_default_workspace_dir()
        if key_path == "paths.database":
            return cls.get_user_data_dir() / "stocknova.db"
        return PROJECT_ROOT

    @classmethod
    def get_accounts_config(cls) -> dict[str, Any]:
        if not cls._initialized:
            cls.load()
        return cls._accounts

    @classmethod
    def save_accounts_config(cls, data: dict[str, Any]) -> None:
        cls._accounts = data
        acc_file = cls.get_user_data_dir() / "accounts_config.json"
        acc_file.parent.mkdir(parents=True, exist_ok=True)
        acc_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def get_api_keys(cls) -> list[str]:
        keys: list[str] = []

        try:
            from stockpilot.core.database import Database
            from stockpilot.core.security import SecurityVault

            db = Database()
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT api_key FROM gemini_keys WHERE status = 'active' ORDER BY priority ASC, id ASC;"
                )
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

        if not cls._initialized:
            cls.load()
        keys_list = cls._api_keys.get("gemini", [])
        for k in keys_list:
            if isinstance(k, dict) and "key" in k:
                val = str(k["key"]).strip()
                if val and val != "YOUR_API_KEY_HERE" and val not in keys:
                    keys.append(val)

        env_key = os.getenv("GEMINI_API_KEY")
        if env_key and env_key.strip() not in keys:
            keys.append(env_key.strip())

        return keys

    @classmethod
    def get_ftp_password(cls) -> str:
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
        try:
            from stockpilot.core.database import Database
            from stockpilot.core.security import get_secure_credential

            db = Database()
            cred = get_secure_credential(db, "freepik")
            if cred and cred.get("secret"):
                return cred["secret"]
        except Exception:
            pass
        return cls.get("platforms.freepik.password", "")


Config.load()
