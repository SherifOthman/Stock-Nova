"""
Stage 1 Quality Control (Pre-Upscale Concept, Anatomy & Hallucination Filter).
Compresses generated images in RAM (~150KB) and checks with Gemini 2.5 Flash Vision
BEFORE spending GPU compute time on upscaling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator
from stockpilot.utils.image_utils import compress_for_gemini

logger = get_logger("stage1_qc")


@dataclass
class QC1Result:
    passed: bool
    confidence: float
    issues: list[str]
    raw_summary: str


class Stage1QC:
    """Pre-upscale anatomy and concept verification."""

    def __init__(self) -> None:
        self.rotator = APIKeyRotator()

    def build_prompt(self) -> str:
        return (
            "You are a strict, world-class Stock Photography Inspector for Adobe Stock. "
            "Inspect this AI-generated image for ANY of the following rejection causes:\n"
            "1. Anatomical defects: Extra/missing/fused fingers, distorted hands, asymmetric eyes, weird facial features.\n"
            "2. AI artifacts: Floating objects, impossible physics, severe warping, unnatural blending boundaries.\n"
            "3. Text & Branding: Any gibberish/unreadable letters, real-world logos, brand names, or trademarks.\n"
            "4. Composition: Awkward cropping of heads/limbs, extreme noise or muddy low-res details.\n\n"
            "Respond ONLY with a valid JSON object strictly matching this format:\n"
            "{\n"
            '  "pass": true,\n'
            '  "confidence": 0.95,\n'
            '  "issues": [],\n'
            '  "summary": "Clean anatomy and composition, no visible defects."\n'
            "}"
        )

    def inspect(self, image_path: Path) -> QC1Result:
        """Runs Stage 1 QC on an image."""
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.error("google-genai SDK not installed. Skipping API QC.")
            return QC1Result(passed=True, confidence=1.0, issues=[], raw_summary="SDK missing")

        key = self.rotator.get_key()
        if not key:
            logger.warning("No Gemini API key available; passing image by default.")
            return QC1Result(passed=True, confidence=0.5, issues=[], raw_summary="No API Key configured")

        compressed_bytes = compress_for_gemini(image_path)
        prompt = self.build_prompt()

        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=Config.get("gemini.model", "gemini-2.5-flash"),
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=compressed_bytes, mime_type="image/jpeg"),
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

            passed = bool(data.get("pass", False))
            confidence = float(data.get("confidence", 0.8))
            issues = data.get("issues", [])
            summary = data.get("summary", "")

            logger.info(f"Stage 1 QC on {image_path.name}: Passed={passed} (Issues: {', '.join(issues) if issues else 'None'})")
            return QC1Result(passed=passed, confidence=confidence, issues=issues, raw_summary=summary)

        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "ResourceExhausted" in err_msg:
                self.rotator.report_rate_limit(key)
            logger.error(f"Stage 1 QC API Error: {e}")
            # On transient error, don't auto-reject
            return QC1Result(passed=True, confidence=0.5, issues=[f"API Error: {e}"], raw_summary="API Error")
