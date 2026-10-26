"""
Video Audio Stripper and Formatter for Stock Assets.
Adobe Stock strictly rejects video clips containing audio tracks.
This module strips the audio track cleanly using ffmpeg (stream copy - zero quality loss)
ensuring 100% compliance with Adobe Stock technical requirements.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from stockpilot.core.logger import get_logger

logger = get_logger("video_processor")


class VideoProcessor:
    """Handles stock video processing and audio stripping."""

    @staticmethod
    def get_ffmpeg_path() -> str | None:
        """Finds ffmpeg executable in PATH or common Windows locations."""
        found = shutil.which("ffmpeg")
        if found:
            return found
        # Common fallback paths on Windows
        fallbacks = [
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
            Path(r"d:\Stock Automation\tools\ffmpeg.exe"),
        ]
        for p in fallbacks:
            if p.exists():
                return str(p)
        return None

    @classmethod
    def strip_audio(cls, video_path: Path, output_path: Path | None = None) -> Path:
        """
        Removes the audio stream from a video file without re-encoding video frames.
        Uses ffmpeg: -an -c:v copy
        """
        if not video_path.exists():
            return video_path

        ffmpeg = cls.get_ffmpeg_path()
        if not ffmpeg:
            logger.warning("ffmpeg not detected on system. Skipping audio strip (install ffmpeg to strip audio).")
            return video_path

        if output_path is None:
            output_path = video_path.parent / f"{video_path.stem}_noaudio{video_path.suffix}"

        cmd = [
            ffmpeg,
            "-y",
            "-i", str(video_path),
            "-an",           # Drop audio
            "-c:v", "copy",   # Copy video stream directly without quality degradation
            str(output_path)
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
            if res.returncode == 0 and output_path.exists():
                logger.info(f"Stripped audio successfully: {video_path.name} -> {output_path.name}")
                # Replace original with stripped version
                video_path.unlink()
                output_path.rename(video_path)
                return video_path
            else:
                logger.error(f"ffmpeg error: {res.stderr[:200]}")
                return video_path
        except Exception as e:
            logger.error(f"Failed to strip audio: {e}")
            return video_path
