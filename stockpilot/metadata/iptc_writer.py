"""
ExifTool and IPTC Metadata Writer for Adobe Stock.
Embeds SEO Title and 45-50 Keywords directly into JPG files using ExifTool,
ensuring Adobe Stock auto-populates metadata on FTP upload.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("iptc_writer")


class IPTCWriter:
    """Manages IPTC/XMP injection via local ExifTool CLI."""

    def __init__(self) -> None:
        self.exiftool_path = Config.get_path("paths.exiftool", Path(r"d:\Stock Automation\tools\exiftool.exe"))

    def is_available(self) -> bool:
        """Verifies ExifTool is installed and executable."""
        if not self.exiftool_path.exists():
            return False
        try:
            res = subprocess.run([str(self.exiftool_path), "-ver"], capture_output=True, text=True, check=False)
            return res.returncode == 0
        except Exception:
            return False

    def write_metadata(
        self,
        image_path: Path,
        title: str,
        keywords: list[str],
        description: str | None = None
    ) -> bool:
        """
        Injects Title and Keywords into IPTC, XMP, and EXIF tags.
        """
        if not self.is_available():
            logger.error(f"ExifTool not found at {self.exiftool_path}")
            return False

        if not description:
            description = title

        # Build args
        cmd = [
            str(self.exiftool_path),
            "-overwrite_original",
            "-charset", "iptc=UTF8",
            f"-IPTC:ObjectName={title}",
            f"-IPTC:Caption-Abstract={description}",
            f"-XMP:Title={title}",
            f"-XMP:Description={description}",
            f"-EXIF:ImageDescription={title}",
        ]

        # Add keywords as separate -Keywords and -Subject tags
        for kw in keywords:
            clean_kw = kw.strip()
            if clean_kw:
                cmd.append(f"-IPTC:Keywords={clean_kw}")
                cmd.append(f"-XMP:Subject={clean_kw}")

        cmd.append(str(image_path))

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
            if res.returncode == 0:
                logger.info(f"IPTC metadata injected successfully into: {image_path.name}")
                return True
            else:
                logger.error(f"ExifTool error on {image_path.name}: {res.stderr}")
                return False
        except Exception as e:
            logger.error(f"Failed to execute ExifTool: {e}")
            return False
