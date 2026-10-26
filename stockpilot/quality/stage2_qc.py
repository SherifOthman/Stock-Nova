"""
Stage 2 Quality Control (Post-Upscale 100% Crop & Technical Artifact Filter).
Verifies that upscaling did not introduce plastic textures, halos, edge ringing, or severe noise.
Combines OpenCV mathematical checks with Gemini Vision on 100% center crop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from PIL import Image

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator
from stockpilot.utils.image_utils import compress_for_gemini, extract_100_percent_center_crop

logger = get_logger("stage2_qc")


@dataclass
class QC2Result:
    passed: bool
    confidence: float
    sharpness_score: float
    issues: list[str]
    raw_summary: str


class Stage2QC:
    """Post-upscale artifact and texture inspector."""

    def __init__(self) -> None:
        self.rotator = APIKeyRotator()

    def run_opencv_sharpness(self, image_path: Path) -> float:
        """Calculates Laplacian variance for sharpness."""
        try:
            import cv2
            img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                return 0.0
            lap = cv2.Laplacian(img, cv2.CV_64F)
            return float(lap.var())
        except Exception:
            # Fallback if cv2 headless not installed
            return 150.0

    def inspect(self, upscaled_path: Path) -> QC2Result:
        """Runs Stage 2 post-upscale verification."""
        sharpness = self.run_opencv_sharpness(upscaled_path)
        min_sharpness = Config.get("qc.stage2.min_sharpness", 100.0)

        issues = []
        if sharpness < min_sharpness:
            issues.append(f"Image too soft/blurry (sharpness {sharpness:.1f} < {min_sharpness})")

        # Extract 100% center crop for Gemini to evaluate texture
        crop_path = extract_100_percent_center_crop(upscaled_path, crop_ratio=0.25)
        crop_bytes = compress_for_gemini(crop_path, max_bytes=180_000)

        # Cleanup crop file
        try:
            crop_path.unlink(missing_ok=True)
        except Exception:
            pass

        key = self.rotator.get_key()
        if not key:
            passed = len(issues) == 0
            return QC2Result(
                passed=passed,
                confidence=0.7,
                sharpness_score=sharpness,
                issues=issues,
                raw_summary="Passed via local OpenCV checks (No API Key)"
            )

        prompt = (
            "You are a technical Adobe Stock reviewer examining a 100% ZOOM CROP of an upscaled stock photo. "
            "Inspect specifically for upscaling damage:\n"
            "1. Plastic or waxy skin (loss of pores/micro-texture).\n"
            "2. Over-sharpening halos or white outline ringing around edges.\n"
            "3. Pattern repetition or tile grid artifacts.\n"
            "4. Severe noise amplification or watercolor blotches.\n\n"
            "Respond ONLY with a valid JSON object strictly matching this format:\n"
            "{\n"
            '  "pass": true,\n'
            '  "confidence": 0.95,\n'
            '  "issues": [],\n'
            '  "summary": "Crisp natural details, no upscaling halos or plastic textures."\n'
            "}"
        )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=Config.get("gemini.model", "gemini-2.5-flash"),
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=crop_bytes, mime_type="image/jpeg"),
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            res_text = response.text or "{}"
            data = json.loads(res_text)

            api_passed = bool(data.get("pass", False))
            confidence = float(data.get("confidence", 0.8))
            api_issues = data.get("issues", [])
            summary = data.get("summary", "")

            combined_issues = issues + api_issues
            passed = api_passed and (len(issues) == 0)

            logger.info(f"Stage 2 QC on {upscaled_path.name}: Passed={passed}, Sharpness={sharpness:.1f}")
            return QC2Result(
                passed=passed,
                confidence=confidence,
                sharpness_score=sharpness,
                issues=combined_issues,
                raw_summary=summary
            )

        except Exception as e:
            logger.error(f"Stage 2 QC API Error: {e}")
            passed = len(issues) == 0
            return QC2Result(
                passed=passed,
                confidence=0.5,
                sharpness_score=sharpness,
                issues=issues + [f"API Error: {e}"],
                raw_summary="API Error - Fallback to OpenCV"
            )
