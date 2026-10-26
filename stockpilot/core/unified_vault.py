"""
StockNova AI — Unified Central Asset Vault & Video Model Benchmark Manager.
Manages:
1. Single asset repository shared across Adobe Stock and Freepik with independent status tracking.
2. Video Model A/B Testing & Winner Selection (strictly banning 100-credit Quality modes).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("unified_vault")


class UnifiedVaultManager:
    """Manages the unified asset repository and video model benchmarking."""

    BANNED_VIDEO_MODES = {"quality", "quality_100", "100_credit", "quality (100 credits)"}

    def __init__(self) -> None:
        self.db = Database()

    @classmethod
    def is_video_model_allowed(cls, model_name: str, credit_cost: int = 15) -> bool:
        """Hard-blocks any video generation mode costing >= 100 credits or named 'Quality'."""
        norm = model_name.strip().lower()
        if credit_cost >= 100:
            return False
        if norm in cls.BANNED_VIDEO_MODES or "100" in norm:
            return False
        return True

    def select_best_video_model(self) -> dict[str, Any]:
        """
        Evaluates eligible video models (< 100 credits):
        - If models are still in benchmark phase (< 4 tested videos), picks the next under-tested model
          so the agent compares their real quality.
        - Once tested, automatically locks onto the model with the highest QC Pass + Adobe Acceptance score!
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT model_name, points_cost, total_generated, qc_passed, qc_borderline, qc_failed,
                       adobe_accepted, adobe_rejected, is_winner, status
                FROM model_performance
                WHERE asset_type = 'video'
                  AND points_cost < 100
                  AND status NOT IN ('blacklisted', 'banned_100_credit')
                ORDER BY is_winner DESC, id ASC;
            """)
            models = [dict(r) for r in cursor.fetchall() if self.is_video_model_allowed(r["model_name"], r["points_cost"])]

        if not models:
            return {"model_name": "omni flash", "points_cost": 15, "mode": "default_winner"}

        # Check if any eligible model needs initial benchmark samples (< 3 samples)
        under_tested = [m for m in models if (m["total_generated"] or 0) < 3]
        if under_tested:
            chosen = under_tested[0]
            return {
                "model_name": chosen["model_name"],
                "points_cost": chosen["points_cost"],
                "mode": "benchmark_testing",
                "reason": f"Benchmarking '{chosen['model_name']}' ({chosen['total_generated']}/3 test samples completed)",
            }

        # Calculate composite quality score for each tested model
        best_model = models[0]
        best_score = -1.0
        for m in models:
            gen = max(1, m["total_generated"] or 1)
            qc_pass_rate = float(m["qc_passed"] or 0) / gen
            ad_total = (m["adobe_accepted"] or 0) + (m["adobe_rejected"] or 0)
            ad_acc_rate = (float(m["adobe_accepted"] or 0) / ad_total) if ad_total > 0 else qc_pass_rate
            score = (qc_pass_rate * 0.55) + (ad_acc_rate * 0.45)
            if score > best_score:
                best_score = score
                best_model = m

        # Mark the best model as winner in SQLite
        with self.db.get_connection() as conn:
            conn.execute("UPDATE model_performance SET is_winner = 0 WHERE asset_type = 'video';")
            conn.execute("UPDATE model_performance SET is_winner = 1 WHERE model_name = ?;", (best_model["model_name"],))

        return {
            "model_name": best_model["model_name"],
            "points_cost": best_model["points_cost"],
            "mode": "locked_winner",
            "score": round(best_score * 100, 1),
            "reason": f"Locked onto winner '{best_model['model_name']}' ({best_score*100:.0f}% quality score)",
        }

    def record_model_result(self, model_name: str, asset_type: str, passed_qc: bool, is_borderline: bool = False, sharpness: float = 0.0) -> None:
        """Records generation and QC results per AI model and recalculates the winning video model."""
        if asset_type == "video" and not self.is_video_model_allowed(model_name):
            logger.warning(f"Blocked recording for banned 100-credit video mode: {model_name}")
            return

        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO model_performance (
                    model_name, asset_type, total_generated, qc_passed, qc_borderline, qc_failed, avg_sharpness
                )
                VALUES (?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(model_name) DO UPDATE SET
                    total_generated = total_generated + 1,
                    qc_passed = qc_passed + excluded.qc_passed,
                    qc_borderline = qc_borderline + excluded.qc_borderline,
                    qc_failed = qc_failed + excluded.qc_failed,
                    avg_sharpness = CASE WHEN excluded.avg_sharpness > 0 
                                         THEN (avg_sharpness + excluded.avg_sharpness) / 2.0 
                                         ELSE avg_sharpness END,
                    updated_at = CURRENT_TIMESTAMP;
            """, (
                model_name,
                asset_type,
                1 if passed_qc and not is_borderline else 0,
                1 if is_borderline else 0,
                0 if (passed_qc or is_borderline) else 1,
                sharpness,
            ))

            cursor = conn.cursor()
            cursor.execute("SELECT total_generated, qc_failed FROM model_performance WHERE model_name = ?", (model_name,))
            r = cursor.fetchone()
            if r and r["total_generated"] >= 6:
                fail_rate = r["qc_failed"] / r["total_generated"]
                if fail_rate >= 0.55:
                    conn.execute("UPDATE model_performance SET status = 'blacklisted', is_winner = 0 WHERE model_name = ?", (model_name,))
                    logger.warning(f"Auto-Blacklisted Model '{model_name}' (QC Fail Rate: {fail_rate*100:.1f}%)")

        if asset_type == "video":
            self.select_best_video_model()

    def curate_freepik_golden_batch(self, target_count: int = 150) -> list[Path]:
        """Delegates to the stateful FreepikOnboardingCurator."""
        from stockpilot.platforms.freepik_curator import FreepikOnboardingCurator

        curator = FreepikOnboardingCurator()
        res = curator.run_incremental_curation()
        logger.info(f"Freepik 150 Curation Result: {res}")
        return list(curator.golden_folder.glob("*.jpg")) + list(curator.golden_folder.glob("*.png"))
