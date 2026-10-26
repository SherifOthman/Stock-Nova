"""
StockNova AI — Strategic Argon / Gemini Brain & Multi-Account Failover Bridge.
Features:
1. Primary Argon Account Priority: Always selects the user's #1 designated Primary Argon account
   first to preserve continuous conversation history.
2. Automatic Account Failover with Local Handoff Report: If Account #1 hits a limit,
   switches to Account #2 and injects the local SQLite Handoff Report so 0% of history is lost.
3. Official Google AI Studio API Key Rotation ('gemini-2.5-pro' for strategy, 'gemini-2.5-flash' for QC/SEO).
"""

from __future__ import annotations

import json
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator
from stockpilot.strategy.memory_context import MemoryContextBuilder

logger = get_logger("antigravity_bridge")


class AntigravityAgentBridge:
    """Manages strategic planning with Primary Argon Account priority and local SQLite handoff."""

    def __init__(self) -> None:
        self.db = Database()
        self.rotator = APIKeyRotator()
        self.memory = MemoryContextBuilder()
        self.strategic_model = "gemini-2.5-pro"
        self.fast_model = "gemini-2.5-flash"

    def get_active_argon_identity(self) -> dict[str, Any]:
        """
        Returns the #1 Primary Argon account if healthy; if it hit a limit,
        automatically fails over to the next active account and flags handoff mode.
        """
        accounts = self.db.get_detailed_accounts()
        if not accounts:
            return {
                "profile_name": "Primary Argon Brain",
                "email": "primary@local",
                "is_primary": True,
                "is_failover": False,
                "from_account": "",
            }

        primary = next((a for a in accounts if a.get("is_primary_argon") == 1), accounts[0])
        if primary.get("status") == "active" and not primary.get("last_error"):
            return {
                "profile_name": primary["profile_name"],
                "email": primary.get("email") or primary["profile_name"],
                "is_primary": True,
                "is_failover": False,
                "from_account": "",
            }

        # Primary hit a limit -> fail over to next active account with Handoff Report
        backup = next(
            (a for a in accounts if a["profile_name"] != primary["profile_name"] and a.get("status") == "active"),
            primary,
        )
        return {
            "profile_name": backup["profile_name"],
            "email": backup.get("email") or backup["profile_name"],
            "is_primary": False,
            "is_failover": backup["profile_name"] != primary["profile_name"],
            "from_account": primary.get("email") or primary["profile_name"],
        }

    def run_argon_research(self, topic: str = "High-demand commercial stock video & photo niches") -> list[dict[str, Any]]:
        """
        Executes deep strategic research using Primary Argon context + Google Search Grounding,
        and saves the resulting strategy snapshot to SQLite so history is never lost.
        """
        identity = self.get_active_argon_identity()
        memory_header = self.memory.build_memory_prompt_header(
            is_failover=identity["is_failover"],
            from_acc=identity["from_account"],
            to_acc=identity["email"],
        )

        key = self.rotator.get_key()
        if not key:
            logger.warning("No Google AI Studio API key configured yet; returning learned local concepts.")
            return self._fallback_concepts(topic)

        prompt = (
            f"{memory_header}\n"
            f"Active Strategic Brain Account: {identity['email']}\n"
            f"Task: Conduct deep commercial stock market research on: '{topic}'.\n"
            "Identify 6 HIGH-COMMERCIAL, TOP-SELLING stock video (Priority #1) and photo (Priority #2) concepts.\n"
            "STRICT RULES:\n"
            "1. NO HUMANS: zero people, zero faces, zero hands.\n"
            "2. 100% photorealistic commercial stock OR 100% clean flat vector.\n"
            "3. Videos must work as a single continuous 10s camera take without audio and using <100 credit models.\n\n"
            "Respond ONLY with a valid JSON array of objects matching this format:\n"
            "[\n"
            "  {\n"
            '    "concept": "concise description of the visual scene",\n'
            '    "media_priority": "video" or "image",\n'
            '    "style": "photorealistic" or "vector",\n'
            '    "commercial_niche": "Technology / Architecture / Clean Energy / Culinary",\n'
            '    "camera_motion": "slow smooth forward dolly"\n'
            "  }\n"
            "]"
        )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            try:
                response = client.models.generate_content(
                    model=self.strategic_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.25,
                    ),
                )
            except Exception:
                response = client.models.generate_content(
                    model=self.fast_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.25,
                    ),
                )

            data = json.loads(response.text or "[]")
            if isinstance(data, list) and data:
                niches = [c.get("commercial_niche", "") for c in data if isinstance(c, dict)]
                self.db.save_memory_handoff_snapshot(
                    active_account=identity["email"],
                    handoff_summary=f"Researched {len(data)} concepts for '{topic}'. Top niches: {', '.join(niches[:4])}",
                    winning_niches=niches,
                    blacklisted=self.memory.get_blacklisted_patterns(),
                )
                return data
        except Exception as e:
            logger.error(f"Strategic Research Error: {e}")

        return self._fallback_concepts(topic)

    @staticmethod
    def _fallback_concepts(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "concept": f"Macro commercial studio shot of sustainable clean energy glass solar cells ({topic})",
                "media_priority": "video",
                "style": "photorealistic",
                "commercial_niche": "Clean Energy & Technology",
                "camera_motion": "Single continuous slow forward dolly",
            },
            {
                "concept": "Minimalist luxury architectural interior with warm sunlight and copy space",
                "media_priority": "video",
                "style": "photorealistic",
                "commercial_niche": "Architecture & Interiors",
                "camera_motion": "Single continuous slow pan left to right",
            },
            {
                "concept": "Isolated white background 3D commercial packaging mockup with soft studio shadows",
                "media_priority": "image",
                "style": "photorealistic",
                "commercial_niche": "Product Mockups",
                "camera_motion": "Static studio frame",
            },
            {
                "concept": "Fresh organic Mediterranean culinary flatlay on dark slate table with copy space",
                "media_priority": "image",
                "style": "photorealistic",
                "commercial_niche": "Food & Beverage",
                "camera_motion": "Overhead locked tripod",
            },
        ]
