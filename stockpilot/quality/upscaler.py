"""
Headless Upscayl CLI Wrapper.
Runs Upscayl silently via subprocess using the verified High Fidelity model (high-fidelity-4x).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("upscaler")


class Upscaler:
    """Headless CLI manager for Upscayl."""

    def __init__(self) -> None:
        self.bin_path = Config.get_path(
            "upscayl.bin_path",
            Path(r"C:\Program Files\Upscayl\resources\bin\upscayl-bin.exe")
        )
        self.models_dir = Config.get_path(
            "upscayl.models_dir",
            Path(r"C:\Program Files\Upscayl\resources\models")
        )
        self.default_model = Config.get("upscayl.default_model", "high-fidelity-4x")
        self.default_scale = Config.get("upscayl.default_scale", 2)
        self.timeout = Config.get("upscayl.timeout_seconds", 600)

    def is_available(self) -> bool:
        return self.bin_path.exists() and self.models_dir.exists()

    def _kill_lingering_instances(self) -> None:
        """Kills any stuck or orphan upscayl-bin processes to free GPU VRAM."""
        try:
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/IM", "upscayl-bin.exe"],
                capture_output=True,
                check=False
            )
        except Exception:
            pass

    def upscale(
        self,
        input_path: Path,
        output_dir: Path,
        model: str | None = None,
        scale: int | None = None,
        output_format: str = "jpg"
    ) -> Path | None:
        """
        Runs headless upscaling via upscayl-bin.exe.
        Returns the path to the upscaled image or None on failure.
        """
        if not self.is_available():
            logger.error(f"Upscayl not configured properly at {self.bin_path}")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        target_model = model or self.default_model
        
        # Target Scaling: Fixed 2x (Optimal 4K / ~17MP) across all images.
        # Rationale: Raw images are already 2048x2048 (square) or ~2750x1500 (landscape).
        # Upscaling 2x gives 4096x4096 or 5500x3000 (~16.8 MP), the exact commercial 4K standard.
        # Upscaling 4x is strictly avoided because 65MP+ inflates file size (>50MB),
        # causes interpolation smoothing artifacts, and triggers rejection on Adobe/Freepik.
        target_scale = scale if scale is not None else (self.default_scale or 2)

        target_output_file = output_dir / f"{input_path.stem}.{output_format}"

        cmd = [
            str(self.bin_path),
            "-i", str(input_path),
            "-o", str(target_output_file),
            "-s", str(target_scale),
            "-m", str(self.models_dir),
            "-n", target_model,
            "-f", output_format
        ]

        logger.info(f"Starting silent Upscayl [{target_model} {target_scale}x] on: {input_path.name}")
        start_time = time.perf_counter()
        timeout_sec = max(self.timeout, 600)

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                check=False
            )
            elapsed = time.perf_counter() - start_time

            if res.returncode == 0:
                if target_output_file.exists():
                    logger.info(f"Upscaled successfully in {elapsed:.2f}s -> {target_output_file.name}")
                    return target_output_file
                # Fallback check for any match in output_dir
                expected = list(output_dir.glob(f"{input_path.stem}*.{output_format}"))
                if expected:
                    out_file = expected[0]
                    logger.info(f"Upscaled successfully in {elapsed:.2f}s -> {out_file.name}")
                    return out_file
                logger.warning(f"Upscayl succeeded but output file not found in {output_dir}")
                return None
            else:
                logger.error(f"Upscayl failed (exit code {res.returncode}): {res.stderr}")
                return None

        except subprocess.TimeoutExpired:
            logger.error(f"Upscayl process timed out after {self.timeout}s on {input_path.name}")
            return None
        except Exception as e:
            logger.error(f"Exception during Upscayl execution: {e}")
            return None
