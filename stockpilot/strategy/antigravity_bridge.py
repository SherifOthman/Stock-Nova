"""
StockNova AI — Antigravity Agent Ecosystem Bridge.
Directly connects to Google AI Studio's Antigravity Agent Suite:
1. Gemini 4 Argon ('gemini-4-argon'):
   - Chief Strategist: Deep market research with Grounding with Google Search.
   - Complex prompt generation avoiding commercial/legal stock pitfalls.
2. Gemini 3.8 Flash ('gemini-3.8-flash'):
   - Long-horizon autonomous agent orchestrator.
   - Multi-frame video motion & cut inspector.
3. Gemini 3.5 Flash Lite ('gemini-3.5-flash-lite'):
   - High-throughput, ultra-fast pre-upscale QC & keyword tagging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator

logger = get_logger("antigravity_bridge")


class AntigravityAgentBridge:
    """Manages the Google AI Studio Antigravity Model Trinity."""

    def __init__(self) -> None:
        self.rotator = APIKeyRotator()
        self.argon_model = Config.get("gemini.strategic_model", "gemini-4-argon")
        self.agent_model = Config.get("gemini.agent_orchestrator", "gemini-3.8-flash")
        self.fast_model = Config.get("gemini.qc_fast_model", "gemini-3.5-flash-lite")

    def run_argon_research(self, topic: str) -> list[dict[str, Any]]:
        """
        Executes deep strategic research using Gemini 4 Argon
        with Google Search Grounding enabled.
        """
        key = self.rotator.get_key()
        if not key:
            logger.warning("No API key available; returning fallback concepts.")
            return []

        prompt = (
            f"As Principal Creative Director at Adobe Stock & Freepik, conduct deep market research on: '{topic}'.\n"
            "Identify 5 HIGH-COMMERCIAL, TOP-SELLING stock photography & video b-roll concepts currently in high demand.\n"
            "RULES:\n"
            "1. NO HUMANS: zero people, zero faces, zero hands.\n"
            "2. 100% photorealistic commercial stock OR 100% flat vector (no cartoonish hybrid).\n"
            "3. For video, must work as a single continuous camera take.\n\n"
            "Respond ONLY with a valid JSON array of objects strictly matching this format:\n"
            "[\n"
            "  {\n"
            '    "concept": "concise description of the visual scene",\n'
            '    "style": "photorealistic" or "vector",\n'
            '    "commercial_niche": "Technology / Architecture / Clean Energy",\n'
            '    "camera_motion": "slow smooth forward dolly"\n'
            "  }\n"
            "]"
        )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)

            # Grounding with Google Search if enabled
            tools = []
            if Config.get("gemini.enable_google_search_grounding", True):
                try:
                    tools.append(types.Tool(google_search=types.GoogleSearch()))
                except Exception:
                    pass

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            )
            if tools:
                config.tools = tools

            # Try Gemini 4 Argon first, fallback to Gemini 3.8 Flash
            try:
                response = client.models.generate_content(
                    model=self.argon_model,
                    contents=prompt,
                    config=config
                )
            except Exception as e_argon:
                logger.warning(f"Argon model call fallback to {self.agent_model}: {e_argon}")
                response = client.models.generate_content(
                    model=self.agent_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.3
                    )
                )

            data = json.loads(response.text or "[]")
            logger.info(f"Gemini 4 Argon research complete: {len(data)} concepts generated.")
            return data

        except Exception as e:
            logger.error(f"Antigravity Bridge Error: {e}")
            return []
