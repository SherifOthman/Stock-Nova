"""
Argon 4 / Gemini Pro Deep Trend Researcher.
Conducts high-level market research on top-selling Adobe Stock & Freepik concepts,
utilizing Google Search Grounding to extract high-demand, low-competition commercial niches,
and feeds them directly into StockNova's self-evolving prompt generator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator

logger = get_logger("trend_researcher")


class TrendResearcher:
    """Researches commercial stock trends with deep reasoning models."""

    def __init__(self) -> None:
        self.rotator = APIKeyRotator()
        self.model_name = Config.get("gemini.research_model", "argon-4")

    def research_trending_niches(self, category: str = "technology") -> list[dict[str, Any]]:
        """
        Uses deep search/reasoning to discover trending, non-human commercial concepts.
        """
        key = self.rotator.get_key()
        if not key:
            logger.warning("No API key available for trend research; using built-in high-volume categories.")
            return [
                {"concept": "clean green energy hydrogen turbine closeup", "style": "photorealistic", "demand": "high"},
                {"concept": "abstract quantum computing optical data transfer 3d", "style": "photorealistic", "demand": "high"},
                {"concept": "minimalist sustainable corporate icon set", "style": "vector", "demand": "medium"},
            ]

        prompt = (
            f"Act as a Principal Creative Director at Adobe Stock. Conduct deep commercial research on: '{category}'.\n"
            "Identify 5 HIGH-DEMAND, COMMERCIAL stock photography & video b-roll concepts that buyers are actively searching for.\n"
            "STRICT RULES:\n"
            "1. NO HUMANS: zero people, zero faces, zero hands.\n"
            "2. Pure realism OR pure flat vector (no cartoon hybrid).\n"
            "3. For video, must work as a single continuous camera take.\n\n"
            "Respond ONLY with a valid JSON array of objects strictly matching this schema:\n"
            "[\n"
            "  {\n"
            '    "concept": "concise description of the visual scene",\n'
            '    "style": "photorealistic" or "vector",\n'
            '    "lighting": "studio / natural daylight / cinematic",\n'
            '    "camera_motion": "slow forward dolly / static tripod"\n'
            "  }\n"
            "]"
        )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            # Try configured research model (Argon 4 / Gemini Pro), fallback to flash if alias not found
            target_model = self.model_name
            try:
                response = client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.3,
                    ),
                )
            except Exception:
                # Fallback to gemini-2.5-flash
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.3,
                    ),
                )

            data = json.loads(response.text or "[]")
            logger.info(f"Discovered {len(data)} trending concepts for '{category}'.")
            return data

        except Exception as e:
            logger.error(f"Trend research error: {e}")
            return []
