"""
StockNova AI — Browser Account & Gmail Identity Resolver.
Automatically identifies real Google Account Names, Gaia IDs, and Gmail addresses
from Chrome and Edge local profiles, eliminating generic 'Profile 31/32' labels.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("browser_account_resolver")


class BrowserAccountResolver:
    """Discovers and resolves local Chrome and Edge Google identities."""

    @staticmethod
    def get_standard_browser_roots() -> dict[str, Path]:
        """Returns standard Windows AppData paths for Chrome, Edge, and Brave."""
        local_app_data = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\eleml\AppData\Local"))
        return {
            "chrome": local_app_data / "Google" / "Chrome" / "User Data",
            "edge": local_app_data / "Microsoft" / "Edge" / "User Data",
            "brave": local_app_data / "BraveSoftware" / "Brave-Browser" / "User Data"
        }

    @classmethod
    def resolve_profile_info(cls, user_data_dir: str | Path, profile_dir: str = "Default") -> dict[str, Any]:
        """
        Reads Chrome/Edge Local State and profile preferences to find the logged-in Gmail and name.
        """
        user_path = Path(user_data_dir)
        local_state = user_path / "Local State"

        result = {
            "account_name": "",
            "email": "",
            "browser": "chrome" if "Chrome" in str(user_path) else ("edge" if "Edge" in str(user_path) else "other"),
            "profile_dir": profile_dir,
            "user_data_dir": str(user_path),
            "is_valid": False,
            "error": ""
        }

        if not user_path.exists():
            result["error"] = f"Browser directory does not exist: {user_path}"
            return result

        profile_path = user_path / profile_dir
        if not profile_path.exists():
            # Check case-insensitive match or 'Default'
            found = False
            for d in user_path.iterdir():
                if d.is_dir() and d.name.lower() == profile_dir.lower():
                    profile_path = d
                    profile_dir = d.name
                    found = True
                    break
            if not found and profile_dir.lower() == "profile 1":
                # Often Profile 1 is 'Default' in Chrome
                default_p = user_path / "Default"
                if default_p.exists():
                    profile_path = default_p
                    profile_dir = "Default"
                    found = True

            if not found:
                result["error"] = f"Profile directory '{profile_dir}' not found on disk"
                return result

        result["is_valid"] = True

        # 1. Inspect Local State
        if local_state.exists():
            try:
                with open(local_state, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                info_cache = state_data.get("profile", {}).get("info_cache", {})

                match_info = info_cache.get(profile_dir)
                if not match_info:
                    # Case-insensitive lookup
                    for k, v in info_cache.items():
                        if k.lower() == profile_dir.lower():
                            match_info = v
                            break

                # If still not matched, check if only one profile exists
                if not match_info and len(info_cache) == 1:
                    match_info = next(iter(info_cache.values()))

                if match_info:
                    result["email"] = match_info.get("user_name", "") or match_info.get("email", "")
                    result["account_name"] = match_info.get("gaia_name") or match_info.get("name", "")
            except Exception as e:
                logger.warning(f"Failed to parse Local State in {user_path}: {e}")

        # 2. Inspect Profile Preferences if email is still empty
        if not result["email"]:
            pref_file = profile_path / "Preferences"
            if pref_file.exists():
                try:
                    with open(pref_file, "r", encoding="utf-8") as f:
                        pref_data = json.load(f)
                    
                    # Try google account info in preferences
                    acc_info = pref_data.get("account_info", [])
                    if isinstance(acc_info, list) and len(acc_info) > 0:
                        first = acc_info[0]
                        result["email"] = first.get("email", "")
                        if not result["account_name"]:
                            result["account_name"] = first.get("full_name", "") or first.get("given_name", "")

                    if not result["account_name"]:
                        result["account_name"] = pref_data.get("profile", {}).get("name", "")
                except Exception as e:
                    logger.warning(f"Failed to parse Preferences in {profile_path}: {e}")

        return result

    @classmethod
    def discover_all_browser_profiles(cls) -> list[dict[str, Any]]:
        """Scans all standard browser locations on this machine and returns discovered accounts."""
        discovered: list[dict[str, Any]] = []
        roots = cls.get_standard_browser_roots()

        for b_name, b_path in roots.items():
            if not b_path.exists():
                continue

            local_state = b_path / "Local State"
            if local_state.exists():
                try:
                    with open(local_state, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    info_cache = data.get("profile", {}).get("info_cache", {})
                    for p_dir, info in info_cache.items():
                        email = info.get("user_name", "")
                        name = info.get("gaia_name") or info.get("name", "")
                        discovered.append({
                            "browser": b_name,
                            "profile_dir": p_dir,
                            "user_data_dir": str(b_path),
                            "email": email,
                            "account_name": name or f"{b_name.title()} ({p_dir})",
                            "display_label": f"{name} ({email})" if email else f"{b_name.title()} ({p_dir})",
                            "is_valid": True
                        })
                except Exception as e:
                    logger.warning(f"Error scanning {b_name} Local State: {e}")

        return discovered

    @classmethod
    def sync_accounts_with_db(cls, db: Any) -> list[dict[str, Any]]:
        """
        Reads accounts_config.json, automatically enriches each account with real Google Account Name
        and Gmail address from browser profiles, and synchronizes them to the SQLite database.
        """
        config_path = Path(r"d:\Stock Automation\config\accounts_config.json")
        if not config_path.exists():
            return []

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                conf = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read accounts config: {e}")
            return []

        accounts = conf.get("accounts", [])
        updated_accounts: list[dict[str, Any]] = []

        # Also get all discovered profiles on the machine as smart fallbacks
        discovered = cls.discover_all_browser_profiles()

        for idx, acc in enumerate(accounts):
            profile_name = acc.get("profile_name", f"Account_{idx+1}")
            user_data = acc.get("chrome_user_data_dir", "")
            profile_dir = acc.get("profile_dir", "Default")
            tier = acc.get("tier", "free")
            pool_id = acc.get("pool_id")
            limit = acc.get("daily_points", 50 if tier == "free" else 0)
            enabled = acc.get("enabled", True)

            # Manual override from config if provided
            manual_email = acc.get("email", "")
            manual_name = acc.get("account_name", "")

            # Resolve from browser
            resolved = cls.resolve_profile_info(user_data, profile_dir)
            email = manual_email or resolved.get("email", "")
            account_name = manual_name or resolved.get("account_name", "")

            # If still missing and we have discovered profiles, match by index or name
            if not email and discovered:
                fallback = discovered[idx % len(discovered)]
                email = fallback.get("email", "")
                if not account_name:
                    account_name = fallback.get("account_name", "")

            if not account_name:
                account_name = email.split("@")[0].replace(".", " ").title() if email else profile_name

            browser_type = resolved.get("browser", "chrome")
            is_valid = resolved.get("is_valid", True)
            last_error = resolved.get("error", "")

            # Update DB
            db.upsert_account(
                profile_name=profile_name,
                account_name=account_name,
                email=email,
                tier=tier,
                pool_id=pool_id,
                daily_limit=limit,
                browser=browser_type,
                profile_dir=profile_dir,
                status="active" if (enabled and is_valid) else ("error" if not is_valid else "disabled"),
                last_error=last_error,
                action_hint="افتح المتصفح وسجل دخولك إلى Google لربط الجلسة" if not email else ""
            )

            updated_accounts.append({
                "profile_name": profile_name,
                "account_name": account_name,
                "email": email,
                "tier": tier,
                "pool_id": pool_id,
                "status": "active" if (enabled and is_valid) else "error",
                "error": last_error
            })

        logger.info(f"Synchronized {len(updated_accounts)} accounts with real identities into database.")
        return updated_accounts
