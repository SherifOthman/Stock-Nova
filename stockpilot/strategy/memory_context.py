"""
StockNova AI External Memory Context Builder.
Extracts real-time intelligence from SQLite (rejection reasons, acceptance rates,
winning categories, and blacklists) and formats a concise, dense briefing.
This context is automatically injected into every prompt sent to Argon 4 / Gemini Pro / Google AI Studio,
ensuring 100% memory continuity even if browser sessions, accounts, or models are reset!
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("memory_context")


class MemoryContextBuilder:
    """Builds dynamic memory briefing from local database."""

    def __init__(self) -> None:
        self.db = Database()
        self.strategy_file = Path(r"d:\Stock Automation\config\creative_strategy.json")

    def get_blacklisted_patterns(self) -> list[str]:
        if not self.strategy_file.exists():
            return []
        try:
            with open(self.strategy_file, "r", encoding="utf-8") as f:
                return json.load(f).get("blacklisted_patterns", [])
        except Exception:
            return []

    def get_top_rejection_reasons(self, limit: int = 5) -> list[str]:
        """Fetches distinct rejection reasons from past submissions."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT adobe_rejection_reason, COUNT(*) as cnt
                FROM assets
                WHERE status = 'adobe_rejected' AND adobe_rejection_reason IS NOT NULL AND adobe_rejection_reason != ''
                GROUP BY adobe_rejection_reason
                ORDER BY cnt DESC
                LIMIT ?
            """, (limit,))
            return [f"{r['adobe_rejection_reason']} ({r['cnt']}x)" for r in cursor.fetchall()]

    def get_winning_concepts(self, limit: int = 5) -> list[str]:
        """Fetches concepts with highest acceptance rate."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pattern_or_concept, category, total_accepted, total_submitted
                FROM strategy_learnings
                WHERE total_accepted > 0 AND action_taken != 'blacklisted'
                ORDER BY total_accepted DESC, (total_accepted * 1.0 / total_submitted) DESC
                LIMIT ?
            """, (limit,))
            return [f"{r['pattern_or_concept']} ({r['category']}: {r['total_accepted']}/{r['total_submitted']} accepted)" for r in cursor.fetchall()]

    def build_memory_prompt_header(self) -> str:
        """
        Creates the dense system briefing to inject into Argon / Gemini.
        Keeps token size minimal while enforcing absolute memory of past errors.
        """
        blacklisted = self.get_blacklisted_patterns()
        rejections = self.get_top_rejection_reasons()
        winners = self.get_winning_concepts()

        header_lines = [
            "=== STOCKNOVA HISTORICAL MEMORY & HARD CONSTRAINTS ===",
            "You are operating with full awareness of our historical portfolio performance.",
            "STRICT RULES (Violations cause instant rejection):",
            "1. NO HUMANS: zero people, zero faces, zero silhouettes, zero hands. Unpopulated scenes only.",
            "2. STYLE PURITY: Strictly 100% photorealistic commercial stock OR 100% flat vector/infographic. NEVER cartoonish/semi-realistic hybrid.",
            "3. VIDEO CONSTRAINT: Single continuous take (8-10s) with locked/smooth camera. No scene cuts, no zooms that alter subject, no morphing.",
            "4. VIDEO MODEL BUDGET: Target 10-20 credit models only (Omni Flash / Veo Fast). Never generate concepts requiring multi-angle cuts."
        ]

        if blacklisted:
            header_lines.append(f"5. ACTIVELY BLACKLISTED CONCEPTS (DO NOT GENERATE): {', '.join(blacklisted[:15])}")

        if rejections:
            header_lines.append(f"6. TOP PAST REJECTION REASONS TO AVOID: {'; '.join(rejections)}")

        if winners:
            header_lines.append(f"7. PROVEN WINNING DIRECTIONS TO EXPAND: {'; '.join(winners)}")

        header_lines.append("======================================================\n")
        return "\n".join(header_lines)
