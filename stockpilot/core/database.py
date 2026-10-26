"""
Database schema and manager for Google Dots.
Handles SQLite operations for accounts, credits, assets (images & videos),
batches, and strategy learning with full ACID transactions.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path
from typing import Any, Generator

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("database")


class Database:
    """Singleton database manager for Google Dots."""

    _instance: Database | None = None

    def __new__(cls) -> Database:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.db_path = Config.get_path("paths.database")
        if not self.db_path:
            self.db_path = Path(r"d:\Stock Automation\data\google_dots.db")

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self._initialized = True

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a thread-safe connection context manager."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Initializes tables and indexes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Accounts table (Multi-tier: Free, Plus, Pro)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_name TEXT UNIQUE NOT NULL,
                    account_name TEXT,
                    email TEXT,
                    tier TEXT CHECK(tier IN ('free', 'plus', 'pro')) NOT NULL,
                    daily_video_credits_limit INTEGER DEFAULT 50,
                    daily_video_credits_used INTEGER DEFAULT 0,
                    daily_image_credits_used INTEGER DEFAULT 0,
                    pool_id TEXT,
                    status TEXT DEFAULT 'active',
                    browser TEXT DEFAULT 'chrome',
                    profile_dir TEXT,
                    last_error TEXT,
                    error_action_hint TEXT,
                    last_error_time DATETIME,
                    last_used_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Dynamic migration check for existing accounts table
            cursor.execute("PRAGMA table_info(accounts);")
            existing_cols = {col["name"] for col in cursor.fetchall()}
            if "account_name" not in existing_cols:
                cursor.execute("ALTER TABLE accounts ADD COLUMN account_name TEXT;")
            if "browser" not in existing_cols:
                cursor.execute("ALTER TABLE accounts ADD COLUMN browser TEXT DEFAULT 'chrome';")
            if "profile_dir" not in existing_cols:
                cursor.execute("ALTER TABLE accounts ADD COLUMN profile_dir TEXT;")
            if "last_error" not in existing_cols:
                cursor.execute("ALTER TABLE accounts ADD COLUMN last_error TEXT;")
            if "error_action_hint" not in existing_cols:
                cursor.execute("ALTER TABLE accounts ADD COLUMN error_action_hint TEXT;")
            if "last_error_time" not in existing_cols:
                cursor.execute("ALTER TABLE accounts ADD COLUMN last_error_time DATETIME;")

            # Platform Alerts & Connection Health Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS platform_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_identifier TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    action_hint TEXT NOT NULL,
                    severity TEXT DEFAULT 'warning',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved INTEGER DEFAULT 0
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON platform_alerts(resolved);")

            # 2. Shared Credit Pools (Plus 200, Pro 1000)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credit_pools (
                    pool_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    total_credits INTEGER NOT NULL,
                    remaining_credits INTEGER NOT NULL,
                    target_consumption_days INTEGER DEFAULT 12,
                    daily_target_credits INTEGER DEFAULT 80,
                    used_today INTEGER DEFAULT 0,
                    last_reset_date DATE,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 3. Assets Table (Both Video & Image)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE NOT NULL,
                    asset_type TEXT CHECK(asset_type IN ('video', 'image')) NOT NULL,
                    filename TEXT NOT NULL,
                    original_prompt TEXT NOT NULL,
                    concept_id TEXT,
                    model_used TEXT,
                    category TEXT,
                    subject_type TEXT,
                    lighting_style TEXT,
                    visual_pattern TEXT,
                    generated_by_profile TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    phash TEXT,
                    dhash TEXT,
                    status TEXT NOT NULL DEFAULT 'downloaded',
                    qc1_feedback TEXT,
                    qc2_feedback TEXT,
                    opencv_sharpness REAL,
                    opencv_noise REAL,
                    seo_title TEXT,
                    seo_keywords TEXT,
                    batch_id TEXT,
                    adobe_asset_id TEXT,
                    adobe_rejection_reason TEXT,
                    current_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                );
            """)

            # Dynamic migration check for commercial sales and downloads columns on assets
            cursor.execute("PRAGMA table_info(assets);")
            asset_cols = {col["name"] for col in cursor.fetchall()}
            if "adobe_downloads" not in asset_cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN adobe_downloads INTEGER DEFAULT 0;")
            if "adobe_earnings" not in asset_cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN adobe_earnings REAL DEFAULT 0.0;")
            if "freepik_downloads" not in asset_cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN freepik_downloads INTEGER DEFAULT 0;")
            if "freepik_earnings" not in asset_cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN freepik_earnings REAL DEFAULT 0.0;")
            if "total_downloads" not in asset_cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN total_downloads INTEGER DEFAULT 0;")
            if "last_download_date" not in asset_cols:
                cursor.execute("ALTER TABLE assets ADD COLUMN last_download_date DATETIME;")

            # 4. Anti-Similarity Batches
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT UNIQUE NOT NULL,
                    target_platform TEXT DEFAULT 'adobe_stock',
                    asset_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'building',
                    csv_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    uploaded_at DATETIME,
                    submitted_at DATETIME
                );
            """)

            # 5. Strategy Learnings & Auto-Pivot
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_or_concept TEXT UNIQUE NOT NULL,
                    category TEXT,
                    total_submitted INTEGER DEFAULT 0,
                    total_accepted INTEGER DEFAULT 0,
                    total_rejected INTEGER DEFAULT 0,
                    rejection_rate REAL DEFAULT 0.0,
                    action_taken TEXT DEFAULT 'active',
                    reason TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 6. Gemini API Keys
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gemini_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_alias TEXT UNIQUE NOT NULL,
                    api_key TEXT NOT NULL,
                    priority INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'active',
                    cooldown_until DATETIME,
                    requests_today INTEGER DEFAULT 0,
                    last_used_at DATETIME
                );
            """)

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_batch ON assets(batch_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_concept ON assets(concept_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);")

        logger.info(f"Database initialized successfully at {self.db_path}")

    # --- Account & Quota Operations ---
    def sync_accounts_config(self, config_data: dict[str, Any]) -> None:
        """Syncs accounts and credit pools from accounts_config.json into DB."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Pools
            pools = config_data.get("credit_strategy", {})
            for pool_key in ["plus_pool", "pro_pool"]:
                if pool_key in pools:
                    p = pools[pool_key]
                    tier = "plus" if "plus" in pool_key else "pro"
                    cursor.execute("""
                        INSERT INTO credit_pools (
                            pool_id, tier, total_credits, remaining_credits,
                            target_consumption_days, daily_target_credits, last_reset_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(pool_id) DO UPDATE SET
                            total_credits = excluded.total_credits,
                            target_consumption_days = excluded.target_consumption_days,
                            daily_target_credits = excluded.daily_target_credits;
                    """, (
                        pool_key, tier, p.get("total_credits", 200),
                        p.get("total_credits", 200),
                        p.get("target_consumption_days", 10),
                        p.get("daily_target_credits", 20),
                        date.today().isoformat()
                    ))

            # Accounts
            for acc in config_data.get("accounts", []):
                tier = acc.get("tier", "free")
                limit = acc.get("daily_video_credits", 50 if tier == "free" else 0)
                cursor.execute("""
                    INSERT INTO accounts (profile_name, tier, daily_video_credits_limit, pool_id, status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(profile_name) DO UPDATE SET
                        tier = excluded.tier,
                        daily_video_credits_limit = excluded.daily_video_credits_limit,
                        pool_id = excluded.pool_id;
                """, (
                    acc["profile_name"], tier, limit,
                    acc.get("pool_id"),
                    "active" if acc.get("enabled", True) else "disabled"
                ))

    def record_generation(self, profile_name: str, asset_type: str, credits_spent: int = 1) -> None:
        """Records credit usage on an account and its shared pool."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Fetch account
            cursor.execute("SELECT tier, pool_id FROM accounts WHERE profile_name = ?", (profile_name,))
            row = cursor.fetchone()
            if not row:
                return

            tier, pool_id = row["tier"], row["pool_id"]

            if asset_type == "video":
                cursor.execute("""
                    UPDATE accounts 
                    SET daily_video_credits_used = daily_video_credits_used + ?,
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE profile_name = ?
                """, (credits_spent, profile_name))
            else:
                cursor.execute("""
                    UPDATE accounts 
                    SET daily_image_credits_used = daily_image_credits_used + ?,
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE profile_name = ?
                """, (credits_spent, profile_name))

            # Deduct from shared pool if applicable
            if pool_id:
                cursor.execute("""
                    UPDATE credit_pools
                    SET remaining_credits = MAX(0, remaining_credits - ?),
                        used_today = used_today + ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE pool_id = ?
                """, (credits_spent, credits_spent, pool_id))

    def insert_asset(self, asset_data: dict[str, Any]) -> str:
        """Inserts a generated asset record into the database."""
        asset_uuid = asset_data.get("uuid") or str(uuid.uuid4())
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO assets (
                    uuid, asset_type, filename, original_prompt, concept_id,
                    model_used, category, subject_type, lighting_style,
                    visual_pattern, generated_by_profile, duration_seconds,
                    status, current_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asset_uuid,
                asset_data["asset_type"],
                asset_data["filename"],
                asset_data["original_prompt"],
                asset_data.get("concept_id"),
                asset_data.get("model_used"),
                asset_data.get("category"),
                asset_data.get("subject_type"),
                asset_data.get("lighting_style"),
                asset_data.get("visual_pattern"),
                asset_data.get("generated_by_profile"),
                asset_data.get("duration_seconds", 0),
                asset_data.get("status", "downloaded"),
                str(asset_data.get("current_path", ""))
            ))
        return asset_uuid

    def update_asset(self, asset_identifier: str, **kwargs: Any) -> None:
        """Dynamically updates fields for an asset by UUID or filename stem. Inserts if not found."""
        if not kwargs:
            return
        fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values())
        values.extend([asset_identifier, f"{asset_identifier}%"])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE assets SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE uuid = ? OR filename LIKE ?",
                values
            )
            if cursor.rowcount == 0:
                # Insert newly encountered file
                new_uuid = str(uuid.uuid4())
                filename = kwargs.get("filename") or f"{asset_identifier}.jpg"
                status = kwargs.get("status", "in_pipeline")
                prompt_fallback = kwargs.get("original_prompt") or filename.replace("_", " ").replace(".jpg", "").replace(".png", "")
                conn.execute("""
                    INSERT INTO assets (uuid, filename, asset_type, status, model_used, original_prompt)
                    VALUES (?, ?, 'image', ?, 'nano banana pro', ?)
                """, (new_uuid, filename, status, prompt_fallback))
                # Now re-apply updates
                re_values = list(kwargs.values())
                re_values.append(new_uuid)
                conn.execute(
                    f"UPDATE assets SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE uuid = ?",
                    re_values
                )

    def get_concept_asset_count(self, concept_id: str) -> int:
        """Returns the number of assets generated for a specific concept (to enforce micro-batch limits)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM assets WHERE concept_id = ?", (concept_id,))
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def get_acceptance_rate(self) -> float:
        """Calculates current Adobe Stock acceptance rate."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN status = 'adobe_accepted' THEN 1 END) as accepted,
                    COUNT(CASE WHEN status IN ('adobe_accepted', 'adobe_rejected') THEN 1 END) as total
                FROM assets;
            """)
            row = cursor.fetchone()
            if row and row["total"] > 0:
                return float(row["accepted"]) / float(row["total"])
            return 0.0  # 0.0% when no assets reviewed yet

    def get_video_stats(self) -> dict[str, Any]:
        """Returns comprehensive video review metrics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_videos,
                    COUNT(CASE WHEN status IN ('qc2_pass', 'uploaded', 'adobe_accepted') THEN 1 END) as passed_videos,
                    COUNT(CASE WHEN status IN ('qc1_fail', 'qc2_fail', 'adobe_rejected') THEN 1 END) as rejected_videos,
                    COUNT(CASE WHEN qc1_feedback LIKE '%cut%' OR qc2_feedback LIKE '%cut%' THEN 1 END) as cut_issues,
                    COUNT(CASE WHEN qc1_feedback LIKE '%warp%' OR qc2_feedback LIKE '%warp%' THEN 1 END) as warp_issues,
                    COUNT(CASE WHEN qc1_feedback LIKE '%audio%' OR qc2_feedback LIKE '%audio%' THEN 1 END) as audio_issues
                FROM assets 
                WHERE asset_type = 'video';
            """)
            row = cursor.fetchone()
            return {
                "total_scanned": row["total_videos"] if row else 0,
                "passed": row["passed_videos"] if row else 0,
                "rejected": row["rejected_videos"] if row else 0,
                "issues": {
                    "scene_cuts": row["cut_issues"] if row else 0,
                    "warping_morphing": row["warp_issues"] if row else 0,
                    "audio_detected": row["audio_issues"] if row else 0
                }
            }

    def get_dual_platform_breakdown(self) -> dict[str, Any]:
        """Calculates exact asset distribution between Adobe Stock and Freepik."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_vault_assets,
                    COUNT(CASE WHEN asset_type = 'image' THEN 1 END) as total_images,
                    COUNT(CASE WHEN asset_type = 'video' THEN 1 END) as total_videos,
                    
                    -- Adobe Stock numbers
                    COUNT(CASE WHEN adobe_status = 'uploaded' THEN 1 END) as adobe_uploaded,
                    COUNT(CASE WHEN adobe_status = 'accepted' THEN 1 END) as adobe_accepted,
                    COUNT(CASE WHEN adobe_status = 'rejected' THEN 1 END) as adobe_rejected,
                    COUNT(CASE WHEN (adobe_status = 'pending' OR adobe_status IS NULL) AND status = 'qc2_pass' THEN 1 END) as adobe_pending_ready,
                    
                    -- Freepik numbers (Photos only)
                    COUNT(CASE WHEN is_freepik_150_golden = 1 THEN 1 END) as freepik_golden_curated,
                    COUNT(CASE WHEN freepik_status = 'uploaded' THEN 1 END) as freepik_uploaded,
                    COUNT(CASE WHEN freepik_status = 'accepted' THEN 1 END) as freepik_accepted,
                    COUNT(CASE WHEN freepik_status = 'rejected' THEN 1 END) as freepik_rejected,
                    COUNT(CASE WHEN asset_type = 'image' AND status = 'qc2_pass' AND (freepik_status IS NULL OR freepik_status != 'uploaded') THEN 1 END) as freepik_available_pool
                FROM assets;
            """)
            r = cursor.fetchone()
            return dict(r) if r else {}

    def upsert_account(
        self,
        profile_name: str,
        account_name: str = "",
        email: str = "",
        tier: str = "free",
        pool_id: str | None = None,
        daily_limit: int = 50,
        browser: str = "chrome",
        profile_dir: str = "Default",
        status: str = "active",
        last_error: str = "",
        action_hint: str = ""
    ) -> None:
        """Inserts or updates an account with real Google account name and Gmail address."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO accounts (
                    profile_name, account_name, email, tier, daily_video_credits_limit,
                    pool_id, status, browser, profile_dir, last_error, error_action_hint,
                    last_error_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? != '' THEN CURRENT_TIMESTAMP ELSE NULL END)
                ON CONFLICT(profile_name) DO UPDATE SET
                    account_name = COALESCE(NULLIF(excluded.account_name, ''), accounts.account_name),
                    email = COALESCE(NULLIF(excluded.email, ''), accounts.email),
                    tier = excluded.tier,
                    daily_video_credits_limit = excluded.daily_video_credits_limit,
                    pool_id = excluded.pool_id,
                    status = excluded.status,
                    browser = excluded.browser,
                    profile_dir = excluded.profile_dir,
                    last_error = excluded.last_error,
                    error_action_hint = excluded.error_action_hint,
                    last_error_time = CASE WHEN excluded.last_error != '' THEN CURRENT_TIMESTAMP ELSE accounts.last_error_time END;
            """, (
                profile_name, account_name, email, tier, daily_limit,
                pool_id, status, browser, profile_dir, last_error, action_hint,
                last_error
            ))

    def get_detailed_accounts(self) -> list[dict[str, Any]]:
        """Returns all accounts ordered by tier and usage with full identity metadata."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    id, profile_name, account_name, email, tier,
                    daily_video_credits_limit, daily_video_credits_used, daily_image_credits_used,
                    pool_id, status, browser, profile_dir, last_error, error_action_hint,
                    last_error_time, last_used_at, created_at
                FROM accounts
                ORDER BY 
                    CASE tier WHEN 'pro' THEN 1 WHEN 'plus' THEN 2 ELSE 3 END,
                    id ASC;
            """)
            return [dict(r) for r in cursor.fetchall()]

    def record_platform_alert(
        self,
        platform: str,
        account_identifier: str,
        error_type: str,
        error_message: str,
        action_hint: str,
        severity: str = "warning"
    ) -> int:
        """Records an active connection or platform error to surface in the dashboard."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # If an identical active alert exists, update timestamp and message
            cursor.execute("""
                SELECT id FROM platform_alerts 
                WHERE platform = ? AND account_identifier = ? AND resolved = 0;
            """, (platform, account_identifier))
            existing = cursor.fetchone()
            if existing:
                alert_id = existing["id"]
                cursor.execute("""
                    UPDATE platform_alerts 
                    SET error_type = ?, error_message = ?, action_hint = ?, severity = ?, created_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                """, (error_type, error_message, action_hint, severity, alert_id))
                return alert_id
            else:
                cursor.execute("""
                    INSERT INTO platform_alerts (
                        platform, account_identifier, error_type, error_message, action_hint, severity, resolved
                    ) VALUES (?, ?, ?, ?, ?, ?, 0);
                """, (platform, account_identifier, error_type, error_message, action_hint, severity))
                return cursor.lastrowid

    def resolve_platform_alert(self, alert_id: int) -> None:
        """Marks an alert as resolved."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE platform_alerts SET resolved = 1 WHERE id = ?;", (alert_id,))

    def clear_platform_alerts(self, platform: str, account_identifier: str = "") -> None:
        """Clears active alerts for a specific platform or account when connection succeeds."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if account_identifier:
                cursor.execute("""
                    UPDATE platform_alerts SET resolved = 1 
                    WHERE platform = ? AND account_identifier = ? AND resolved = 0;
                """, (platform, account_identifier))
            else:
                cursor.execute("""
                    UPDATE platform_alerts SET resolved = 1 
                    WHERE platform = ? AND resolved = 0;
                """, (platform,))

    def get_active_platform_alerts(self) -> list[dict[str, Any]]:
        """Returns all unresolved platform errors sorted by urgency and time."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, platform, account_identifier, error_type, error_message, action_hint, severity, created_at
                FROM platform_alerts
                WHERE resolved = 0
                ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, id DESC;
            """)
            return [dict(r) for r in cursor.fetchall()]

    def update_account_health(
        self,
        profile_name: str,
        status: str,
        last_error: str = "",
        action_hint: str = ""
    ) -> None:
        """Updates health status of a specific account."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE accounts 
                SET status = ?, 
                    last_error = ?,
                    error_action_hint = ?,
                    last_error_time = CASE WHEN ? != '' THEN CURRENT_TIMESTAMP ELSE last_error_time END
                WHERE profile_name = ?;
            """, (status, last_error, action_hint, last_error, profile_name))

    def record_asset_downloads(
        self,
        identifier: str,
        platform: str = "adobe",
        downloads: int = 1,
        earnings: float = 0.0
    ) -> bool:
        """
        Updates download counts and earnings for an asset identified by filename, stem, uuid, or adobe_asset_id.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            clean_id = Path(identifier).stem
            cursor.execute("""
                SELECT id, filename, adobe_downloads, freepik_downloads, adobe_earnings, freepik_earnings
                FROM assets
                WHERE filename = ? OR filename LIKE ? OR uuid = ? OR adobe_asset_id = ?
                LIMIT 1;
            """, (identifier, f"{clean_id}%", identifier, identifier))
            row = cursor.fetchone()
            if not row:
                return False

            asset_id = row["id"]
            if platform.lower() == "adobe":
                new_ad_dl = (row["adobe_downloads"] or 0) + int(downloads)
                new_ad_earn = round((row["adobe_earnings"] or 0.0) + float(earnings), 2)
                new_fp_dl = row["freepik_downloads"] or 0
                new_fp_earn = row["freepik_earnings"] or 0.0
            else:
                new_ad_dl = row["adobe_downloads"] or 0
                new_ad_earn = row["adobe_earnings"] or 0.0
                new_fp_dl = (row["freepik_downloads"] or 0) + int(downloads)
                new_fp_earn = round((row["freepik_earnings"] or 0.0) + float(earnings), 2)

            total_dl = new_ad_dl + new_fp_dl

            cursor.execute("""
                UPDATE assets
                SET adobe_downloads = ?,
                    adobe_earnings = ?,
                    freepik_downloads = ?,
                    freepik_earnings = ?,
                    total_downloads = ?,
                    last_download_date = CURRENT_TIMESTAMP
                WHERE id = ?;
            """, (new_ad_dl, new_ad_earn, new_fp_dl, new_fp_earn, total_dl, asset_id))
            return True

    def get_downloads_performance_analytics(self) -> dict[str, Any]:
        """
        Calculates commercial portfolio monetization metrics:
        - Total downloads on Adobe vs Freepik
        - Count of downloaded assets (best sellers) vs zero-download assets
        - Monetization conversion percentage
        - Top 12 downloaded assets ordered by sales
        - Category breakdown of sales
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Global downloads stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_tracked_assets,
                    COALESCE(SUM(total_downloads), 0) as total_downloads_all,
                    COALESCE(SUM(adobe_downloads), 0) as adobe_total_downloads,
                    COALESCE(SUM(adobe_earnings), 0.0) as adobe_total_earnings,
                    COALESCE(SUM(freepik_downloads), 0) as freepik_total_downloads,
                    COALESCE(SUM(freepik_earnings), 0.0) as freepik_total_earnings,
                    COUNT(CASE WHEN total_downloads > 0 THEN 1 END) as downloaded_assets_count,
                    COUNT(CASE WHEN (total_downloads = 0 OR total_downloads IS NULL) AND (status IN ('uploaded', 'adobe_accepted', 'qc2_pass') OR is_freepik_150_golden = 1) THEN 1 END) as zero_download_assets_count
                FROM assets;
            """)
            g = dict(cursor.fetchone() or {})
            total_dl = g.get("total_downloads_all", 0)
            dl_count = g.get("downloaded_assets_count", 0)
            zero_count = g.get("zero_download_assets_count", 0)
            total_active = dl_count + zero_count
            conv_rate = round((dl_count / total_active * 100), 1) if total_active > 0 else 0.0

            # Top Downloaded Assets
            cursor.execute("""
                SELECT 
                    uuid, filename, asset_type, model_used, category, subject_type,
                    status, adobe_status, freepik_status, is_freepik_150_golden,
                    COALESCE(adobe_downloads, 0) as adobe_downloads,
                    COALESCE(adobe_earnings, 0.0) as adobe_earnings,
                    COALESCE(freepik_downloads, 0) as freepik_downloads,
                    COALESCE(freepik_earnings, 0.0) as freepik_earnings,
                    COALESCE(total_downloads, 0) as total_downloads,
                    last_download_date
                FROM assets
                WHERE total_downloads > 0
                ORDER BY total_downloads DESC, adobe_earnings DESC
                LIMIT 12;
            """)
            top_downloaded = [dict(r) for r in cursor.fetchall()]

            # Sample of zero-download assets for strategy evaluation
            cursor.execute("""
                SELECT 
                    uuid, filename, asset_type, category, subject_type, status,
                    COALESCE(total_downloads, 0) as total_downloads
                FROM assets
                WHERE (total_downloads = 0 OR total_downloads IS NULL)
                  AND (status IN ('uploaded', 'adobe_accepted', 'qc2_pass') OR is_freepik_150_golden = 1)
                ORDER BY id DESC
                LIMIT 10;
            """)
            zero_downloads_sample = [dict(r) for r in cursor.fetchall()]

            # Downloads by category
            cursor.execute("""
                SELECT 
                    COALESCE(category, 'General Commercial') as category_name,
                    COUNT(*) as asset_count,
                    COALESCE(SUM(total_downloads), 0) as category_downloads,
                    COALESCE(SUM(adobe_earnings + freepik_earnings), 0.0) as category_earnings
                FROM assets
                WHERE total_downloads > 0
                GROUP BY COALESCE(category, 'General Commercial')
                ORDER BY category_downloads DESC
                LIMIT 6;
            """)
            by_category = [dict(r) for r in cursor.fetchall()]

            return {
                "total_downloads_all": total_dl,
                "adobe": {
                    "downloads": g.get("adobe_total_downloads", 0),
                    "earnings": round(g.get("adobe_total_earnings", 0.0), 2)
                },
                "freepik": {
                    "downloads": g.get("freepik_total_downloads", 0),
                    "earnings": round(g.get("freepik_total_earnings", 0.0), 2)
                },
                "downloaded_assets_count": dl_count,
                "zero_download_assets_count": zero_count,
                "monetization_rate_pct": conv_rate,
                "total_earnings_usd": round(g.get("adobe_total_earnings", 0.0) + g.get("freepik_total_earnings", 0.0), 2),
                "top_downloaded_assets": top_downloaded,
                "zero_downloads_sample": zero_downloads_sample,
                "downloads_by_category": by_category
            }

    def import_contributor_sales_data(self, platform: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Ingests parsed sales rows from Adobe Stock or Freepik Contributor CSV.
        Matches filename, title, or asset ID and updates download counts.
        """
        updated = 0
        total_dl_added = 0
        for r in records:
            ident = r.get("filename") or r.get("file_name") or r.get("title") or r.get("asset_id") or ""
            if not ident:
                continue
            dl = int(r.get("downloads", 1) or 1)
            earn = float(r.get("earnings", 0.0) or r.get("royalties", 0.0) or 0.0)
            if self.record_asset_downloads(ident, platform, dl, earn):
                updated += 1
                total_dl_added += dl

        return {
            "status": "success",
            "platform": platform,
            "updated_assets": updated,
            "total_downloads_added": total_dl_added
        }
