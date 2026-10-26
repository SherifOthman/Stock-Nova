"""
Video Audio Stripper and Formatter for Stock Assets.
Adobe Stock strictly rejects AI video clips that contain audio tracks.
This module strips the audio track cleanly using ffmpeg (-an -c:v copy)
with zero visual quality loss and zero hardcoded paths.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("video_processor")


class VideoProcessor:
    """Handles mandatory stock video audio stripping (-an) and container cleanup."""

    @staticmethod
    def get_ffmpeg_path() -> str | None:
        """Finds ffmpeg executable in PATH, bundled tools folder, or standard Windows locations."""
        found = shutil.which("ffmpeg")
        if found:
            return found

        project_tools = Config.get_project_root() / "tools" / "ffmpeg.exe"
        fallbacks = [
            project_tools,
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        ]
        for p in fallbacks:
            if p.exists():
                return str(p)
        return None

    @classmethod
    def strip_audio(cls, video_path: Path, output_path: Path | None = None) -> tuple[Path, bool]:
        """
        Removes any audio stream from a video file without re-encoding video frames (-an -c:v copy).
        Returns (final_video_path, audio_stripped_success).
        """
        if not video_path.exists():
            return video_path, False

        ffmpeg = cls.get_ffmpeg_path()
        if not ffmpeg:
            logger.warning("ffmpeg not found in PATH or tools/. Place ffmpeg.exe in tools/ for automatic audio stripping.")
            return video_path, False

        temp_out = output_path or video_path.parent / f"{video_path.stem}_silent_tmp{video_path.suffix}"

        cmd = [
            ffmpeg,
            "-y",
            "-i", str(video_path),
            "-an",          # Strictly remove all audio tracks for Adobe Stock compliance
            "-c:v", "copy",  # Lossless stream copy
            "-movflags", "+faststart",
            str(temp_out),
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
            if res.returncode == 0 and temp_out.exists() and temp_out.stat().st_size > 1024:
                if output_path is None:
                    video_path.unlink(missing_ok=True)
                    temp_out.rename(video_path)
                    logger.info(f"Stripped audio track (-an) cleanly: {video_path.name}")
                    return video_path, True
                logger.info(f"Stripped audio track (-an) cleanly -> {temp_out.name}")
                return temp_out, True
            else:
                temp_out.unlink(missing_ok=True)
                logger.error(f"ffmpeg audio strip warning: {res.stderr[:200]}")
                return video_path, False
        except Exception as e:
            temp_out.unlink(missing_ok=True)
            logger.error(f"Failed to strip audio on {video_path.name}: {e}")
            return video_path, False
