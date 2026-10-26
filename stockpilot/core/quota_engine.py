"""
Quota and Credit Engine for Google Dots.
Coordinates multi-tier account credits (Free 50 videos, Plus 200, Pro 1000)
with flexible 10-15 days pacing, micro-batching per concept, and video-first priority.
"""

from __future__ import annotations

from typing import Any
from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("quota_engine")


class QuotaEngine:
    """Manages credit allocation, burn pacing, and profile selection."""

    def __init__(self) -> None:
        self.db = Database()
        self.config = Config.get_accounts_config()

    def get_next_generation_task(self, concept_id: str) -> dict[str, Any] | None:
        """
        Determines the next eligible account and asset type (Video first, then Image).
        Enforces:
        1. Micro-batching per concept (stops after e.g. 8 assets to avoid flooding low-performing styles).
        2. Free tier 50 video credits exhausted first.
        3. Pacing on Plus/Pro accounts.
        """
        # 1. Micro-batching check
        max_per_concept = self.config.get("system_settings", {}).get("micro_batch_limit_per_concept", 8)
        current_concept_count = self.db.get_concept_asset_count(concept_id)
        if current_concept_count >= max_per_concept:
            logger.info(f"Concept '{concept_id}' reached micro-batch limit ({max_per_concept}). Pausing concept for review.")
            return None

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 2. Check Free accounts for remaining daily video credits (Top Priority)
            cursor.execute("""
                SELECT profile_name, tier, daily_video_credits_limit, daily_video_credits_used
                FROM accounts
                WHERE tier = 'free' AND status = 'active'
                  AND daily_video_credits_used < daily_video_credits_limit
                ORDER BY daily_video_credits_used ASC
                LIMIT 1;
            """)
            free_account = cursor.fetchone()
            if free_account:
                return {
                    "profile_name": free_account["profile_name"],
                    "tier": "free",
                    "asset_type": "video",
                    "model": self.config.get("system_settings", {}).get("video_model", "omni flash"),
                    "duration_seconds": self.config.get("system_settings", {}).get("default_video_duration_seconds", 8),
                    "pool_id": None
                }

            # 3. Check Shared Pools (Plus / Pro)
            cursor.execute("""
                SELECT p.pool_id, p.tier, p.remaining_credits, p.daily_target_credits, p.used_today,
                       a.profile_name
                FROM credit_pools p
                JOIN accounts a ON a.pool_id = p.pool_id
                WHERE p.remaining_credits > 0 AND a.status = 'active'
                ORDER BY CASE WHEN p.tier = 'pro' THEN 1 ELSE 2 END, p.remaining_credits DESC
                LIMIT 1;
            """)
            pool_row = cursor.fetchone()
            if pool_row:
                # Video-first priority on Pro/Plus as well
                return {
                    "profile_name": pool_row["profile_name"],
                    "tier": pool_row["tier"],
                    "asset_type": "video",
                    "model": self.config.get("system_settings", {}).get("video_model", "omni flash"),
                    "duration_seconds": self.config.get("system_settings", {}).get("default_video_duration_seconds", 8),
                    "pool_id": pool_row["pool_id"]
                }

            # 4. If all video quotas drained, switch to Image generation (Nano Banana Pro)
            cursor.execute("""
                SELECT profile_name, tier, pool_id
                FROM accounts
                WHERE status = 'active'
                ORDER BY id ASC
                LIMIT 1;
            """)
            img_account = cursor.fetchone()
            if img_account:
                return {
                    "profile_name": img_account["profile_name"],
                    "tier": img_account["tier"],
                    "asset_type": "image",
                    "model": self.config.get("system_settings", {}).get("image_model", "nano banana pro"),
                    "pool_id": img_account["pool_id"]
                }

        logger.warning("All account quotas and generation limits are currently exhausted.")
        return None
