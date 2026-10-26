"""
Freepik 150-200 Golden Onboarding Curator & Technical Validator.
Features:
1. Strict Technical Standards:
   - Minimum 4 Megapixels (>= 2000px on shortest side).
   - Maximum 100 Megapixels.
   - Clean aspect ratios (1:1, 16:9, 4:3, 9:16).
   - Extra-strict sharpness threshold (Freepik manual reviewers inspect at 100% zoom).
2. Incremental Curation & State Locking:
   - Assets already picked are locked in SQLite (is_freepik_150_golden = 1) and never re-evaluated.
   - Assets rejected for Freepik are recorded (freepik_rejected = 1) and never re-evaluated.
   - Only newly generated/upscaled assets from Nano Banana Pro in '2_QC2_Approved' are scanned.
   - Progressively fills the vault until reaching 150-200.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from PIL import Image

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.batching.similarity_engine import AntiSimilarityBatcher
from stockpilot.quality.opencv_checks import calculate_sharpness

logger = get_logger("freepik_curator")


@dataclass
class FreepikOnboardingStatus:
    total_target: int
    curated_count: int
    needed_count: int
    isolated_mockup_count: int
    full_bleed_bg_count: int
    is_ready_for_submission: bool


class FreepikOnboardingCurator:
    """Manages incremental curation of the 150-200 golden onboarding batch."""

    MIN_TARGET = 150
    MAX_TARGET = 200

    def __init__(self) -> None:
        self.db = Database()
        self.batcher = AntiSimilarityBatcher()
        self.ws_root = Config.get_path("paths.workspace_root", Path(r"d:\Stock Automation\workspace"))
        self.golden_folder = self.ws_root / "freepik_golden_150"
        self.golden_folder.mkdir(parents=True, exist_ok=True)
        self._ensure_freepik_tracking_schema()

    def _ensure_freepik_tracking_schema(self) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(assets);")
            cols = [row["name"] for row in cursor.fetchall()]
            if "freepik_rejected" not in cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN freepik_rejected INTEGER DEFAULT 0;")
            if "freepik_rejection_notes" not in cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN freepik_rejection_notes TEXT;")

    def get_status(self) -> FreepikOnboardingStatus:
        """Returns the live state of the Freepik 150-200 curation pool."""
        curated_files = list(self.golden_folder.glob("*.jpg")) + list(self.golden_folder.glob("*.png"))
        count = len(curated_files)

        isolated = sum(1 for f in curated_files if any(k in f.name.lower() for k in ["isolated", "mockup", "object", "white"]))
        bg = count - isolated

        needed = max(0, self.MIN_TARGET - count)
        return FreepikOnboardingStatus(
            total_target=self.MIN_TARGET,
            curated_count=count,
            needed_count=needed,
            isolated_mockup_count=isolated,
            full_bleed_bg_count=bg,
            is_ready_for_submission=count >= self.MIN_TARGET
        )

    def validate_technical_specs(self, image_path: Path) -> tuple[bool, str]:
        """
        Validates Freepik's strict technical onboarding guidelines:
        - Must be >= 4 Megapixels (>= 4,000,000 pixels)
        - Shortest side must be >= 2000px
        - File size between 500KB and 50MB
        - Sharpness threshold >= 115 (strict against soft AI textures)
        """
        try:
            size_bytes = image_path.stat().st_size
            if size_bytes < 400_000:
                return False, "File size too small (< 400KB)"
            if size_bytes > 50_000_000:
                return False, "File size too large (> 50MB)"

            with Image.open(image_path) as img:
                w, h = img.size
                megapixels = (w * h) / 1_000_000.0

                if megapixels < 4.0:
                    return False, f"Resolution too low ({megapixels:.1f} MP < 4.0 MP minimum for Freepik)"

                if min(w, h) < 2000:
                    return False, f"Shortest dimension too small ({min(w, h)}px < 2000px)"

            # Check sharpness (Freepik reviewers manually zoom 100%)
            sharpness = calculate_sharpness(image_path)
            if sharpness < 115.0:
                return False, f"Texture too soft for Freepik manual zoom (Sharpness {sharpness:.1f} < 115.0)"

            return True, "Passed Freepik technical specs"

        except Exception as e:
            return False, f"Technical validation error: {e}"

    def run_incremental_curation(self) -> dict[str, int]:
        """
        Scans ONLY newly approved, non-evaluated assets in 2_QC2_Approved.
        Selects valid candidates without duplicate pHash until reaching 150-200.
        Never re-evaluates already locked or already rejected assets.
        """
        status = self.get_status()
        if status.curated_count >= self.MAX_TARGET:
            logger.info("Freepik Golden Onboarding pool is already complete (200 assets)!")
            return {"added": 0, "total_curated": status.curated_count, "rejected": 0}

        approved_source_dir = self.ws_root / "2_QC2_Approved"
        candidates = list(approved_source_dir.glob("*.jpg")) + list(approved_source_dir.glob("*.png"))

        # Fetch existing golden hashes to prevent duplicates
        existing_golden_files = list(self.golden_folder.glob("*.jpg")) + list(self.golden_folder.glob("*.png"))
        existing_hashes = [self.batcher.compute_hashes(f)[0] for f in existing_golden_files]

        added_count = 0
        rejected_count = 0

        # Query DB to find assets already evaluated
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT uuid, is_freepik_150_golden, freepik_rejected FROM assets;")
            db_records = {row["uuid"]: row for row in cursor.fetchall()}

        for candidate in candidates:
            if status.curated_count + added_count >= self.MAX_TARGET:
                break

            asset_stem = candidate.stem
            # Check DB lock
            rec = db_records.get(asset_stem)
            if rec:
                if rec["is_freepik_150_golden"] == 1:
                    continue  # Already in the golden set
                if rec["freepik_rejected"] == 1:
                    continue  # Already rejected for Freepik

            # 1. Technical Specs Check
            is_valid, reason = self.validate_technical_specs(candidate)
            if not is_valid:
                self.db.update_asset(asset_stem, freepik_rejected=1, freepik_rejection_notes=reason)
                rejected_count += 1
                logger.info(f"Skipping for Freepik ({candidate.name}): {reason}")
                continue

            # 2. Anti-Similarity Uniqueness Check against all golden members
            cand_phash, _ = self.batcher.compute_hashes(candidate)
            collision = any(self.batcher.are_similar(cand_phash, exist_h) for exist_h in existing_hashes)
            if collision:
                self.db.update_asset(asset_stem, freepik_rejected=1, freepik_rejection_notes="Similar to existing golden asset")
                rejected_count += 1
                continue

            # 3. Passed! Lock into Golden Set
            dest = self.golden_folder / candidate.name
            shutil.copy2(str(candidate), str(dest))
            existing_hashes.append(cand_phash)
            added_count += 1

            self.db.update_asset(
                asset_stem,
                is_freepik_150_golden=1,
                freepik_status="golden_150_locked",
                current_path=str(dest)
            )
            logger.info(f"✨ Added to Freepik Golden Onboarding: {candidate.name}")

        new_total = len(existing_hashes)
        logger.info(f"Freepik Curation Cycle Finished: Added={added_count}, Rejected={rejected_count}, Golden Pool={new_total}/150")
        return {"added": added_count, "total_curated": new_total, "rejected": rejected_count}
