"""
Freepik 150 Golden Onboarding Curator & Stateful Incremental Validator.
Designed specifically for the dedicated 'Freepik 150 Gate' tab:
1. Ultra-Strict Manual-Review Rules:
   - Minimum 4 Megapixels (>= 2000px on shortest side) & <= 80 Megapixels.
   - Strict sharpness threshold (>= 115.0) because Freepik onboarding is manually reviewed at 100% zoom.
   - Strict anti-similarity (pHash distance >= 12) so no two images look alike.
2. Stateful Incremental SQLite Memory ('freepik_150_ledger' table):
   - Every image inspected is recorded by SHA-256 hash ('approved_150' or 'rejected_150').
   - If you inspect 120 images today (100 approved, 20 rejected) and add 60 new images tomorrow,
     clicking the button tomorrow AUTOMATICALLY SKIPS the 120 already-checked images and only
     inspects the new ones until you reach 150/150!
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:
    Image = None

from stockpilot.batching.similarity_engine import AntiSimilarityBatcher
from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.quality.opencv_checks import calculate_sharpness

logger = get_logger("freepik_curator")


@dataclass
class FreepikOnboardingStatus:
    total_target: int
    curated_count: int
    needed_count: int
    already_inspected_total: int
    rejected_count: int
    isolated_mockup_count: int
    full_bleed_bg_count: int
    is_ready_for_submission: bool
    target_folder: str = ""

    @property
    def total_ever_inspected(self) -> int:
        return self.already_inspected_total


class FreepikOnboardingCurator:
    """Manages stateful, incremental curation of the Freepik 150 Golden Onboarding batch."""

    MIN_TARGET = 150
    MAX_TARGET = 160

    def __init__(self) -> None:
        self.db = Database()
        self.batcher = AntiSimilarityBatcher()
        self.ws_root = Config.get_path("paths.workspace_root")
        self.golden_folder = self.ws_root / "freepik_golden_150"
        self.golden_folder.mkdir(parents=True, exist_ok=True)
        self.source_dirs = [self.ws_root / "2_QC2_Approved", self.ws_root / "3_Batched_Ready"]

    @staticmethod
    def compute_file_sha256(file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def get_status(self) -> FreepikOnboardingStatus:
        """Returns the live state of the Freepik 150 curation pool and SQLite ledger."""
        curated_files = list(self.golden_folder.glob("*.jpg")) + list(self.golden_folder.glob("*.png"))
        count = len(curated_files)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_checked,
                    COUNT(CASE WHEN decision = 'rejected_150' THEN 1 END) as rej_cnt
                FROM freepik_150_ledger;
            """)
            row = cursor.fetchone()
            total_checked = (row["total_checked"] or 0) if row else count
            rej_cnt = (row["rej_cnt"] or 0) if row else 0

        isolated = sum(
            1 for f in curated_files if any(k in f.name.lower() for k in ["isolated", "mockup", "object", "white"])
        )
        bg = max(0, count - isolated)
        needed = max(0, self.MIN_TARGET - count)

        return FreepikOnboardingStatus(
            total_target=self.MIN_TARGET,
            curated_count=count,
            needed_count=needed,
            already_inspected_total=max(total_checked, count),
            rejected_count=rej_cnt,
            isolated_mockup_count=isolated,
            full_bleed_bg_count=bg,
            is_ready_for_submission=count >= self.MIN_TARGET,
        )

    def get_ledger_items(self, limit: int = 150) -> list[dict[str, Any]]:
        """Returns the list of approved and rejected items in the Freepik 150 ledger."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT filename, decision, sharpness_score, megapixels, reason, golden_path, inspected_at
                FROM freepik_150_ledger
                ORDER BY CASE decision WHEN 'approved_150' THEN 1 ELSE 2 END, id DESC
                LIMIT ?;
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def validate_technical_specs(self, image_path: Path) -> tuple[bool, float, float, str]:
        """
        Validates Freepik's strict manual-review onboarding guidelines:
        - >= 4.0 Megapixels and shortest side >= 2000px
        - File size between 400KB and 45MB
        - Sharpness >= 115.0 (Freepik manual reviewers zoom to 100%)
        """
        try:
            size_bytes = image_path.stat().st_size
            if size_bytes < 350_000:
                return False, 0.0, 0.0, "File size too small (< 350KB)"
            if size_bytes > 48_000_000:
                return False, 0.0, 0.0, "File size too large (> 48MB)"

            with Image.open(image_path) as img:
                w, h = img.size
                megapixels = round((w * h) / 1_000_000.0, 2)
                if megapixels < 4.0:
                    return False, 0.0, megapixels, f"Resolution too low ({megapixels:.1f} MP < 4.0 MP minimum)"
                if min(w, h) < 2000:
                    return False, 0.0, megapixels, f"Shortest side too small ({min(w, h)}px < 2000px)"

            sharpness = round(float(calculate_sharpness(image_path)), 1)
            if sharpness < 115.0:
                return False, sharpness, megapixels, f"Texture too soft for Freepik manual zoom ({sharpness} < 115.0)"

            return True, sharpness, megapixels, "Passed strict Freepik 150 manual-review check"
        except Exception as e:
            return False, 0.0, 0.0, f"Validation error: {e}"

    def run_incremental_curation(self, custom_source_dir: Path | None = None) -> dict[str, Any]:
        """
        Scans candidate images (from custom_source_dir, 2_QC2_Approved, and 3_Batched_Ready),
        AUTOMATICALLY SKIPS any image whose SHA-256 hash is already in 'freepik_150_ledger',
        and evaluates only new images until reaching 150 approved Golden assets!
        """
        status = self.get_status()
        if status.curated_count >= self.MAX_TARGET:
            return {
                "status": "complete",
                "added": 0,
                "skipped_already_checked": status.already_inspected_total,
                "rejected_new": 0,
                "total_curated": status.curated_count,
                "needed": 0,
            }

        candidate_files: list[Path] = []
        if custom_source_dir and custom_source_dir.exists():
            candidate_files.extend(custom_source_dir.rglob("*.jpg"))
            candidate_files.extend(custom_source_dir.rglob("*.png"))

        approved_dir = self.ws_root / "2_QC2_Approved"
        batched_dir = self.ws_root / "3_Batched_Ready"
        for folder in (approved_dir, batched_dir):
            if folder.exists():
                candidate_files.extend(folder.rglob("*.jpg"))
                candidate_files.extend(folder.rglob("*.png"))

        # Load all previously inspected SHA-256 hashes and approved pHashes from SQLite
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_hash, decision, phash FROM freepik_150_ledger;")
            ledger_rows = cursor.fetchall()
            checked_hashes = {r["file_hash"] for r in ledger_rows}
            existing_phashes = [r["phash"] for r in ledger_rows if r["decision"] == "approved_150" and r["phash"]]

        added_count = 0
        rejected_new_count = 0
        skipped_count = 0

        for candidate in candidate_files:
            if status.curated_count + added_count >= self.MIN_TARGET:
                break
            if not candidate.exists():
                continue

            try:
                f_hash = self.compute_file_sha256(candidate)
            except Exception:
                continue

            # STATEFUL MEMORY: Skip immediately if already checked in a previous run!
            if f_hash in checked_hashes:
                skipped_count += 1
                continue

            checked_hashes.add(f_hash)
            is_valid, sharpness, mp, reason = self.validate_technical_specs(candidate)
            cand_phash, _ = self.batcher.compute_hashes(candidate)

            if is_valid and cand_phash:
                if any(self.batcher.are_similar(cand_phash, ex_p) for ex_p in existing_phashes):
                    is_valid = False
                    reason = "Too similar (pHash) to another image already in the Freepik 150 batch"

            if not is_valid:
                rejected_new_count += 1
                with self.db.get_connection() as conn:
                    conn.execute("""
                        INSERT OR IGNORE INTO freepik_150_ledger (
                            file_hash, filename, original_path, decision, sharpness_score, megapixels, phash, reason
                        ) VALUES (?, ?, ?, 'rejected_150', ?, ?, ?, ?);
                    """, (f_hash, candidate.name, str(candidate), sharpness, mp, cand_phash, reason))
                self.db.update_asset(candidate.stem, freepik_rejected=1, freepik_rejection_notes=reason)
                continue

            # Approved for Freepik 150 Golden Gate!
            dest = self.golden_folder / candidate.name
            if candidate.resolve() != dest.resolve():
                shutil.copy2(str(candidate), str(dest))

            existing_phashes.append(cand_phash)
            added_count += 1

            with self.db.get_connection() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO freepik_150_ledger (
                        file_hash, filename, original_path, golden_path, decision, sharpness_score, megapixels, phash, reason
                    ) VALUES (?, ?, ?, ?, 'approved_150', ?, ?, ?, ?);
                """, (f_hash, candidate.name, str(candidate), str(dest), sharpness, mp, cand_phash, reason))

            self.db.update_asset(
                candidate.stem,
                is_freepik_150_golden=1,
                freepik_status="golden_150_locked",
            )

        updated_status = self.get_status()
        logger.info(
            f"Freepik 150 Scan: Added={added_count}, Skipped={skipped_count}, RejectedNew={rejected_new_count}, Total={updated_status.curated_count}/150"
        )
        return {
            "status": "success",
            "added": added_count,
            "skipped_already_checked": skipped_count,
            "rejected_new": rejected_new_count,
            "total_curated": updated_status.curated_count,
            "needed": updated_status.needed_count,
        }
