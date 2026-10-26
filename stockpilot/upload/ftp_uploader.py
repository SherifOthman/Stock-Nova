"""
Adobe Stock FTP Upload Manager.
Uploads batches of verified images to Adobe Stock via secure FTPS/FTP.
Moves uploaded batches to 'workspace/4_Uploaded_Awaiting_Submit'.
"""

from __future__ import annotations

import ftplib
import shutil
import time
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("ftp_uploader")


class AdobeFTPUploader:
    """Handles FTP uploads to Adobe Stock."""

    def __init__(self) -> None:
        self.db = Database()
        # Retrieve credentials from secure local SQLite database or config
        from stockpilot.core.security import get_secure_credential
        cred = get_secure_credential(self.db, "ftp")
        meta = (cred.get("metadata") if cred else {}) or {}

        self.host = meta.get("host") or Config.get("ftp.host", "ftp.contributor.adobestock.com")
        self.port = int(meta.get("port") or Config.get("ftp.port", 21))
        self.username = (cred.get("username") if cred else None) or Config.get("ftp.username", "")
        self.password = (cred.get("secret") if cred else None) or Config.get_ftp_password()
        self.remote_dir = Config.get("ftp.remote_dir", "/")
        self.timeout = Config.get("ftp.timeout", 30)

    def is_configured(self) -> bool:
        return bool(self.username and self.password)

    def upload_batch(self, batch_dir: Path, target_awaiting_dir: Path) -> bool:
        """
        Uploads all images and the CSV from batch_dir via FTP to Adobe Stock,
        then moves the entire batch folder to target_awaiting_dir.
        """
        if not self.is_configured():
            logger.warning("FTP credentials not configured in settings.yaml! Simulation mode enabled.")
            # In simulation / test mode, move folder to awaiting submission
            dest = target_awaiting_dir / batch_dir.name
            target_awaiting_dir.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.move(str(batch_dir), str(dest))
            return True

        files_to_upload = list(batch_dir.glob("*.jpg")) + list(batch_dir.glob("*.csv"))
        if not files_to_upload:
            logger.warning(f"No uploadable files found in {batch_dir}")
            return False

        logger.info(f"Connecting to Adobe Stock FTP: {self.host} ({self.username})...")

        try:
            ftp = ftplib.FTP()
            ftp.connect(self.host, self.port, timeout=self.timeout)
            ftp.login(self.username, self.password)
            ftp.set_pasv(True)

            if self.remote_dir and self.remote_dir != "/":
                ftp.cwd(self.remote_dir)

            for file_path in files_to_upload:
                logger.info(f"Uploading via FTP: {file_path.name}...")
                with open(file_path, "rb") as fp:
                    ftp.storbinary(f"STOR {file_path.name}", fp, blocksize=8192)

            ftp.quit()
            logger.info(f"Batch {batch_dir.name} ({len(files_to_upload)} files) uploaded successfully to FTP.")

            # Move batch folder to awaiting submit
            target_awaiting_dir.mkdir(parents=True, exist_ok=True)
            dest = target_awaiting_dir / batch_dir.name
            shutil.move(str(batch_dir), str(dest))

            # Update DB
            with self.db.get_connection() as conn:
                conn.execute(
                    "UPDATE batches SET status = 'uploaded', uploaded_at = CURRENT_TIMESTAMP WHERE batch_id = ?",
                    (batch_dir.name,)
                )

            return True

        except Exception as e:
            logger.error(f"FTP Upload failed for {batch_dir.name}: {e}")
            return False
