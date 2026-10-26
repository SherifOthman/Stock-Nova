"""
Database Schema and Manager for StockNova AI.
Handles SQLite operations (with WAL concurrency) for:
- Multi-account Gemini / Argon management (Free 50/day, Plus 200/mo, Pro 1000/mo + Primary Argon Brain flag)
- Agent Handoff Memory Snapshots (zero history loss when failing over between accounts)
- Daily Employee Shifts (Auto-Pilot state machine)
- Video Model Benchmarking (excluding 100-credit Quality modes)
- Assets (Videos & Images) with 3-tier calibrated QC (Approved, Borderline/Quick Look, Rejected)
- Independent Dual-Platform Tracking (Adobe Stock & Freepik)
- Dedicated Stateful Freepik 150 Gate Ledger (never re-checks already inspected photos)
- Persistent Adaptive Quality Rules & Strategy Learnings
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Generator

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("database")


class Database:
    """Singleton SQLite Database Manager for StockNova AI."""

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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self._initialized = True

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a thread-safe WAL connection context manager."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Initializes all tables, migrations, default pools, and indexes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Accounts Table (Free 50/day, Plus 200/mo, Pro 1000/mo + Primary Argon Brain)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_name TEXT UNIQUE NOT NULL,
                    account_name TEXT,
                    email TEXT,
                    tier TEXT CHECK(tier IN ('free', 'plus', 'pro')) NOT NULL DEFAULT 'free',
                    is_primary_argon INTEGER DEFAULT 0,
                    daily_video_credits_limit INTEGER DEFAULT 50,
                    daily_video_credits_used INTEGER DEFAULT 0,
                    daily_image_credits_used INTEGER DEFAULT 0,
                    monthly_credits_limit INTEGER DEFAULT 0,
                    monthly_credits_remaining INTEGER DEFAULT 0,
                    pool_id TEXT,
                    status TEXT DEFAULT 'active',
                    browser TEXT DEFAULT 'chrome',
                    profile_dir TEXT,
                    last_daily_reset DATE,
                    last_error TEXT,
                    error_action_hint TEXT,
                    last_error_time DATETIME,
                    last_used_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("PRAGMA table_info(accounts);")
            acc_cols = {col["name"] for col in cursor.fetchall()}
            acc_migrations = {
                "account_name": "TEXT",
                "email": "TEXT",
                "is_primary_argon": "INTEGER DEFAULT 0",
                "monthly_credits_limit": "INTEGER DEFAULT 0",
                "monthly_credits_remaining": "INTEGER DEFAULT 0",
                "monthly_credits_used": "INTEGER DEFAULT 0",
                "is_shared_pool": "INTEGER DEFAULT 0",
                "renewal_day": "INTEGER DEFAULT 24",
                "detected_models": "TEXT DEFAULT 'omni flash,veo fast,kling standard'",
                "can_generate_video": "INTEGER DEFAULT 1",
                "can_generate_image": "INTEGER DEFAULT 1",
                "browser": "TEXT DEFAULT 'chrome'",
                "profile_dir": "TEXT",
                "last_daily_reset": "DATE",
                "last_error": "TEXT",
                "error_action_hint": "TEXT",
                "last_error_time": "DATETIME",
            }
            for col_name, col_def in acc_migrations.items():
                if col_name not in acc_cols:
                    cursor.execute(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def};")

            # 2. Shared Credit Pools (Free Daily Pool, Plus 200 Pool, Pro 1000 Pool)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credit_pools (
                    pool_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    total_credits INTEGER NOT NULL DEFAULT 0,
                    remaining_credits INTEGER NOT NULL DEFAULT 0,
                    target_consumption_days INTEGER DEFAULT 14,
                    daily_target_credits INTEGER DEFAULT 0,
                    used_today INTEGER DEFAULT 0,
                    is_shared INTEGER DEFAULT 0,
                    renewal_day INTEGER DEFAULT 24,
                    last_reset_date DATE,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("PRAGMA table_info(credit_pools);")
            cp_cols = {col["name"] for col in cursor.fetchall()}
            for col_name, col_def in {
                "is_shared": "INTEGER DEFAULT 0",
                "renewal_day": "INTEGER DEFAULT 24",
            }.items():
                if col_name not in cp_cols:
                    cursor.execute(f"ALTER TABLE credit_pools ADD COLUMN {col_name} {col_def};")

            # Seed pool rows with 0 defaults when no accounts exist (never fake 200/1000 without accounts)
            cursor.execute("SELECT COUNT(*) as cnt FROM credit_pools;")
            if (cursor.fetchone()["cnt"] or 0) == 0:
                today_iso = date.today().isoformat()
                cursor.execute("""
                    INSERT INTO credit_pools (pool_id, tier, total_credits, remaining_credits, target_consumption_days, daily_target_credits, used_today, last_reset_date)
                    VALUES 
                        ('free_daily_pool', 'free', 0, 0, 1, 0, 0, ?),
                        ('plus_pool', 'plus', 0, 0, 7, 0, 0, ?),
                        ('pro_pool', 'pro', 0, 0, 14, 0, 0, ?);
                """, (today_iso, today_iso, today_iso))

            # 3. Assets Table (Videos & Images with 3-tier QC + Dual Platform Status)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE NOT NULL,
                    file_hash TEXT,
                    asset_type TEXT CHECK(asset_type IN ('video', 'image')) NOT NULL,
                    filename TEXT NOT NULL,
                    original_prompt TEXT NOT NULL,
                    concept_id TEXT,
                    model_used TEXT,
                    upscale_model TEXT DEFAULT 'high-fidelity-4x',
                    upscale_scale INTEGER DEFAULT 2,
                    category TEXT,
                    subject_type TEXT,
                    lighting_style TEXT,
                    visual_pattern TEXT,
                    generated_by_profile TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    width INTEGER DEFAULT 0,
                    height INTEGER DEFAULT 0,
                    audio_stripped INTEGER DEFAULT 0,
                    phash TEXT,
                    dhash TEXT,
                    status TEXT NOT NULL DEFAULT 'downloaded',
                    qc_tier TEXT DEFAULT 'approved',
                    qc_score REAL DEFAULT 85.0,
                    technical_score REAL DEFAULT 85.0,
                    motion_continuity_score REAL DEFAULT 85.0,
                    qc1_feedback TEXT,
                    qc2_feedback TEXT,
                    opencv_sharpness REAL DEFAULT 0.0,
                    opencv_noise REAL DEFAULT 0.0,
                    seo_title TEXT,
                    adobe_title TEXT,
                    freepik_title TEXT,
                    seo_keywords TEXT,
                    batch_id TEXT,
                    adobe_status TEXT DEFAULT 'pending',
                    adobe_asset_id TEXT,
                    adobe_rejection_reason TEXT,
                    adobe_downloads INTEGER DEFAULT 0,
                    adobe_earnings REAL DEFAULT 0.0,
                    freepik_status TEXT DEFAULT 'ready_when_active',
                    freepik_rejected INTEGER DEFAULT 0,
                    freepik_rejection_notes TEXT,
                    is_freepik_150_golden INTEGER DEFAULT 0,
                    freepik_downloads INTEGER DEFAULT 0,
                    freepik_earnings REAL DEFAULT 0.0,
                    total_downloads INTEGER DEFAULT 0,
                    last_download_date DATETIME,
                    video_model_tested TEXT,
                    storyboard_path TEXT,
                    current_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("PRAGMA table_info(assets);")
            asset_cols = {col["name"] for col in cursor.fetchall()}
            asset_migrations = {
                "file_hash": "TEXT",
                "upscale_model": "TEXT DEFAULT 'high-fidelity-4x'",
                "upscale_scale": "INTEGER DEFAULT 2",
                "width": "INTEGER DEFAULT 0",
                "height": "INTEGER DEFAULT 0",
                "audio_stripped": "INTEGER DEFAULT 0",
                "qc_tier": "TEXT DEFAULT 'approved'",
                "qc_score": "REAL DEFAULT 85.0",
                "technical_score": "REAL DEFAULT 85.0",
                "motion_continuity_score": "REAL DEFAULT 85.0",
                "adobe_title": "TEXT",
                "freepik_title": "TEXT",
                "adobe_status": "TEXT DEFAULT 'pending'",
                "adobe_downloads": "INTEGER DEFAULT 0",
                "adobe_earnings": "REAL DEFAULT 0.0",
                "freepik_status": "TEXT DEFAULT 'ready_when_active'",
                "freepik_rejected": "INTEGER DEFAULT 0",
                "freepik_rejection_notes": "TEXT",
                "is_freepik_150_golden": "INTEGER DEFAULT 0",
                "freepik_downloads": "INTEGER DEFAULT 0",
                "freepik_earnings": "REAL DEFAULT 0.0",
                "total_downloads": "INTEGER DEFAULT 0",
                "last_download_date": "DATETIME",
                "video_model_tested": "TEXT",
                "storyboard_path": "TEXT",
            }
            for col_name, col_def in asset_migrations.items():
                if col_name not in asset_cols:
                    cursor.execute(f"ALTER TABLE assets ADD COLUMN {col_name} {col_def};")

            # 4. Stateful Freepik 150 Onboarding Ledger (Never re-checks already inspected photos)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS freepik_150_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_hash TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    original_path TEXT,
                    golden_path TEXT,
                    decision TEXT CHECK(decision IN ('approved_150', 'rejected_150')) NOT NULL,
                    sharpness_score REAL DEFAULT 0.0,
                    megapixels REAL DEFAULT 0.0,
                    phash TEXT,
                    reason TEXT,
                    inspected_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 5. Video & Image Model Performance Table (Excludes 100-credit Quality modes)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT UNIQUE NOT NULL,
                    asset_type TEXT NOT NULL DEFAULT 'video',
                    points_cost INTEGER DEFAULT 15,
                    total_generated INTEGER DEFAULT 0,
                    qc_passed INTEGER DEFAULT 0,
                    qc_borderline INTEGER DEFAULT 0,
                    qc_failed INTEGER DEFAULT 0,
                    adobe_accepted INTEGER DEFAULT 0,
                    adobe_rejected INTEGER DEFAULT 0,
                    avg_sharpness REAL DEFAULT 0.0,
                    is_winner INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("PRAGMA table_info(model_performance);")
            mp_cols = {col["name"] for col in cursor.fetchall()}
            for col_name, col_def in {
                "qc_borderline": "INTEGER DEFAULT 0",
                "avg_sharpness": "REAL DEFAULT 0.0",
                "is_winner": "INTEGER DEFAULT 0",
            }.items():
                if col_name not in mp_cols:
                    cursor.execute(f"ALTER TABLE model_performance ADD COLUMN {col_name} {col_def};")

            # Seed default eligible video models (and mark 100-credit quality as banned)
            default_video_models = [
                ("omni flash", "video", 15, "preferred", 1),
                ("veo fast", "video", 20, "active", 0),
                ("kling standard", "video", 15, "active", 0),
                ("hailuo minimax", "video", 15, "active", 0),
                ("wan 2.1", "video", 10, "active", 0),
                ("quality (100 credits)", "video", 100, "banned_100_credit", 0),
            ]
            for m_name, a_type, cost, st, win in default_video_models:
                cursor.execute("""
                    INSERT INTO model_performance (model_name, asset_type, points_cost, status, is_winner)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(model_name) DO NOTHING;
                """, (m_name, a_type, cost, st, win))

            # 6. Agent Memory Snapshots (Handoff Report between Argon accounts)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_memory_snapshots (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    active_argon_account TEXT,
                    handoff_summary TEXT,
                    winning_niches_json TEXT DEFAULT '[]',
                    blacklisted_json TEXT DEFAULT '[]',
                    winning_video_model TEXT DEFAULT 'omni flash',
                    last_shift_state_json TEXT DEFAULT '{}',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                INSERT INTO agent_memory_snapshots (id, active_argon_account, handoff_summary)
                VALUES (1, 'Primary Argon Account', 'Initial system state ready.')
                ON CONFLICT(id) DO NOTHING;
            """)

            # 7. Self-Driving Daily Employee Shifts Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_shifts (
                    shift_date DATE PRIMARY KEY,
                    auto_pilot_enabled INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'idle',
                    current_stage TEXT DEFAULT 'READY',
                    current_detail TEXT DEFAULT 'Ready to start daily shift',
                    target_videos INTEGER DEFAULT 10,
                    completed_videos INTEGER DEFAULT 0,
                    target_images INTEGER DEFAULT 30,
                    completed_images INTEGER DEFAULT 0,
                    free_credits_spent INTEGER DEFAULT 0,
                    plus_credits_spent INTEGER DEFAULT 0,
                    pro_credits_spent INTEGER DEFAULT 0,
                    winning_video_model TEXT DEFAULT 'omni flash',
                    planned_prompts_json TEXT DEFAULT '[]',
                    telegram_notified INTEGER DEFAULT 0,
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 8. Persistent Adaptive Quality & Buffer Rules Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS adaptive_rules (
                    rule_key TEXT PRIMARY KEY,
                    rule_value TEXT NOT NULL,
                    reason TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 9. Batches, Strategy Learnings, Gemini Keys & Platform Alerts
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

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_tier ON assets(qc_tier);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_hash ON assets(file_hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_freepik150_hash ON freepik_150_ledger(file_hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);")

        self.reset_daily_free_credits_if_new_day()
        logger.info(f"Database initialized at {self.db_path}")

    # =========================================================================
    # DAILY CREDIT RESET & MULTI-ACCOUNT POOLS
    # =========================================================================
    def reset_daily_free_credits_if_new_day(self) -> None:
        """Resets the 50 daily free credits on all accounts when a new calendar day starts."""
        today_str = date.today().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE accounts
                SET daily_video_credits_used = 0,
                    daily_image_credits_used = 0,
                    last_daily_reset = ?
                WHERE last_daily_reset IS NULL OR last_daily_reset != ?;
            """, (today_str, today_str))

            cursor.execute("""
                UPDATE credit_pools
                SET used_today = 0,
                    last_reset_date = ?
                WHERE last_reset_date IS NULL OR last_reset_date != ?;
            """, (today_str, today_str))

    @staticmethod
    def _days_until_renewal(renewal_day: int) -> int:
        """Calculates exact days remaining until the monthly subscription renewal day (1..31)."""
        import calendar
        today = date.today()
        r_day = max(1, min(31, int(renewal_day or 24)))
        max_day_this_month = calendar.monthrange(today.year, today.month)[1]
        target_this_month = min(r_day, max_day_this_month)
        if today.day < target_this_month:
            return max(1, (date(today.year, today.month, target_this_month) - today).days)
        next_month = 1 if today.month == 12 else today.month + 1
        next_year = today.year + 1 if today.month == 12 else today.year
        max_day_next = calendar.monthrange(next_year, next_month)[1]
        target_next = min(r_day, max_day_next)
        return max(1, (date(next_year, next_month, target_next) - today).days)

    def get_credit_pools_summary(self) -> dict[str, Any]:
        """
        Calculates 100% dynamic live credit balances strictly from registered accounts:
        - If 0 accounts are registered in a tier, total=0, remaining=0, used=0 (NEVER fake 200 or 1000).
        - Builds an explicit ordered `accounts_queue` for every pool showing:
          - who is Exhausted (`exhausted` / خلص)
          - who is Next in Turn (`next_up` / عليه الدور)
          - who is Waiting (`available` / متاح في الطابور)
          - whether accounts share a single pool (`is_shared_pool = 1`) or have individual quotas (`is_shared_pool = 0`).
        """
        self.reset_daily_free_credits_if_new_day()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, profile_name, account_name, email, tier, is_primary_argon,
                       daily_video_credits_limit, daily_video_credits_used, daily_image_credits_used,
                       monthly_credits_limit, monthly_credits_remaining, monthly_credits_used,
                       is_shared_pool, renewal_day, detected_models,
                       can_generate_video, can_generate_image, status, last_used_at
                FROM accounts
                ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                         CASE tier WHEN 'free' THEN 1 WHEN 'plus' THEN 2 WHEN 'pro' THEN 3 END,
                         is_primary_argon DESC,
                         id ASC;
            """)
            all_accounts = [dict(r) for r in cursor.fetchall()]
            active_accounts = [a for a in all_accounts if a.get("status") == "active"]

            cursor.execute("SELECT * FROM credit_pools;")
            pools_map = {r["pool_id"]: dict(r) for r in cursor.fetchall()}

            # -----------------------------------------------------------------
            # 1. FREE 50/DAY POOL (All registered accounts contribute 50/day)
            # -----------------------------------------------------------------
            free_limit_default = int(Config.get("credit_strategy.free_daily_credits_per_account", 50))
            total_free_daily = 0
            used_free_daily = 0
            accounts_finished_free = 0
            accounts_with_free_left = 0
            free_queue: list[dict[str, Any]] = []
            free_next_assigned = False

            for idx, acc in enumerate(all_accounts):
                is_active = acc.get("status") == "active"
                lim = int(acc.get("daily_video_credits_limit") or free_limit_default)
                used = min(lim, int(acc.get("daily_video_credits_used") or 0))
                rem = max(0, lim - used) if is_active else 0
                if is_active:
                    total_free_daily += lim
                    used_free_daily += used
                    if rem <= 0:
                        accounts_finished_free += 1
                        q_status = "exhausted"
                    elif not free_next_assigned:
                        accounts_with_free_left += 1
                        q_status = "next_up"
                        free_next_assigned = True
                    else:
                        accounts_with_free_left += 1
                        q_status = "available"
                else:
                    q_status = "disabled"

                free_queue.append({
                    "id": acc["id"],
                    "profile_name": acc["profile_name"],
                    "account_name": acc.get("account_name") or acc["profile_name"],
                    "email": acc.get("email") or acc["profile_name"],
                    "tier": acc.get("tier", "free"),
                    "is_primary_argon": bool(acc.get("is_primary_argon")),
                    "limit": lim,
                    "used": used,
                    "remaining": rem,
                    "usage_pct": round((used / lim * 100), 1) if lim > 0 else 0.0,
                    "queue_status": q_status,
                    "queue_position": idx + 1,
                    "detected_models": [m.strip() for m in (acc.get("detected_models") or "omni flash").split(",") if m.strip()],
                })

            # -----------------------------------------------------------------
            # 2. PLUS 200 MONTHLY POOL (Dynamic from actual Plus accounts!)
            # -----------------------------------------------------------------
            plus_accounts = [a for a in all_accounts if a.get("tier") == "plus"]
            active_plus = [a for a in plus_accounts if a.get("status") == "active"]
            plus_pool_row = pools_map.get("plus_pool", {})
            plus_queue: list[dict[str, Any]] = []
            plus_next_assigned = False

            if not active_plus:
                plus_total = 0
                plus_remaining = 0
                plus_used = 0
                plus_is_shared = False
                plus_renewal_day = 24
                plus_days_left = 0
            else:
                plus_is_shared = any(bool(a.get("is_shared_pool")) for a in active_plus)
                plus_renewal_day = int(active_plus[0].get("renewal_day") or plus_pool_row.get("renewal_day") or 24)
                plus_days_left = self._days_until_renewal(plus_renewal_day)

                if plus_is_shared:
                    # Shared pool across entered Plus emails
                    shared_lim = int(plus_pool_row.get("total_credits") or 0)
                    if shared_lim <= 0:
                        shared_lim = int(active_plus[0].get("monthly_credits_limit") or 200)
                    shared_used = sum(int(a.get("monthly_credits_used") or 0) for a in active_plus)
                    if shared_used == 0 and plus_pool_row.get("total_credits", 0) > 0:
                        shared_used = max(0, int(plus_pool_row.get("total_credits", 200)) - int(plus_pool_row.get("remaining_credits", 200)))
                    plus_total = shared_lim
                    plus_used = min(shared_lim, shared_used)
                    plus_remaining = max(0, plus_total - plus_used)
                else:
                    # Individual 200 pool per Plus account
                    plus_total = sum(int(a.get("monthly_credits_limit") or 200) for a in active_plus)
                    plus_used = sum(
                        max(0, int(a.get("monthly_credits_limit") or 200) - int(a.get("monthly_credits_remaining") if a.get("monthly_credits_remaining") is not None else 200))
                        for a in active_plus
                    )
                    plus_remaining = max(0, plus_total - plus_used)

                for idx, acc in enumerate(plus_accounts):
                    is_active = acc.get("status") == "active"
                    acc_lim = int(acc.get("monthly_credits_limit") or 200)
                    if plus_is_shared:
                        acc_used = int(acc.get("monthly_credits_used") or 0)
                        acc_rem = plus_remaining if is_active else 0
                    else:
                        acc_rem = int(acc.get("monthly_credits_remaining") if acc.get("monthly_credits_remaining") is not None else acc_lim)
                        acc_used = max(0, acc_lim - acc_rem)
                    if not is_active:
                        q_st = "disabled"
                    elif acc_rem <= 0:
                        q_st = "exhausted"
                    elif not plus_next_assigned:
                        q_st = "next_up"
                        plus_next_assigned = True
                    else:
                        q_st = "available"

                    r_day = int(acc.get("renewal_day") or 24)
                    plus_queue.append({
                        "id": acc["id"],
                        "profile_name": acc["profile_name"],
                        "account_name": acc.get("account_name") or acc["profile_name"],
                        "email": acc.get("email") or acc["profile_name"],
                        "tier": "plus",
                        "is_shared_pool": bool(acc.get("is_shared_pool")),
                        "renewal_day": r_day,
                        "days_to_renewal": self._days_until_renewal(r_day),
                        "limit": plus_total if plus_is_shared else acc_lim,
                        "used": acc_used,
                        "remaining": acc_rem,
                        "usage_pct": round(((plus_used if plus_is_shared else acc_used) / max(1, (plus_total if plus_is_shared else acc_lim)) * 100), 1),
                        "queue_status": q_st,
                        "queue_position": idx + 1,
                        "detected_models": [m.strip() for m in (acc.get("detected_models") or "omni flash,veo fast").split(",") if m.strip()],
                    })

            plus_dict = {
                "is_configured": len(active_plus) > 0,
                "total_accounts": len(plus_accounts),
                "active_accounts": len(active_plus),
                "accounts_exhausted": sum(1 for q in plus_queue if q["queue_status"] == "exhausted"),
                "accounts_available": sum(1 for q in plus_queue if q["queue_status"] in ("next_up", "available")),
                "is_shared_pool": plus_is_shared,
                "total": plus_total,
                "remaining": plus_remaining,
                "used": plus_used,
                "used_today": plus_pool_row.get("used_today", 0) if active_plus else 0,
                "renewal_day": plus_renewal_day,
                "days_to_renewal": plus_days_left,
                "daily_recommended_burn": round(plus_remaining / max(1, min(7, plus_days_left))) if plus_remaining > 0 else 0,
                "accounts_queue": plus_queue,
            }

            # -----------------------------------------------------------------
            # 3. PRO 1000 MONTHLY POOL (Dynamic from actual Pro accounts!)
            # -----------------------------------------------------------------
            pro_accounts = [a for a in all_accounts if a.get("tier") == "pro"]
            active_pro = [a for a in pro_accounts if a.get("status") == "active"]
            pro_pool_row = pools_map.get("pro_pool", {})
            pro_queue: list[dict[str, Any]] = []
            pro_next_assigned = False

            if not active_pro:
                pro_total = 0
                pro_remaining = 0
                pro_used = 0
                pro_is_shared = False
                pro_renewal_day = 24
                pro_days_left = 0
                pro_target_days = 14
            else:
                pro_is_shared = any(bool(a.get("is_shared_pool")) for a in active_pro)
                pro_renewal_day = int(active_pro[0].get("renewal_day") or pro_pool_row.get("renewal_day") or 24)
                pro_days_left = self._days_until_renewal(pro_renewal_day)
                pro_target_days = max(1, min(int(pro_pool_row.get("target_consumption_days") or 14), pro_days_left))

                if pro_is_shared:
                    shared_lim = int(pro_pool_row.get("total_credits") or 0)
                    if shared_lim <= 0:
                        shared_lim = int(active_pro[0].get("monthly_credits_limit") or 1000)
                    shared_used = sum(int(a.get("monthly_credits_used") or 0) for a in active_pro)
                    if shared_used == 0 and pro_pool_row.get("total_credits", 0) > 0:
                        shared_used = max(0, int(pro_pool_row.get("total_credits", 1000)) - int(pro_pool_row.get("remaining_credits", 1000)))
                    pro_total = shared_lim
                    pro_used = min(shared_lim, shared_used)
                    pro_remaining = max(0, pro_total - pro_used)
                else:
                    pro_total = sum(int(a.get("monthly_credits_limit") or 1000) for a in active_pro)
                    pro_used = sum(
                        max(0, int(a.get("monthly_credits_limit") or 1000) - int(a.get("monthly_credits_remaining") if a.get("monthly_credits_remaining") is not None else 1000))
                        for a in active_pro
                    )
                    pro_remaining = max(0, pro_total - pro_used)

                for idx, acc in enumerate(pro_accounts):
                    is_active = acc.get("status") == "active"
                    acc_lim = int(acc.get("monthly_credits_limit") or 1000)
                    if pro_is_shared:
                        acc_used = int(acc.get("monthly_credits_used") or 0)
                        acc_rem = pro_remaining if is_active else 0
                    else:
                        acc_rem = int(acc.get("monthly_credits_remaining") if acc.get("monthly_credits_remaining") is not None else acc_lim)
                        acc_used = max(0, acc_lim - acc_rem)
                    if not is_active:
                        q_st = "disabled"
                    elif acc_rem <= 0:
                        q_st = "exhausted"
                    elif not pro_next_assigned:
                        q_st = "next_up"
                        pro_next_assigned = True
                    else:
                        q_st = "available"

                    r_day = int(acc.get("renewal_day") or 24)
                    pro_queue.append({
                        "id": acc["id"],
                        "profile_name": acc["profile_name"],
                        "account_name": acc.get("account_name") or acc["profile_name"],
                        "email": acc.get("email") or acc["profile_name"],
                        "tier": "pro",
                        "is_shared_pool": bool(acc.get("is_shared_pool")),
                        "renewal_day": r_day,
                        "days_to_renewal": self._days_until_renewal(r_day),
                        "limit": pro_total if pro_is_shared else acc_lim,
                        "used": acc_used,
                        "remaining": acc_rem,
                        "usage_pct": round(((pro_used if pro_is_shared else acc_used) / max(1, (pro_total if pro_is_shared else acc_lim)) * 100), 1),
                        "queue_status": q_st,
                        "queue_position": idx + 1,
                        "detected_models": [m.strip() for m in (acc.get("detected_models") or "omni flash,veo fast,kling standard").split(",") if m.strip()],
                    })

            pro_dict = {
                "is_configured": len(active_pro) > 0,
                "total_accounts": len(pro_accounts),
                "active_accounts": len(active_pro),
                "accounts_exhausted": sum(1 for q in pro_queue if q["queue_status"] == "exhausted"),
                "accounts_available": sum(1 for q in pro_queue if q["queue_status"] in ("next_up", "available")),
                "is_shared_pool": pro_is_shared,
                "total": pro_total,
                "remaining": pro_remaining,
                "used": pro_used,
                "used_today": pro_pool_row.get("used_today", 0) if active_pro else 0,
                "target_days": pro_target_days,
                "renewal_day": pro_renewal_day,
                "days_to_renewal": pro_days_left,
                "daily_recommended_burn": round(pro_remaining / max(1, pro_target_days)) if pro_remaining > 0 else 0,
                "accounts_queue": pro_queue,
            }

            return {
                "has_any_accounts": len(active_accounts) > 0,
                "total_registered_accounts": len(all_accounts),
                "free_daily": {
                    "is_configured": len(active_accounts) > 0,
                    "total_accounts": len(active_accounts),
                    "accounts_finished_today": accounts_finished_free,
                    "accounts_exhausted_today": accounts_finished_free,
                    "accounts_remaining_today": accounts_with_free_left,
                    "total_daily_credits": total_free_daily,
                    "total_daily_capacity": total_free_daily,
                    "used_today": used_free_daily,
                    "remaining_today": max(0, total_free_daily - used_free_daily),
                    "accounts_queue": free_queue,
                },
                "plus_200": plus_dict,
                "plus_monthly": plus_dict,
                "pro_1000": pro_dict,
                "pro_monthly": pro_dict,
                "accounts": all_accounts,
            }

    def reset_daily_account_usage(self) -> None:
        """Explicitly resets today's 50 free daily credits across all accounts."""
        today_str = date.today().isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE accounts
                SET daily_video_credits_used = 0,
                    daily_image_credits_used = 0,
                    last_daily_reset = ?;
            """, (today_str,))
            conn.execute("UPDATE credit_pools SET used_today = 0, last_reset_date = ?;", (today_str,))

    def select_next_account_for_credits(
        self,
        credits_needed: int = 15,
        points_needed: int | None = None,
    ) -> dict[str, Any] | None:
        """
        Enforces strict dynamic credit spending priority across user-registered accounts:
        1. Priority #1: Any active account that still has daily Free 50 credits left today.
        2. Priority #2: Any active Plus (200 monthly credits) account that still has monthly credits left.
        3. Priority #3: Any active Pro (1000 monthly credits) account that still has monthly credits left.
        Never returns a fake account if the user hasn't registered one.
        """
        needed = int(points_needed if points_needed is not None else credits_needed)
        summary = self.get_credit_pools_summary()

        # 1. Check daily Free 50 queue first
        for item in summary["free_daily"]["accounts_queue"]:
            if item["queue_status"] in ("next_up", "available") and item["remaining"] >= needed:
                item["credit_source"] = "free_50_daily"
                item["reason_ar"] = f"الأولوية #1: سحب من الـ 50 نقطة المجانية اليومية ({item['email']})"
                item["reason_en"] = f"Priority #1: Drawing from Daily Free 50 Pool ({item['email']})"
                return item

        # 2. Check Plus 200 queue second (only if user actually has Plus accounts)
        if summary["plus_200"]["is_configured"] and summary["plus_200"]["remaining"] >= needed:
            for item in summary["plus_200"]["accounts_queue"]:
                if item["queue_status"] in ("next_up", "available") and item["remaining"] >= needed:
                    item["credit_source"] = "plus_200_pool"
                    item["reason_ar"] = f"الأولوية #2: سحب من باقة Plus 200 الشهرية ({item['email']})"
                    item["reason_en"] = f"Priority #2: Drawing from Monthly Plus 200 Pool ({item['email']})"
                    return item

        # 3. Check Pro 1000 queue third (only if user actually has Pro accounts)
        if summary["pro_1000"]["is_configured"] and summary["pro_1000"]["remaining"] >= needed:
            for item in summary["pro_1000"]["accounts_queue"]:
                if item["queue_status"] in ("next_up", "available") and item["remaining"] >= needed:
                    item["credit_source"] = "pro_1000_pool"
                    item["reason_ar"] = f"الأولوية #3: سحب من باقة Pro 1000 الشهرية ({item['email']})"
                    item["reason_en"] = f"Priority #3: Drawing from Monthly Pro 1000 Pool ({item['email']})"
                    return item

        return None

    def record_account_credit_spend(self, profile_name: str, points_spent: int = 10, source_pool: str = "free_50_daily") -> None:
        """Records credit spend against either the account's 50 daily free quota or monthly Plus/Pro quota."""
        pts = int(points_spent)
        with self.get_connection() as conn:
            if source_pool == "free_50_daily":
                conn.execute(
                    """
                    UPDATE accounts
                    SET daily_video_credits_used = MIN(daily_video_credits_limit, daily_video_credits_used + ?),
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE profile_name = ? OR email = ?;
                    """,
                    (pts, profile_name, profile_name),
                )
            elif "plus" in source_pool:
                conn.execute(
                    """
                    UPDATE accounts
                    SET monthly_credits_used = monthly_credits_used + ?,
                        monthly_credits_remaining = MAX(0, monthly_credits_remaining - ?),
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE profile_name = ? OR email = ?;
                    """,
                    (pts, pts, profile_name, profile_name),
                )
                conn.execute(
                    "UPDATE credit_pools SET remaining_credits = MAX(0, remaining_credits - ?), used_today = used_today + ? WHERE pool_id = 'plus_pool';",
                    (pts, pts),
                )
            else:
                conn.execute(
                    """
                    UPDATE accounts
                    SET monthly_credits_used = monthly_credits_used + ?,
                        monthly_credits_remaining = MAX(0, monthly_credits_remaining - ?),
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE profile_name = ? OR email = ?;
                    """,
                    (pts, pts, profile_name, profile_name),
                )
                conn.execute(
                    "UPDATE credit_pools SET remaining_credits = MAX(0, remaining_credits - ?), used_today = used_today + ? WHERE pool_id = 'pro_pool';",
                    (pts, pts),
                )

    def get_or_create_daily_shift(self) -> dict[str, Any]:
        """Retrieves or creates today's autonomous employee shift record."""
        today_str = date.today().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_shifts WHERE shift_date = ?;", (today_str,))
            row = cursor.fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO daily_shifts (shift_date, status, current_stage, current_detail)
                    VALUES (?, 'idle', 'READY', 'الموظف الذكي جاهز لبدء وردية اليوم');
                    """,
                    (today_str,),
                )
                cursor.execute("SELECT * FROM daily_shifts WHERE shift_date = ?;", (today_str,))
                row = cursor.fetchone()
            d = dict(row) if row else {"shift_date": today_str, "status": "idle"}
            d["videos_completed"] = d.get("completed_videos", 0)
            d["images_completed"] = d.get("completed_images", 0)
            return d

    def update_daily_shift(self, **kwargs: Any) -> None:
        """Updates today's daily shift record."""
        today_str = date.today().isoformat()
        self.get_or_create_daily_shift()
        col_map = {
            "status": "status",
            "current_step": "current_stage",
            "notes": "current_detail",
            "videos_planned": "target_videos",
            "videos_completed": "completed_videos",
            "images_planned": "target_images",
            "images_completed": "completed_images",
            "free_credits_spent": "free_credits_spent",
            "plus_credits_spent": "plus_credits_spent",
            "pro_credits_spent": "pro_credits_spent",
            "active_video_model": "winning_video_model",
        }
        updates = {}
        for k, v in kwargs.items():
            target_col = col_map.get(k, k)
            updates[target_col] = v
        if not updates:
            return
        set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
        vals = list(updates.values()) + [today_str]
        with self.get_connection() as conn:
            conn.execute(f"UPDATE daily_shifts SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE shift_date = ?;", vals)

    def get_primary_argon_account(self) -> dict[str, Any] | None:
        """Returns the designated #1 Primary Argon account, or falls back to the next active account."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM accounts
                WHERE status = 'active'
                ORDER BY is_primary_argon DESC,
                         CASE tier WHEN 'pro' THEN 1 WHEN 'plus' THEN 2 ELSE 3 END,
                         id ASC
                LIMIT 1;
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_primary_argon_account(self, profile_name: str) -> None:
        """Marks a specific account as the #1 Primary Master Argon Brain."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE accounts SET is_primary_argon = 0;")
            cursor.execute(
                "UPDATE accounts SET is_primary_argon = 1 WHERE profile_name = ? OR email = ?;",
                (profile_name, profile_name),
            )

    def save_memory_handoff_snapshot(
        self,
        active_account: str,
        handoff_summary: str,
        winning_niches: list[str] | None = None,
        blacklisted: list[str] | None = None,
        winning_video_model: str | None = None,
        shift_state: dict[str, Any] | None = None,
    ) -> None:
        """Saves the local Handoff Report so if Argon switches accounts, 0% of history is lost."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM agent_memory_snapshots WHERE id = 1;")
            existing = dict(cursor.fetchone() or {})

            niches_json = json.dumps(winning_niches) if winning_niches is not None else existing.get("winning_niches_json", "[]")
            black_json = json.dumps(blacklisted) if blacklisted is not None else existing.get("blacklisted_json", "[]")
            v_model = winning_video_model or existing.get("winning_video_model", "omni flash")
            state_json = json.dumps(shift_state) if shift_state is not None else existing.get("last_shift_state_json", "{}")

            cursor.execute("""
                UPDATE agent_memory_snapshots
                SET active_argon_account = ?,
                    handoff_summary = ?,
                    winning_niches_json = ?,
                    blacklisted_json = ?,
                    winning_video_model = ?,
                    last_shift_state_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1;
            """, (active_account, handoff_summary, niches_json, black_json, v_model, state_json))

    def get_memory_handoff_snapshot(self) -> dict[str, Any]:
        """Returns the latest local Handoff Report for Argon continuity."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM agent_memory_snapshots WHERE id = 1;")
            row = cursor.fetchone()
            if not row:
                return {}
            d = dict(row)
            try:
                d["winning_niches"] = json.loads(d.get("winning_niches_json") or "[]")
            except Exception:
                d["winning_niches"] = []
            try:
                d["blacklisted"] = json.loads(d.get("blacklisted_json") or "[]")
            except Exception:
                d["blacklisted"] = []
            return d

    # =========================================================================
    # ADAPTIVE RULES PERSISTENCE (Fixes previously unsaved threshold calculations)
    # =========================================================================
    def set_adaptive_rule(self, rule_key: str, rule_value: Any, reason: str = "") -> None:
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO adaptive_rules (rule_key, rule_value, reason, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(rule_key) DO UPDATE SET
                    rule_value = excluded.rule_value,
                    reason = excluded.reason,
                    updated_at = CURRENT_TIMESTAMP;
            """, (rule_key, str(rule_value), reason))

    def get_adaptive_rule(self, rule_key: str, default: Any = None) -> Any:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rule_value FROM adaptive_rules WHERE rule_key = ?;", (rule_key,))
            row = cursor.fetchone()
            return row["rule_value"] if row else default

    def get_all_adaptive_rules(self) -> list[dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rule_key, rule_value, reason, updated_at FROM adaptive_rules ORDER BY updated_at DESC;")
            return [dict(r) for r in cursor.fetchall()]

    # =========================================================================
    # ACCOUNT & QUOTA OPERATIONS
    # =========================================================================
    def sync_accounts_config(self, config_data: dict[str, Any]) -> None:
        """Syncs accounts and credit pools from accounts_config.json into DB."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            pools = config_data.get("credit_strategy", {})
            for pool_key in ["plus_pool", "pro_pool"]:
                if pool_key in pools:
                    p = pools[pool_key]
                    tier = "plus" if "plus" in pool_key else "pro"
                    default_total = 200 if tier == "plus" else 1000
                    default_days = 7 if tier == "plus" else 14
                    cursor.execute("""
                        INSERT INTO credit_pools (
                            pool_id, tier, total_credits, remaining_credits,
                            target_consumption_days, daily_target_credits, last_reset_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(pool_id) DO UPDATE SET
                            total_credits = excluded.total_credits,
                            target_consumption_days = excluded.target_consumption_days;
                    """, (
                        pool_key,
                        tier,
                        p.get("total_credits", default_total),
                        p.get("total_credits", default_total),
                        p.get("target_consumption_days", default_days),
                        p.get("daily_target_credits", 30 if tier == "plus" else 70),
                        date.today().isoformat(),
                    ))

            for idx, acc in enumerate(config_data.get("accounts", [])):
                tier = acc.get("tier", "free").lower()
                daily_limit = acc.get("daily_video_credits", 50)
                monthly_limit = 1000 if tier == "pro" else (200 if tier == "plus" else 0)
                is_prim = 1 if acc.get("is_primary_argon") or idx == 0 else 0
                cursor.execute("""
                    INSERT INTO accounts (
                        profile_name, account_name, email, tier, is_primary_argon,
                        daily_video_credits_limit, monthly_credits_limit, monthly_credits_remaining,
                        pool_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_name) DO UPDATE SET
                        tier = excluded.tier,
                        daily_video_credits_limit = excluded.daily_video_credits_limit,
                        pool_id = excluded.pool_id;
                """, (
                    acc["profile_name"],
                    acc.get("account_name", acc["profile_name"]),
                    acc.get("email", ""),
                    tier,
                    is_prim,
                    daily_limit,
                    monthly_limit,
                    monthly_limit,
                    acc.get("pool_id") or ("pro_pool" if tier == "pro" else ("plus_pool" if tier == "plus" else "free_daily_pool")),
                    "active" if acc.get("enabled", True) else "disabled",
                ))

    def record_generation(self, profile_name: str, asset_type: str, credits_spent: int = 15, credit_source: str = "free_50_daily") -> None:
        """Records credit usage on an account and its corresponding pool."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tier, pool_id, daily_video_credits_used, daily_video_credits_limit FROM accounts WHERE profile_name = ?", (profile_name,))
            row = cursor.fetchone()
            if not row:
                return

            tier = row["tier"]
            pool_id = row["pool_id"] or ("pro_pool" if tier == "pro" else ("plus_pool" if tier == "plus" else "free_daily_pool"))

            if asset_type == "video":
                if credit_source == "free_50_daily" or (row["daily_video_credits_used"] + credits_spent <= row["daily_video_credits_limit"]):
                    cursor.execute("""
                        UPDATE accounts 
                        SET daily_video_credits_used = daily_video_credits_used + ?,
                            last_used_at = CURRENT_TIMESTAMP
                        WHERE profile_name = ?
                    """, (credits_spent, profile_name))
                else:
                    cursor.execute("""
                        UPDATE accounts
                        SET monthly_credits_remaining = MAX(0, monthly_credits_remaining - ?),
                            last_used_at = CURRENT_TIMESTAMP
                        WHERE profile_name = ?
                    """, (credits_spent, profile_name))
                    cursor.execute("""
                        UPDATE credit_pools
                        SET remaining_credits = MAX(0, remaining_credits - ?),
                            used_today = used_today + ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE pool_id = ?
                    """, (credits_spent, credits_spent, pool_id))
            else:
                cursor.execute("""
                    UPDATE accounts 
                    SET daily_image_credits_used = daily_image_credits_used + ?,
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE profile_name = ?
                """, (credits_spent, profile_name))

    def insert_asset(self, asset_data: dict[str, Any]) -> str:
        """Inserts a generated asset record into the database."""
        asset_uuid = asset_data.get("uuid") or str(uuid.uuid4())
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO assets (
                    uuid, file_hash, asset_type, filename, original_prompt, concept_id,
                    model_used, category, subject_type, lighting_style,
                    visual_pattern, generated_by_profile, duration_seconds,
                    status, qc_tier, qc_score, current_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asset_uuid,
                asset_data.get("file_hash", ""),
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
                asset_data.get("qc_tier", "approved"),
                asset_data.get("qc_score", 85.0),
                str(asset_data.get("current_path", "")),
            ))
        return asset_uuid

    def update_asset(self, asset_identifier: str, **kwargs: Any) -> None:
        """Dynamically updates fields for an asset by UUID or filename stem. Inserts if not found."""
        if not kwargs:
            return
        fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values())
        values.extend([asset_identifier, asset_identifier, f"{asset_identifier}.%"])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE assets SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE uuid = ? OR filename = ? OR filename LIKE ?",
                values,
            )
            if cursor.rowcount == 0:
                new_uuid = str(uuid.uuid4())
                filename = kwargs.get("filename") or f"{asset_identifier}.jpg"
                asset_type = kwargs.get("asset_type") or ("video" if filename.lower().endswith((".mp4", ".mov")) else "image")
                status = kwargs.get("status", "in_pipeline")
                default_model = "omni flash" if asset_type == "video" else "nano banana pro"
                model_used = kwargs.get("model_used", default_model)
                prompt_fallback = kwargs.get("original_prompt") or Path(filename).stem.replace("_", " ")
                conn.execute("""
                    INSERT INTO assets (uuid, filename, asset_type, status, model_used, original_prompt)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (new_uuid, filename, asset_type, status, model_used, prompt_fallback))
                re_values = list(kwargs.values())
                re_values.append(new_uuid)
                conn.execute(
                    f"UPDATE assets SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE uuid = ?",
                    re_values,
                )

    def get_concept_asset_count(self, concept_id: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM assets WHERE concept_id = ?", (concept_id,))
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def get_acceptance_rate(self) -> float:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN status = 'adobe_accepted' OR adobe_status = 'accepted' THEN 1 END) as accepted,
                    COUNT(CASE WHEN status IN ('adobe_accepted', 'adobe_rejected') OR adobe_status IN ('accepted', 'rejected') THEN 1 END) as total
                FROM assets;
            """)
            row = cursor.fetchone()
            if row and row["total"] > 0:
                return float(row["accepted"]) / float(row["total"])
            return 0.0

    def get_video_stats(self) -> dict[str, Any]:
        """Returns comprehensive video review & model benchmark metrics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_videos,
                    COUNT(CASE WHEN status IN ('qc2_pass', 'uploaded', 'adobe_accepted') THEN 1 END) as passed_videos,
                    COUNT(CASE WHEN qc_tier = 'borderline' THEN 1 END) as borderline_videos,
                    COUNT(CASE WHEN status IN ('qc1_fail', 'qc2_fail', 'adobe_rejected') THEN 1 END) as rejected_videos,
                    COUNT(CASE WHEN audio_stripped = 1 THEN 1 END) as audio_stripped_count,
                    COUNT(CASE WHEN qc1_feedback LIKE '%cut%' OR qc2_feedback LIKE '%cut%' THEN 1 END) as cut_issues,
                    COUNT(CASE WHEN qc1_feedback LIKE '%warp%' OR qc2_feedback LIKE '%warp%' THEN 1 END) as warp_issues
                FROM assets 
                WHERE asset_type = 'video';
            """)
            row = cursor.fetchone()

            cursor.execute("""
                SELECT model_name, points_cost, total_generated, qc_passed, qc_borderline, qc_failed,
                       adobe_accepted, adobe_rejected, is_winner, status
                FROM model_performance
                WHERE asset_type = 'video'
                ORDER BY is_winner DESC, qc_passed DESC;
            """)
            models = [dict(r) for r in cursor.fetchall()]

            return {
                "total_scanned": row["total_videos"] if row else 0,
                "passed": row["passed_videos"] if row else 0,
                "borderline": row["borderline_videos"] if row else 0,
                "rejected": row["rejected_videos"] if row else 0,
                "audio_stripped_count": row["audio_stripped_count"] if row else 0,
                "models": models,
                "issues": {
                    "scene_cuts": row["cut_issues"] if row else 0,
                    "warping_morphing": row["warp_issues"] if row else 0,
                    "audio_detected": 0,
                },
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
                    COUNT(CASE WHEN qc_tier = 'borderline' THEN 1 END) as borderline_count,
                    
                    -- Adobe Stock numbers
                    COUNT(CASE WHEN adobe_status = 'uploaded' THEN 1 END) as adobe_uploaded,
                    COUNT(CASE WHEN adobe_status = 'accepted' OR status = 'adobe_accepted' THEN 1 END) as adobe_accepted,
                    COUNT(CASE WHEN adobe_status = 'rejected' OR status = 'adobe_rejected' THEN 1 END) as adobe_rejected,
                    COUNT(CASE WHEN (adobe_status = 'pending' OR adobe_status IS NULL) AND status = 'qc2_pass' THEN 1 END) as adobe_pending_ready,
                    
                    -- Freepik numbers
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
        action_hint: str = "",
        is_primary_argon: int = 0,
        is_shared_pool: int = 0,
        renewal_day: int = 24,
        monthly_remaining: int | None = None,
        detected_models: str = "omni flash,veo fast,kling standard",
    ) -> None:
        """Inserts or updates an account with tier, shared pool flag, renewal day, models, and primary Argon flag."""
        tier_clean = tier.lower().strip()
        if tier_clean not in ("free", "plus", "pro"):
            tier_clean = "free"
        monthly_lim = 1000 if tier_clean == "pro" else (200 if tier_clean == "plus" else 0)
        rem_val = monthly_remaining if monthly_remaining is not None else monthly_lim
        used_val = max(0, monthly_lim - rem_val)
        resolved_pool = pool_id or ("pro_pool" if tier_clean == "pro" else ("plus_pool" if tier_clean == "plus" else "free_daily_pool"))
        r_day = max(1, min(31, int(renewal_day or 24)))

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if is_primary_argon == 1:
                cursor.execute("UPDATE accounts SET is_primary_argon = 0;")

            cursor.execute("""
                INSERT INTO accounts (
                    profile_name, account_name, email, tier, is_primary_argon,
                    daily_video_credits_limit, monthly_credits_limit, monthly_credits_remaining,
                    monthly_credits_used, is_shared_pool, renewal_day, detected_models,
                    pool_id, status, browser, profile_dir, last_error, error_action_hint,
                    last_error_time, last_daily_reset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? != '' THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
                ON CONFLICT(profile_name) DO UPDATE SET
                    account_name = COALESCE(NULLIF(excluded.account_name, ''), accounts.account_name),
                    email = COALESCE(NULLIF(excluded.email, ''), accounts.email),
                    tier = excluded.tier,
                    is_primary_argon = CASE WHEN excluded.is_primary_argon = 1 THEN 1 ELSE accounts.is_primary_argon END,
                    daily_video_credits_limit = excluded.daily_video_credits_limit,
                    monthly_credits_limit = excluded.monthly_credits_limit,
                    monthly_credits_remaining = CASE WHEN ? IS NOT NULL THEN excluded.monthly_credits_remaining ELSE accounts.monthly_credits_remaining END,
                    is_shared_pool = excluded.is_shared_pool,
                    renewal_day = excluded.renewal_day,
                    detected_models = COALESCE(NULLIF(excluded.detected_models, ''), accounts.detected_models),
                    pool_id = excluded.pool_id,
                    status = excluded.status,
                    browser = excluded.browser,
                    profile_dir = excluded.profile_dir,
                    last_error = excluded.last_error,
                    error_action_hint = excluded.error_action_hint;
            """, (
                profile_name, account_name or email or profile_name, email or profile_name, tier_clean, is_primary_argon,
                daily_limit, monthly_lim, rem_val,
                used_val, int(is_shared_pool), r_day, detected_models,
                resolved_pool, status, browser, profile_dir, last_error, action_hint,
                last_error, date.today().isoformat(),
                monthly_remaining,
            ))

    def delete_account(self, profile_name: str) -> None:
        """Removes a registered account by profile_name or email."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM accounts WHERE profile_name = ? OR email = ?;", (profile_name, profile_name))

    def get_detailed_accounts(self) -> list[dict[str, Any]]:
        self.reset_daily_free_credits_if_new_day()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    id, profile_name, account_name, email, tier, is_primary_argon,
                    daily_video_credits_limit, daily_video_credits_used, daily_image_credits_used,
                    daily_video_credits_limit AS daily_limit,
                    daily_video_credits_used AS daily_used,
                    monthly_credits_limit, monthly_credits_remaining, monthly_credits_used,
                    is_shared_pool, renewal_day, detected_models,
                    pool_id, status, browser, profile_dir, last_error, error_action_hint,
                    last_error_time, last_used_at, created_at
                FROM accounts
                ORDER BY 
                    is_primary_argon DESC,
                    CASE tier WHEN 'pro' THEN 1 WHEN 'plus' THEN 2 ELSE 3 END,
                    id ASC;
            """)
            rows = [dict(r) for r in cursor.fetchall()]
            for r in rows:
                r["days_to_renewal"] = self._days_until_renewal(int(r.get("renewal_day") or 24))
            return rows

    def get_production_preferences(self) -> dict[str, Any]:
        """Returns dynamic production mode (videos_only, images_only, both), enabled stock platforms, and workspace folder."""
        gen_mode = self.get_adaptive_rule("production.generation_mode", "videos_only")
        adobe_en = str(self.get_adaptive_rule("production.adobe_enabled", "1")) == "1"
        freepik_en = str(self.get_adaptive_rule("production.freepik_enabled", "1")) == "1"
        ext_folder = self.get_adaptive_rule("production.external_workspace_path", "")
        return {
            "generation_mode": gen_mode,
            "videos_enabled": gen_mode in ("videos_only", "both"),
            "images_enabled": gen_mode in ("images_only", "both"),
            "adobe_enabled": adobe_en,
            "freepik_enabled": freepik_en,
            "external_workspace_path": ext_folder or str(Config.get_path("paths.workspace")),
        }

    def set_production_preferences(
        self,
        generation_mode: str = "videos_only",
        adobe_enabled: bool = True,
        freepik_enabled: bool = True,
        external_workspace_path: str | None = None,
    ) -> dict[str, Any]:
        mode_clean = generation_mode.strip().lower()
        if mode_clean not in ("videos_only", "images_only", "both"):
            mode_clean = "videos_only"
        self.set_adaptive_rule("production.generation_mode", mode_clean, "User selected generation scope")
        self.set_adaptive_rule("production.adobe_enabled", "1" if adobe_enabled else "0", "Adobe Stock toggle")
        self.set_adaptive_rule("production.freepik_enabled", "1" if freepik_enabled else "0", "Freepik toggle")
        if external_workspace_path is not None and external_workspace_path.strip():
            self.set_adaptive_rule("production.external_workspace_path", external_workspace_path.strip(), "External workspace folder outside project")
        return self.get_production_preferences()

    def record_platform_alert(
        self,
        platform: str,
        account_identifier: str,
        error_type: str,
        error_message: str,
        action_hint: str,
        severity: str = "warning",
    ) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
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
            cursor.execute("""
                INSERT INTO platform_alerts (
                    platform, account_identifier, error_type, error_message, action_hint, severity, resolved
                ) VALUES (?, ?, ?, ?, ?, ?, 0);
            """, (platform, account_identifier, error_type, error_message, action_hint, severity))
            return int(cursor.lastrowid or 0)

    def resolve_platform_alert(self, alert_id: int) -> None:
        with self.get_connection() as conn:
            conn.execute("UPDATE platform_alerts SET resolved = 1 WHERE id = ?;", (alert_id,))

    def clear_platform_alerts(self, platform: str, account_identifier: str = "") -> None:
        with self.get_connection() as conn:
            if account_identifier:
                conn.execute(
                    "UPDATE platform_alerts SET resolved = 1 WHERE platform = ? AND account_identifier = ? AND resolved = 0;",
                    (platform, account_identifier),
                )
            else:
                conn.execute(
                    "UPDATE platform_alerts SET resolved = 1 WHERE platform = ? AND resolved = 0;",
                    (platform,),
                )

    def get_active_platform_alerts(self) -> list[dict[str, Any]]:
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
        action_hint: str = "",
    ) -> None:
        with self.get_connection() as conn:
            conn.execute("""
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
        earnings: float = 0.0,
    ) -> bool:
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
        with self.get_connection() as conn:
            cursor = conn.cursor()
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
                    "earnings": round(g.get("adobe_total_earnings", 0.0), 2),
                },
                "freepik": {
                    "downloads": g.get("freepik_total_downloads", 0),
                    "earnings": round(g.get("freepik_total_earnings", 0.0), 2),
                },
                "downloaded_assets_count": dl_count,
                "zero_download_assets_count": zero_count,
                "monetization_rate_pct": conv_rate,
                "total_earnings_usd": round(g.get("adobe_total_earnings", 0.0) + g.get("freepik_total_earnings", 0.0), 2),
                "top_downloaded_assets": top_downloaded,
                "zero_downloads_sample": zero_downloads_sample,
                "downloads_by_category": by_category,
            }

    def import_contributor_sales_data(self, platform: str, records: list[dict[str, Any]]) -> dict[str, Any]:
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
            "total_downloads_added": total_dl_added,
        }
