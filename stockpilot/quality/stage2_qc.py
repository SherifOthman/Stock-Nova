"""
Stage 2 Quality Control (Post-Upscale 100% Crop & Calibrated 3-Tier Decision Filter).
Verifies that 2x upscaling produced crisp 4K details without plastic textures, halos, or noise.
Calibrated 3-Tier Output:
- 'approved' (Score 80-100): Ready for Adobe Stock & Freepik CSV export.
- 'borderline' (Score 60-79): Kept in 'Needs Quick Look' filter in Review Queue so good work is never lost.
- 'rejected' (Score <60): Moved to Rejected folder with exact defect reason logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator
from stockpilot.utils.image_utils import compress_for_gemini, extract_100_percent_center_crop

logger = get_logger("stage2_qc")


@dataclass
class QC2Result:
    passed: bool
    qc_tier: str  # 'approved', 'borderline', or 'rejected'
    score: float
    confidence: float
    sharpness_score: float
    issues: list[str]
    raw_summary: str


class Stage2QC:
    """Post-upscale calibrated 3-tier artifact and texture inspector."""

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
            return 140.0

    def inspect(self, upscaled_path: Path) -> QC2Result:
        """Runs calibrated Stage 2 post-upscale verification."""
        sharpness = self.run_opencv_sharpness(upscaled_path)
        min_sharpness = float(Config.get("qc.stage2.min_sharpness", 100.0))
        borderline_sharpness = float(Config.get("qc.stage2.borderline_sharpness", 80.0))

        issues: list[str] = []
        is_soft_borderline = False
        is_hard_blur = False

        if sharpness < borderline_sharpness:
            is_hard_blur = True
            issues.append(f"Image too blurry (sharpness {sharpness:.1f} < {borderline_sharpness})")
        elif sharpness < min_sharpness:
            is_soft_borderline = True
            issues.append(f"Slightly soft texture (sharpness {sharpness:.1f} vs target {min_sharpness})")

        crop_path = extract_100_percent_center_crop(upscaled_path, crop_ratio=0.25)
        crop_bytes = compress_for_gemini(crop_path, max_bytes=180_000)

        try:
            crop_path.unlink(missing_ok=True)
        except Exception:
            pass

        key = self.rotator.get_key()
        if not key:
            if is_hard_blur:
                tier, passed, sc = "rejected", False, 45.0
            elif is_soft_borderline:
                tier, passed, sc = "borderline", True, 72.0
            else:
                tier, passed, sc = "approved", True, 88.0
            return QC2Result(
                passed=passed,
                qc_tier=tier,
                score=sc,
                confidence=0.75,
                sharpness_score=round(sharpness, 1),
                issues=issues,
                raw_summary="Evaluated via local OpenCV sharpness check",
            )

        prompt = (
            "You are a calibrated Adobe Stock & Freepik Quality Inspector examining a 100% ZOOM CROP of a 2x upscaled 4K image.\n"
            "Be accurate: do NOT reject good commercial images over tiny harmless details, and do NOT pass clearly defective images.\n"
            "Inspect for:\n"
            "1. Severe plastic/waxy smoothing or loss of natural micro-texture.\n"
            "2. Strong white outline halos or ringing artifacts from upscaling.\n"
            "3. Visible grid/tile seams or severe noise blotches.\n"
            "Score from 0 to 100:\n"
            "- 80 to 100: 'approved' (crisp, natural 4K commercial quality)\n"
            "- 60 to 79: 'borderline' (usable but has minor softness or slight halo — flag for quick human look)\n"
            "- 0 to 59: 'rejected' (severe artifacts, blurry, or damaged texture)\n\n"
            "Respond ONLY with valid JSON:\n"
            "{\n"
            '  "score": 90,\n'
            '  "qc_tier": "approved",\n'
            '  "confidence": 0.94,\n'
            '  "issues": [],\n'
            '  "summary": "Crisp 2x upscaled 4K texture with natural micro-details."\n'
            "}"
        )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
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

            data = json.loads(response.text or "{}")
            score = float(data.get("score", 85.0))
            confidence = float(data.get("confidence", 0.85))
            api_issues = [str(x) for x in data.get("issues", []) if x]
            summary = str(data.get("summary", ""))

            combined_issues = issues + api_issues
            if is_hard_blur:
                score = min(score, 50.0)
            elif is_soft_borderline:
                score = min(score, 75.0)

            if score >= 80.0:
                qc_tier = "approved"
                passed = True
            elif score >= 60.0:
                qc_tier = "borderline"
                passed = True
            else:
                qc_tier = "rejected"
                passed = False

            logger.info(
                f"Stage 2 QC on {upscaled_path.name}: Tier={qc_tier.upper()}, Score={score:.0f}, Sharpness={sharpness:.1f}"
            )
            return QC2Result(
                passed=passed,
                qc_tier=qc_tier,
                score=round(score, 1),
                confidence=confidence,
                sharpness_score=round(sharpness, 1),
                issues=combined_issues,
                raw_summary=summary,
            )

        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "ResourceExhausted" in err_msg:
                self.rotator.report_rate_limit(key)
            logger.error(f"Stage 2 QC API Error: {e}")
            passed = not is_hard_blur
            tier = "rejected" if is_hard_blur else ("borderline" if is_soft_borderline else "approved")
            return QC2Result(
                passed=passed,
                qc_tier=tier,
                score=82.0 if passed else 45.0,
                confidence=0.6,
                sharpness_score=round(sharpness, 1),
                issues=issues,
                raw_summary="Evaluated via OpenCV sharpness fallback",
            )
