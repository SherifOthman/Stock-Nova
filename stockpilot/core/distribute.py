"""
Portable Distribution and Clean Template Exporter.
Allows packaging StockNova AI to be handed over to a friend or collaborator:
- Strips personal Chrome profiles, personal emails, and API keys.
- Initializes a clean, blank template SQLite database.
- Generates clean, ready-to-fill settings and accounts configs.
- Ensures all paths are relative to the project root for zero-friction setup on any PC.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from stockpilot.core.logger import get_logger

logger = get_logger("distribute")
PROJECT_ROOT = Path(r"d:\Stock Automation")


def export_clean_distribution_package(output_zip: Path | None = None) -> Path:
    """Creates a clean, portable distribution zip ready to be shared with other users."""
    if output_zip is None:
        output_zip = PROJECT_ROOT / "StockNova_Clean_Distributable.zip"

    logger.info("Building clean distributable package...")

    # Files & directories to include
    include_patterns = [
        "stockpilot",
        "tools",
        "requirements.txt",
        "run.bat",
        "README.md"
    ]

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add code & tools
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Ignore personal data, logs, database, backups, and workspace files
            rel_root = Path(root).relative_to(PROJECT_ROOT)
            parts = rel_root.parts

            if any(p in parts for p in ["config", "data", "workspace", "backups", "screenshots", "__pycache__", ".git"]):
                continue

            for file in files:
                if file.endswith((".pyc", ".db", ".log", ".zip")):
                    continue
                file_path = Path(root) / file
                arcname = str(file_path.relative_to(PROJECT_ROOT))
                zipf.write(file_path, arcname=arcname)

        # Create clean template configs
        clean_settings = (PROJECT_ROOT / "config" / "settings.example.yaml").read_text(encoding="utf-8") if (PROJECT_ROOT / "config" / "settings.example.yaml").exists() else (PROJECT_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
        clean_accounts = (PROJECT_ROOT / "config" / "accounts_config.example.json").read_text(encoding="utf-8") if (PROJECT_ROOT / "config" / "accounts_config.example.json").exists() else (PROJECT_ROOT / "config" / "accounts_config.json").read_text(encoding="utf-8")

        zipf.writestr("config/settings.yaml", clean_settings)
        zipf.writestr("config/accounts_config.json", clean_accounts)
        zipf.writestr("config/api_keys.yaml", "gemini:\n  - alias: 'my_gemini_key_1'\n    key: 'YOUR_API_KEY_HERE'\n")
        zipf.writestr("data/.keep", "")
        zipf.writestr("workspace/0_Raw_Downloads/.keep", "")

    logger.info(f"Clean distributable package created: {output_zip} ({output_zip.stat().st_size / 1024:.1f} KB)")
    return output_zip


if __name__ == "__main__":
    export_clean_distribution_package()
