"""
Freepik Platform Adapter (Standby Mode).
Kept ready in the codebase for activation once the 150-approved milestone is reached on Adobe Stock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stockpilot.platforms.base import BasePlatformAdapter
from stockpilot.core.logger import get_logger

logger = get_logger("freepik_platform")


class FreepikPlatform(BasePlatformAdapter):
    """Freepik integration adapter (currently standby)."""

    def __init__(self) -> None:
        super().__init__("freepik")
        self._enabled = False

    def is_active(self) -> bool:
        return self._enabled

    def activate(self) -> None:
        self._enabled = True
        logger.info("Freepik platform adapter ACTIVATED!")

    def get_submission_limit(self) -> int:
        return 100 if self._enabled else 0

    def prepare_metadata_file(self, batch_dir: Path, assets: list[dict[str, Any]]) -> Path:
        # Freepik standard CSV
        csv_path = batch_dir / "freepik_metadata.csv"
        # Implementation ready for when active
        return csv_path

    def upload_batch(self, batch_dir: Path) -> bool:
        if not self._enabled:
            logger.info("Freepik is currently on standby. Skipping upload.")
            return False
        return True

    def fetch_review_outcomes(self) -> list[dict[str, Any]]:
        return []
