"""
Adobe Stock Platform Adapter.
Active primary target for StockPilot / Google Dots.
Handles Adobe CSV formatting, FTP upload, and review outcome tracking.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from stockpilot.platforms.base import BasePlatformAdapter
from stockpilot.upload.ftp_uploader import AdobeFTPUploader
from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.metadata.category_classifier import CategoryClassifier

logger = get_logger("adobe_platform")


class AdobeStockPlatform(BasePlatformAdapter):
    """Primary stock target implementation."""

    def __init__(self) -> None:
        super().__init__("adobe_stock")
        self.ftp_uploader = AdobeFTPUploader()

    def is_active(self) -> bool:
        return True

    def get_submission_limit(self) -> int:
        # Default baseline or retrieved from DB / CDP portal tracking
        return Config.get("qc.demand_limiter.default_adobe_limit", 30)

    def prepare_metadata_file(self, batch_dir: Path, assets: list[dict[str, Any]]) -> Path:
        """Writes adobe_stock_metadata.csv inside the batch folder."""
        csv_path = batch_dir / "adobe_stock_metadata.csv"
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])

            for item in assets:
                fname = item["filename"]
                title = item.get("title", "")
                kws = item.get("keywords", [])
                kws_str = ", ".join(kws) if isinstance(kws, list) else str(kws)
                cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(
                    title=title,
                    keywords=kws_str,
                    explicit_category=item.get("category"),
                    concept=item.get("concept_id") or ""
                )
                releases = item.get("releases", "")
                writer.writerow([fname, title, kws_str, cat_id, releases])

        logger.info(f"Adobe Stock metadata CSV written: {csv_path.name}")
        return csv_path

    def upload_batch(self, batch_dir: Path) -> bool:
        """Uploads via FTP using the configured credentials."""
        awaiting_dir = Config.get_path("paths.workspace_root") / "4_Uploaded_Awaiting_Submit"
        return self.ftp_uploader.upload_batch(batch_dir, awaiting_dir)

    def fetch_review_outcomes(self) -> list[dict[str, Any]]:
        """
        Placeholder for automated CDP scraping of Accepted/Not Accepted tabs.
        Returns list of { 'asset_id': str, 'status': 'accepted'|'rejected', 'reason': str }
        """
        return []
