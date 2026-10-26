"""
StockNova AI External Memory Context & Handoff Report Builder.
Extracts real-time intelligence from SQLite (rejection reasons, acceptance rates,
winning categories, blacklists, and active shift state) and formats:
1. A dense system memory header for Argon / Gemini Pro.
2. A structured Handoff Report so if Primary Argon Account #1 hits a limit and
   fails over to Account #2, Account #2 continues from the exact point where
   Account #1 stopped with 0% lost history!
"""

from __future__ import annotations

import json
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("memory_context")


class MemoryContextBuilder:
    """Builds dynamic memory briefings and account-failover handoff reports from SQLite."""

    def __init__(self) -> None:
        self.db = Database()
        self.strategy_file = Config.get_user_data_dir() / "creative_strategy.json"

    def get_blacklisted_patterns(self) -> list[str]:
        res = set()
        if self.strategy_file.exists():
            try:
                with open(self.strategy_file, "r", encoding="utf-8") as f:
                    for p in json.load(f).get("blacklisted_patterns", []):
                        res.add(p)
            except Exception:
                pass
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pattern_or_concept FROM strategy_learnings WHERE action_taken = 'blacklisted';")
            for r in cursor.fetchall():
                res.add(r["pattern_or_concept"])
        return sorted(list(res))

    def get_top_rejection_reasons(self, limit: int = 5) -> list[str]:
        """Fetches distinct rejection reasons from past Adobe Stock & Freepik submissions."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT adobe_rejection_reason, COUNT(*) as cnt
                FROM assets
                WHERE (status = 'adobe_rejected' OR adobe_status = 'rejected')
                  AND adobe_rejection_reason IS NOT NULL AND adobe_rejection_reason != ''
                GROUP BY adobe_rejection_reason
                ORDER BY cnt DESC
                LIMIT ?
            """, (limit,))
            return [f"{r['adobe_rejection_reason']} ({r['cnt']}x)" for r in cursor.fetchall()]

    def get_winning_concepts(self, limit: int = 5) -> list[str]:
        """Fetches concepts with highest acceptance rate, weighting recent 7-day outcomes 2x higher."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pattern_or_concept, category, total_accepted, total_submitted,
                       CASE WHEN updated_at >= datetime('now', '-7 days') THEN 2.0 ELSE 1.0 END AS recency_weight
                FROM strategy_learnings
                WHERE total_accepted > 0 AND action_taken != 'blacklisted'
                ORDER BY (total_accepted * recency_weight) DESC, (total_accepted * 1.0 / MAX(1, total_submitted)) DESC
                LIMIT ?
            """, (limit,))
            return [
                f"{r['pattern_or_concept']} ({r['category']}: {r['total_accepted']}/{r['total_submitted']} accepted)"
                for r in cursor.fetchall()
            ]

    def save_snapshot_after_cycle(
        self,
        account_name: str,
        summary_Note: str = "",
        shift_state: dict[str, Any] | None = None,
    ) -> None:
        """Persists a structured memory handoff checkpoint after each cycle or account switch."""
        winners = self.get_winning_concepts()
        blacklisted = self.get_blacklisted_patterns()
        self.db.save_memory_handoff_snapshot(
            active_account=account_name,
            handoff_summary=summary_Note or "Shift checkpoint saved.",
            winning_niches=winners,
            blacklisted=blacklisted,
            shift_state=shift_state,
        )

    def build_handoff_report(self, from_account: str, to_account: str, shift_progress: dict[str, Any] | None = None) -> str:
        """
        Builds a complete Handoff Report (and bidirectional return-to-primary sync)
        when switching between Argon accounts so zero conversation history or shift progress is lost.
        """
        snapshot = self.db.get_memory_handoff_snapshot()
        blacklisted = self.get_blacklisted_patterns()
        rejections = self.get_top_rejection_reasons()
        winners = self.get_winning_concepts()
        progress = shift_progress or {}

        payload = {
            "handoff_direction": f"{from_account} -> {to_account}",
            "previous_summary": snapshot.get("handoff_summary", "Active daily stock production."),
            "winning_video_model": snapshot.get("winning_video_model", "omni flash"),
            "winning_concepts_7d_weighted": winners,
            "blacklisted_patterns": blacklisted[:12],
            "recent_rejection_causes": rejections,
            "resume_progress": progress,
        }
        return (
            f"=== URGENT ACCOUNT HANDOFF REPORT ({from_account} -> {to_account}) ===\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n===================================================================\n"
        )

    def build_memory_prompt_header(self, is_failover: bool = False, from_acc: str = "", to_acc: str = "") -> str:
        """
        Creates the dense system briefing injected into Argon / Gemini Pro.
        Automatically includes the Handoff Report if failing over or returning to Primary.
        """
        blacklisted = self.get_blacklisted_patterns()
        rejections = self.get_top_rejection_reasons()
        winners = self.get_winning_concepts()
        snapshot = self.db.get_memory_handoff_snapshot()

        header_lines = []
        if is_failover:
            header_lines.append(self.build_handoff_report(from_acc, to_acc))

        header_lines.extend([
            "=== STOCKNOVA HISTORICAL MEMORY & PRODUCTION RULES ===",
            "1. NO HUMANS: zero people, zero faces, zero silhouettes, zero hands. Unpopulated commercial scenes only.",
            "2. STYLE PURITY: Strictly 100% photorealistic commercial stock OR 100% flat vector. NEVER hybrid/cartoonish.",
            "3. VIDEO CONSTRAINT: Single continuous take (8-10s) with smooth steady camera. No scene cuts, no morphing, silent (-an).",
            f"4. VIDEO MODEL BUDGET: Strictly exclude 100-credit Quality modes. Active Winning Model: {snapshot.get('winning_video_model', 'omni flash')}.",
            "5. IMAGE UPSCALING: Strictly 2x (4K target) using High-Fidelity commercial weights.",
        ])

        if blacklisted:
            header_lines.append(f"6. BLACKLISTED CONCEPTS (NEVER GENERATE): {', '.join(blacklisted[:15])}")
        if rejections:
            header_lines.append(f"7. PAST REJECTION REASONS TO AVOID: {'; '.join(rejections)}")
        if winners:
            header_lines.append(f"8. PROVEN WINNING NICHES (7-DAY WEIGHTED): {'; '.join(winners)}")

        header_lines.append("======================================================\n")
        return "\n".join(header_lines)
