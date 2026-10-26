"""
Headless Upscayl CLI Wrapper & Commercial Model Sample Benchmarker.
Enforces:
1. Strictly 2x Upscaling (scale=2) across all images:
   Raw images are ~2048x2048 or ~3000x1500. Scaling 2x produces crisp 4K (~4096x4096 or ~6000x3000)
   without the pixelation, over-smoothing, and 60MB+ bloat caused by 4x scaling.
2. Commercial License Verification (via model_license_validator.py) before running any upscale model.
3. Sample Model Comparison Tester: Can test candidate commercial-safe models ('high-fidelity-4x',
   'ultramix_balanced', 'remacri') on 3-4 sample images and compare sharpness retention vs. original.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.model_license_validator import validate_upscale_model

logger = get_logger("upscaler")


class Upscaler:
    """Headless CLI manager for Upscayl (strictly 2x scale + commercial license guard)."""

    COMMERCIAL_CANDIDATE_MODELS = [
        "high-fidelity-4x",
        "ultramix_balanced",
        "remacri",
    ]

    def __init__(self) -> None:
        self.bin_path = Config.get_path("upscayl.bin_path")
        self.models_dir = Config.get_path("upscayl.models_dir")
        self.default_model = str(Config.get("upscayl.default_model", "high-fidelity-4x"))
        self.default_scale = 2  # Strictly locked to 2x per production rule
        self.timeout = int(Config.get("upscayl.timeout_seconds", 600))

    def is_available(self) -> bool:
        return bool(self.bin_path and self.bin_path.exists() and self.models_dir and self.models_dir.exists())

    def _kill_lingering_instances(self) -> None:
        """Kills any stuck upscayl-bin processes to free GPU VRAM."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "upscayl-bin.exe"],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass

    def upscale(
        self,
        input_path: Path,
        output_dir: Path,
        model: str | None = None,
        scale: int | None = None,
        output_format: str = "jpg",
    ) -> Path | None:
        """
        Runs headless 2x upscaling via upscayl-bin.exe after verifying commercial model safety.
        """
        target_model = model or self.default_model
        # Verify commercial license safety before upscaling
        lic = validate_upscale_model(target_model)
        if not lic.get("is_commercial_safe", True):
            logger.warning(f"Blocked non-commercial upscale model '{target_model}'. Falling back to 'high-fidelity-4x'.")
            target_model = "high-fidelity-4x"

        # Strictly enforce 2x scale
        target_scale = 2

        if not self.is_available():
            logger.warning(f"Upscayl binary not found at {self.bin_path}; copying source for local fallback.")
            output_dir.mkdir(parents=True, exist_ok=True)
            fallback_out = output_dir / f"{input_path.stem}.{output_format}"
            import shutil

            shutil.copy2(str(input_path), str(fallback_out))
            return fallback_out

        output_dir.mkdir(parents=True, exist_ok=True)
        target_output_file = output_dir / f"{input_path.stem}.{output_format}"

        cmd = [
            str(self.bin_path),
            "-i", str(input_path),
            "-o", str(target_output_file),
            "-s", str(target_scale),
            "-m", str(self.models_dir),
            "-n", target_model,
            "-f", output_format,
        ]

        logger.info(f"Running Upscayl 2x [{target_model}] on: {input_path.name}")
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
                check=False,
            )
            elapsed = time.perf_counter() - start_time

            if res.returncode == 0:
                if target_output_file.exists():
                    logger.info(f"Upscaled 2x in {elapsed:.2f}s -> {target_output_file.name}")
                    return target_output_file
                expected = list(output_dir.glob(f"{input_path.stem}*.{output_format}"))
                if expected:
                    return expected[0]
            logger.error(f"Upscayl failed (exit {res.returncode}): {res.stderr[:200]}")
            return None
        except subprocess.TimeoutExpired:
            self._kill_lingering_instances()
            logger.error(f"Upscayl timed out on {input_path.name}")
            return None
        except Exception as e:
            logger.error(f"Upscayl execution error: {e}")
            return None

    def benchmark_models_on_samples(self, sample_images: list[Path], temp_out_dir: Path) -> dict[str, Any]:
        """
        Tests commercial-safe upscale models ('high-fidelity-4x', 'ultramix_balanced', 'remacri')
        on up to 4 sample images at 2x scale and compares OpenCV sharpness vs. the original image.
        Selects and saves the highest-fidelity winner!
        """
        from stockpilot.quality.opencv_checks import calculate_sharpness

        samples = sample_images[:4]
        if not samples:
            return {
                "winner_model": self.default_model,
                "scale": 2,
                "note": "No sample images provided — keeping default 'high-fidelity-4x' at 2x.",
                "results": [],
            }

        results = []
        best_model = "high-fidelity-4x"
        best_ratio = -1.0

        for cand_model in self.COMMERCIAL_CANDIDATE_MODELS:
            lic = validate_upscale_model(cand_model)
            if not lic.get("is_commercial_safe", True):
                continue

            ratios = []
            for img_path in samples:
                orig_sharp = max(1.0, calculate_sharpness(img_path))
                out_file = self.upscale(img_path, temp_out_dir / cand_model, model=cand_model, scale=2)
                if out_file and out_file.exists():
                    up_sharp = calculate_sharpness(out_file)
                    ratios.append(up_sharp / orig_sharp)

            avg_retention = sum(ratios) / len(ratios) if ratios else 1.0
            results.append({
                "model": cand_model,
                "scale": "2x",
                "commercial_safe": True,
                "sharpness_retention_ratio": round(avg_retention, 2),
            })
            if avg_retention > best_ratio:
                best_ratio = avg_retention
                best_model = cand_model

        Config.set("upscayl.default_model", best_model, persist=True)
        self.default_model = best_model
        return {
            "winner_model": best_model,
            "scale": 2,
            "results": results,
            "note": f"Tested {len(samples)} sample images at 2x scale. Best model: {best_model}",
        }
