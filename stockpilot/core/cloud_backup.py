"""
Google Drive and Cloud Disaster Recovery Backup Engine.
Creates encrypted or compressed snapshots of:
- SQLite Database (google_dots.db)
- Creative Strategy & Blacklists (creative_strategy.json)
- Accounts configuration (accounts_config.json)
- Strategy learnings
Backs them up to a designated cloud sync directory / Google Drive location,
ensuring full state and intelligence can be restored in seconds on a new machine.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("cloud_backup")


class CloudBackupEngine:
    """Manages snapshots and syncing to Google Drive or local backup root."""

    DEFAULT_BACKUP_LOCAL_DIR = Path(r"d:\Stock Automation\backups")

    def __init__(self) -> None:
        self.db_path = Config.get_path("paths.database", Path(r"d:\Stock Automation\data\google_dots.db"))
        self.config_dir = Path(r"d:\Stock Automation\config")
        self.gdrive_sync_folder = self._detect_gdrive_folder()

    def _detect_gdrive_folder(self) -> Path:
        """Detects Google Drive desktop client sync folder if installed, or falls back to local backup folder."""
        # Common Google Drive locations on Windows
        user_home = Path.home()
        candidates = [
            user_home / "Google Drive",
            user_home / "GoogleDrive",
            Path(r"G:\My Drive\StockNova_Backups"),
            Path(r"C:\Users\eleml\Google Drive\StockNova_Backups"),
            self.DEFAULT_BACKUP_LOCAL_DIR / "cloud_sync"
        ]
        for c in candidates:
            if c.parent.exists() or c.exists():
                c.mkdir(parents=True, exist_ok=True)
                return c

        self.DEFAULT_BACKUP_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        return self.DEFAULT_BACKUP_LOCAL_DIR

    def create_snapshot(self) -> Path:
        """
        Bundles database and strategy files into a timestamped zip archive.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"StockNova_Backup_{timestamp}.zip"

        target_dir = self.gdrive_sync_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        zip_path = target_dir / backup_filename

        logger.info(f"Creating snapshot at: {zip_path}...")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            # 1. Database
            if self.db_path.exists():
                zipf.write(self.db_path, arcname="google_dots.db")

            # 2. Config files & Blacklists
            if self.config_dir.exists():
                for cfg_file in self.config_dir.glob("*.*"):
                    zipf.write(cfg_file, arcname=f"config/{cfg_file.name}")

        logger.info(f"Snapshot created successfully ({zip_path.stat().st_size / 1024:.1f} KB).")
        # Keep only the last 15 backups to save space
        self._prune_old_backups(target_dir, keep=15)
        return zip_path

    def restore_from_snapshot(self, snapshot_path: Path) -> bool:
        """Restores DB and configs from a backup zip archive."""
        if not snapshot_path.exists():
            logger.error(f"Snapshot file not found: {snapshot_path}")
            return False

        logger.info(f"Restoring system from snapshot: {snapshot_path.name}...")
        try:
            with zipfile.ZipFile(snapshot_path, "r") as zipf:
                for member in zipf.namelist():
                    if member == "google_dots.db":
                        self.db_path.parent.mkdir(parents=True, exist_ok=True)
                        with zipf.open(member) as src, open(self.db_path, "wb") as dst:
                            dst.write(src.read())
                    elif member.startswith("config/"):
                        dest_file = self.config_dir / Path(member).name
                        self.config_dir.mkdir(parents=True, exist_ok=True)
                        with zipf.open(member) as src, open(dest_file, "wb") as dst:
                            dst.write(src.read())

            logger.info("System successfully restored from snapshot!")
            return True
        except Exception as e:
            logger.error(f"Failed to restore from snapshot: {e}")
            return False

    def _prune_old_backups(self, folder: Path, keep: int = 15) -> None:
        """Removes older backup archives beyond the keep count."""
        backups = sorted(list(folder.glob("StockNova_Backup_*.zip")), key=lambda p: p.stat().st_mtime)
        if len(backups) > keep:
            for old in backups[:-keep]:
                try:
                    old.unlink()
                except Exception:
                    pass
