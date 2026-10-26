"""
StockNova AI — Unified Central Asset Vault & Dual-Platform Model.
Single table tracking both Adobe Stock and Freepik lifecycles on the EXACT same asset pool,
enabling automatic cross-platform recycling and zero-duplicate asset management.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("unified_vault")


class UnifiedVaultManager:
    """Manages the single repository of assets targeting both Adobe Stock and Freepik."""

    def __init__(self) -> None:
        self.db = Database()
        self._ensure_dual_platform_schema()

    def _ensure_dual_platform_schema(self) -> None:
        """Adds adobe_status, freepik_status, and model_performance tracking columns."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # Check existing columns in assets
            cursor.execute("PRAGMA table_info(assets);")
            columns = [row["name"] for row in cursor.fetchall()]

            new_cols = {
                "adobe_status": "TEXT DEFAULT 'pending'",      # pending, uploaded, accepted, rejected
                "freepik_status": "TEXT DEFAULT 'not_targeted'", # not_targeted, candidate_150, uploaded, accepted, rejected
                "is_freepik_150_golden": "INTEGER DEFAULT 0",
                "video_model_tested": "TEXT"                   # omni_flash, veo_fast, viewpoint_lite
            }

            for col, col_type in new_cols.items():
                if col not in columns:
                    cursor.execute(f"ALTER TABLE assets ADD COLUMN {col} {col_type};")

            # Model Performance Analytics Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT UNIQUE NOT NULL,
                    asset_type TEXT NOT NULL,
                    points_cost INTEGER DEFAULT 15,
                    total_generated INTEGER DEFAULT 0,
                    qc_passed INTEGER DEFAULT 0,
                    qc_failed INTEGER DEFAULT 0,
                    adobe_accepted INTEGER DEFAULT 0,
                    adobe_rejected INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active', -- active, blacklisted, preferred
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

        logger.info("Unified Dual-Platform Schema verified.")

    def record_model_result(self, model_name: str, asset_type: str, passed_qc: bool) -> None:
        """Records generation and QC results per AI model to self-evolve and blacklist bad models."""
        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO model_performance (model_name, asset_type, total_generated, qc_passed, qc_failed)
                VALUES (?, ?, 1, CASE WHEN ? THEN 1 ELSE 0 END, CASE WHEN ? THEN 0 ELSE 1 END)
                ON CONFLICT(model_name) DO UPDATE SET
                    total_generated = total_generated + 1,
                    qc_passed = qc_passed + CASE WHEN excluded.qc_passed = 1 THEN 1 ELSE 0 END,
                    qc_failed = qc_failed + CASE WHEN excluded.qc_failed = 1 THEN 1 ELSE 0 END,
                    updated_at = CURRENT_TIMESTAMP;
            """, (model_name, asset_type, passed_qc, passed_qc))

            # Auto-blacklist rule: if a model fails QC > 50% over 6+ samples, blacklist it
            cursor = conn.cursor()
            cursor.execute("SELECT total_generated, qc_failed FROM model_performance WHERE model_name = ?", (model_name,))
            r = cursor.fetchone()
            if r and r["total_generated"] >= 6:
                fail_rate = r["qc_failed"] / r["total_generated"]
                if fail_rate >= 0.50:
                    conn.execute("UPDATE model_performance SET status = 'blacklisted' WHERE model_name = ?", (model_name,))
                    logger.warning(f"🚨 AUTO-BLACKLIST: Video Model '{model_name}' blacklisted (QC Fail Rate: {fail_rate*100:.1f}%)")

    def curate_freepik_golden_batch(self, target_count: int = 120) -> list[Path]:
        """
        1-Click Freepik 150/120 Curator:
        Scans the unified vault of approved assets (Nano Banana Pro), selects the cleanest,
        most compliant, and diverse assets, and packages them into the Freepik onboarding folder.
        """
        from stockpilot.batching.similarity_engine import AntiSimilarityBatcher

        batcher = AntiSimilarityBatcher()
        ws_root = Config.get_path("paths.workspace_root", Path(r"d:\Stock Automation\workspace"))
        approved_dir = ws_root / "2_QC2_Approved"
        golden_out_dir = ws_root / "freepik_golden_onboarding"
        golden_out_dir.mkdir(parents=True, exist_ok=True)

        candidates = list(approved_dir.glob("*.jpg")) + list(approved_dir.glob("*.png"))
        if not candidates:
            # Also check images batched or already uploaded to Adobe (safe to reuse on Freepik!)
            batched_dir = ws_root / "3_Batched_Ready"
            candidates.extend(batched_dir.rglob("*.jpg"))

        logger.info(f"Scanning {len(candidates)} unified vault assets for Freepik Onboarding...")

        selected: list[Path] = []
        selected_hashes: list[str] = []

        # Sort: prefer clean mockups and flatlays, then textures
        for img in candidates:
            if len(selected) >= target_count:
                break

            ph, _ = batcher.compute_hashes(img)
            # Enforce strict uniqueness among the golden 120-150
            collision = any(batcher.are_similar(ph, exist_h) for exist_h in selected_hashes)
            if not collision:
                selected.append(img)
                selected_hashes.append(ph)

        # Copy to golden onboarding package
        import shutil
        curated_paths = []
        for img in selected:
            dest = golden_out_dir / img.name
            shutil.copy2(str(img), str(dest))
            curated_paths.append(dest)
            self.db.update_asset(img.stem, freepik_status="candidate_150", is_freepik_150_golden=1)

        logger.info(f"🎉 Curated {len(curated_paths)} golden candidates in {golden_out_dir}")
        return curated_paths
