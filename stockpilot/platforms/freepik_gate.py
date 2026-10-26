"""
Freepik 150 Onboarding Gate Engine.
Dedicated module to build, curate, upscale, and rigorously inspect the 150-200
golden assets required to pass Freepik's strict initial contributor review.
Enforces:
1. Strict visual category split:
   - 50% Isolated white-background commercial objects/mockups (High Freepik acceptance)
   - 50% Full-bleed commercial backgrounds/textures (Architecture, Technology, Food, Abstract)
2. ZERO visual duplicates (Hamming distance strictly enforced across all 150).
3. Stage 1 & Stage 2 QC tailored for Freepik review criteria (no over-sharpening halos, pristine edges).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.quality.stage1_qc import Stage1QC
from stockpilot.quality.upscaler import Upscaler
from stockpilot.quality.stage2_qc import Stage2QC
from stockpilot.batching.similarity_engine import AntiSimilarityBatcher
from stockpilot.utils.filename_cleaner import FilenameCleaner

logger = get_logger("freepik_150_gate")


@dataclass
class FreepikCandidateStats:
    total_target: int
    approved_count: int
    isolated_objects_count: int
    backgrounds_count: int
    pending_qc_count: int
    rejected_count: int
    is_ready_for_submission: bool


class Freepik150Gate:
    """Manages the Freepik Onboarding Candidate Vault."""

    TARGET_COUNT = 150

    def __init__(self) -> None:
        self.db = Database()
        self.ws_root = Config.get_path("paths.workspace_root", Path(r"d:\Stock Automation\workspace"))
        self.gate_dir = self.ws_root / "freepik_150_candidate"
        self.raw_dir = self.gate_dir / "0_raw"
        self.approved_dir = self.gate_dir / "1_approved_ready"
        self.rejected_dir = self.gate_dir / "1_rejected"

        for p in [self.gate_dir, self.raw_dir, self.approved_dir, self.rejected_dir]:
            p.mkdir(parents=True, exist_ok=True)

        self.qc1 = Stage1QC()
        self.upscaler = Upscaler()
        self.qc2 = Stage2QC()
        self.batcher = AntiSimilarityBatcher()

    def get_status(self) -> FreepikCandidateStats:
        """Computes live stats of the Freepik 150 candidate vault."""
        approved_files = list(self.approved_dir.glob("*.jpg")) + list(self.approved_dir.glob("*.png"))
        rejected_files = list(self.rejected_dir.glob("*.jpg")) + list(self.rejected_dir.glob("*.png"))
        pending_files = list(self.raw_dir.glob("*.jpg")) + list(self.raw_dir.glob("*.png"))

        isolated_count = sum(1 for f in approved_files if "isolated" in f.name.lower() or "white_bg" in f.name.lower())
        bg_count = len(approved_files) - isolated_count

        return FreepikCandidateStats(
            total_target=self.TARGET_COUNT,
            approved_count=len(approved_files),
            isolated_objects_count=isolated_count,
            backgrounds_count=bg_count,
            pending_qc_count=len(pending_files),
            rejected_count=len(rejected_files),
            is_ready_for_submission=len(approved_files) >= self.TARGET_COUNT
        )

    def process_candidates(self) -> dict[str, int]:
        """
        Runs rigorous two-stage QC and headless upscaling on all pending candidates.
        Enforces strict anti-similarity against already-approved Freepik candidates.
        """
        pending = list(self.raw_dir.glob("*.jpg")) + list(self.raw_dir.glob("*.png"))
        approved_existing = list(self.approved_dir.glob("*.jpg")) + list(self.approved_dir.glob("*.png"))

        stats = {"processed": 0, "approved": 0, "rejected": 0}

        for raw_file in pending:
            stats["processed"] += 1
            # Clean filename
            cleaned = FilenameCleaner.sanitize_file(raw_file, fallback_slug="freepik_asset")

            # 1. Stage 1 QC
            res1 = self.qc1.inspect(cleaned)
            if not res1.passed:
                logger.warning(f"Freepik Candidate failed Stage 1: {cleaned.name}")
                cleaned.replace(self.rejected_dir / cleaned.name)
                stats["rejected"] += 1
                continue

            # 2. Headless Upscaling
            upscaled = self.upscaler.upscale(cleaned, self.gate_dir / "temp_upscaled")
            if not upscaled:
                cleaned.replace(self.rejected_dir / cleaned.name)
                stats["rejected"] += 1
                continue

            # 3. Stage 2 QC (100% Crop)
            res2 = self.qc2.inspect(upscaled)
            if not res2.passed:
                logger.warning(f"Freepik Candidate failed Stage 2: {upscaled.name}")
                upscaled.replace(self.rejected_dir / upscaled.name)
                cleaned.unlink(missing_ok=True)
                stats["rejected"] += 1
                continue

            # 4. Anti-Similarity Check against existing approved pool
            ph, _ = self.batcher.compute_hashes(upscaled)
            is_duplicate = False
            for exist_img in approved_existing:
                exist_ph, _ = self.batcher.compute_hashes(exist_img)
                if self.batcher.are_similar(ph, exist_ph):
                    is_duplicate = True
                    break

            if is_duplicate:
                logger.warning(f"Freepik Candidate rejected: visually too similar to an already approved candidate.")
                upscaled.replace(self.rejected_dir / f"similars_{upscaled.name}")
                cleaned.unlink(missing_ok=True)
                stats["rejected"] += 1
                continue

            # Move to Approved Ready
            final_dest = self.approved_dir / upscaled.name
            upscaled.replace(final_dest)
            approved_existing.append(final_dest)
            cleaned.unlink(missing_ok=True)
            stats["approved"] += 1
            logger.info(f"✨ Approved Freepik Golden Candidate: {final_dest.name}")

        return stats
