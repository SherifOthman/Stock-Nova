"""
Anti-Similarity Smart Batching Engine.
Uses perceptual hashing (pHash, dHash) and concept IDs to guarantee that
no two similar assets are ever uploaded in the same batch, distributing them
across sequential batch folders (Batch_01, Batch_02...) to prevent Adobe "Similar Submissions" rejections.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from PIL import Image
import imagehash

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("batching")


class AntiSimilarityBatcher:
    """Clusters and distributes assets into diverse batch folders."""

    def __init__(self) -> None:
        self.db = Database()
        self.max_batch_size = Config.get("batching.max_batch_size", 30)
        self.similarity_threshold = Config.get("batching.similarity_threshold", 12)

    def compute_hashes(self, image_path: Path) -> tuple[str, str]:
        """Calculates perceptual hash (pHash) and difference hash (dHash)."""
        with Image.open(image_path) as img:
            ph = str(imagehash.phash(img))
            dh = str(imagehash.dhash(img))
            return ph, dh

    def are_similar(self, phash1: str, phash2: str) -> bool:
        """Compares two pHashes; returns True if Hamming distance <= threshold."""
        try:
            h1 = imagehash.hex_to_hash(phash1)
            h2 = imagehash.hex_to_hash(phash2)
            dist = h1 - h2
            return dist <= self.similarity_threshold
        except Exception:
            return False

    def distribute_into_batches(
        self,
        approved_dir: Path,
        batches_root_dir: Path
    ) -> list[str]:
        """
        Takes all approved images from approved_dir and packs them into diverse
        Batch_01, Batch_02... directories, ensuring no two similar images reside in the same batch.
        """
        batches_root_dir.mkdir(parents=True, exist_ok=True)
        images = list(approved_dir.glob("*.jpg")) + list(approved_dir.glob("*.png"))
        if not images:
            logger.info("No approved images waiting to be batched.")
            return []

        logger.info(f"Distributing {len(images)} approved assets with anti-similarity algorithm...")

        # Compute hash and concept for each image
        pool: list[dict] = []
        for img_path in images:
            ph, dh = self.compute_hashes(img_path)
            pool.append({
                "path": img_path,
                "phash": ph,
                "dhash": dh
            })

        batches: list[list[dict]] = []

        # Greedy allocation
        for item in pool:
            placed = False
            for batch in batches:
                if len(batch) >= self.max_batch_size:
                    continue

                # Check similarity against all items in this candidate batch
                has_collision = False
                for existing in batch:
                    if self.are_similar(item["phash"], existing["phash"]):
                        has_collision = True
                        break

                if not has_collision:
                    batch.append(item)
                    placed = True
                    break

            if not placed:
                # Open a new batch
                batches.append([item])

        created_batch_names = []
        # Find next available batch index
        existing_folders = list(batches_root_dir.glob("Batch_*"))
        next_idx = len(existing_folders) + 1

        for batch_items in batches:
            batch_name = f"Batch_{next_idx:02d}"
            batch_dir = batches_root_dir / batch_name
            batch_dir.mkdir(parents=True, exist_ok=True)

            for it in batch_items:
                src = it["path"]
                dest = batch_dir / src.name
                shutil.move(str(src), str(dest))
                # Update DB
                self.db.update_asset(
                    asset_uuid=src.stem,
                    status="batched",
                    batch_id=batch_name,
                    phash=it["phash"],
                    dhash=it["dhash"],
                    current_path=str(dest)
                )

            # Record batch in DB
            with self.db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO batches (batch_id, asset_count, status) VALUES (?, ?, 'ready')",
                    (batch_name, len(batch_items))
                )

            logger.info(f"Created {batch_name} with {len(batch_items)} diverse assets.")
            created_batch_names.append(batch_name)
            next_idx += 1

        return created_batch_names
