"""
Base Platform Adapter Interface for Stock Agencies.
Enables pluggable architecture to support Adobe Stock now, Freepik on standby,
and easily add Shutterstock, Pond5, Envato later without altering the core pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BasePlatformAdapter(ABC):
    """Abstract interface for all stock platform handlers."""

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name

    @abstractmethod
    def is_active(self) -> bool:
        """Returns True if this platform is currently enabled for uploads."""
        pass

    @abstractmethod
    def get_submission_limit(self) -> int:
        """Returns the current remaining submission limit on the platform."""
        pass

    @abstractmethod
    def prepare_metadata_file(self, batch_dir: Path, assets: list[dict[str, Any]]) -> Path:
        """Generates platform-specific metadata file (e.g. CSV)."""
        pass

    @abstractmethod
    def upload_batch(self, batch_dir: Path) -> bool:
        """Uploads the batch files via FTP or API to the platform."""
        pass

    @abstractmethod
    def fetch_review_outcomes(self) -> list[dict[str, Any]]:
        """Scrapes or queries review outcomes (accepted/rejected + reasons)."""
        pass
