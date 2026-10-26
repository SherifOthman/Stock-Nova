"""
StockNova AI — Modern WebView2 Desktop Application Controller.
Connects the 5-page Arabic/English Desktop UI (and AI Studio preview bridge)
directly to the local Python engine, SQLite database, AgentCoordinator, and pipeline services.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.dynamic_controller import DynamicController
from stockpilot.core.cloud_backup import CloudBackupEngine
from stockpilot.core.unified_vault import UnifiedVaultManager
from stockpilot.core.agent_coordinator import get_coordinator
from stockpilot.platforms.freepik_curator import FreepikOnboardingCurator
from stockpilot.quality.model_license_validator import validate_upscale_model, get_all_models_report
from stockpilot.app import StockNovaPipeline
from stockpilot.core.status_monitor import get_monitor
from stockpilot.core.browser_account_resolver import BrowserAccountResolver
from stockpilot.metadata.category_classifier import CategoryClassifier
from stockpilot.core.security import (
    SecurityVault,
    save_secure_credential,
    get_secure_credential,
)

PROJECT_ROOT = Config.get_project_root()


class DesktopBridgeAPI:
    """Exposes safe Python methods directly to JavaScript inside WebView2 & Preview Bridge."""

    def __init__(self, window_ref: list[Any] | None = None) -> None:
        self.window_ref = window_ref or []
        self.db = Database()
        self.pipeline = StockNovaPipeline()
        self.dynamic = DynamicController()
        self.vault = UnifiedVaultManager()
        self.curator = FreepikOnboardingCurator()
        self.cloud = CloudBackupEngine()
        self.coordinator = get_coordinator()
        self.is_pipeline_busy = False
        try:
            BrowserAccountResolver.sync_accounts_with_db(self.db)
        except Exception as e:
            print("Notice on initial account sync:", e)

    def on_app_startup(self) -> str:
        """
        Triggered automatically when the user opens the application.
        If Auto-Pilot is enabled and there are raw files waiting in workspace, starts the daily shift.
        """
        shift_state = self.coordinator.get_shift_status()
        queues = shift_state.get("queues", {})
        has_raw_work = (queues.get("raw_videos", 0) + queues.get("raw_images", 0)) > 0
        if self.coordinator.auto_pilot_enabled and has_raw_work and not self.coordinator.is_running_shift:
            self.coordinator.execute_daily_shift_async()
            return json.dumps({"status": "auto_started", "message": "تم بدء وردية العمل اليومية تلقائياً."})
        return json.dumps({"status": "ready", "message": "الموظف الذكي في وضع الاستعداد."})

    def get_full_state(self) -> str:
        """Serializes the entire live system metrics into JSON for the 5-page UI."""
        metrics = self.dynamic.get_metrics()
        pro_burn = self.dynamic.calculate_dynamic_daily_burn("pro_pool")
        plus_burn = self.dynamic.calculate_dynamic_daily_burn("plus_pool")
        rolling_buffer = self.dynamic.calculate_rolling_image_buffer()
        video_model_plan = self.dynamic.select_best_video_model()
        credit_pools_summary = self.db.get_credit_pools_summary()
        shift_status = self.coordinator.get_shift_status()
        fp_status = self.curator.get_status()

        accounts = self.db.get_detailed_accounts()
        platform_alerts = self.db.get_active_platform_alerts()
        try:
            discovered_profiles = BrowserAccountResolver.discover_all_browser_profiles()
        except Exception:
            discovered_profiles = []

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pool_id, tier, total_credits, remaining_credits, used_today, target_consumption_days FROM credit_pools"
            )
            pools = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT key_alias, api_key, priority, status, requests_today FROM gemini_keys")
            raw_keys = [dict(r) for r in cursor.fetchall()]
            keys = []
            for r in raw_keys:
                k_copy = dict(r)
                k_copy["api_key"] = SecurityVault.mask_secret(k_copy.get("api_key", ""))
                keys.append(k_copy)

            cursor.execute("""
                SELECT uuid, filename, asset_type, model_used, status, qc_tier, qc_score,
                       technical_score, motion_continuity_score,
                       adobe_status, freepik_status,
                       seo_title, adobe_title, freepik_title, seo_keywords,
                       category, opencv_sharpness, qc1_feedback, qc2_feedback,
                       is_freepik_150_golden, created_at
                FROM assets
                ORDER BY id DESC LIMIT 80
            """)
            recent_assets = [dict(r) for r in cursor.fetchall()]

            freepik_ledger = [
                {
                    "filename": r.get("filename", ""),
                    "width": 4096,
                    "height": 4096,
                    "megapixels": r.get("megapixels", 0),
                    "sharpness_score": r.get("sharpness_score", 0),
                    "passed": r.get("decision") == "approved_150",
                    "rejection_reason": r.get("reason", ""),
                    "inspected_at": r.get("inspected_at", ""),
                }
                for r in self.curator.get_ledger_items(limit=60)
            ]

            cursor.execute("""
                SELECT active_argon_account AS account_used,
                       winning_niches_json AS active_winning_niches,
                       blacklisted_json AS blacklisted_concepts,
                       handoff_summary,
                       updated_at AS created_at
                FROM agent_memory_snapshots
                ORDER BY id DESC LIMIT 5
            """)
            memory_snapshots = [dict(r) for r in cursor.fetchall()]

        production_prefs = self.db.get_production_preferences()
        cached_audit_raw = self.db.get_adaptive_rule("audit.last_pre_shift_json", "")
        pre_shift_audit = None
        if cached_audit_raw:
            try:
                pre_shift_audit = json.loads(cached_audit_raw)
            except Exception:
                pre_shift_audit = None
        if not pre_shift_audit:
            pre_shift_audit = self.coordinator.run_pre_shift_ai_audit()

        ws_root = Config.get_workspace_dir()
        for sub in [
            "0_Raw_Downloads",
            "1_QC1_Approved",
            "1_QC_Borderline",
            "1_QC1_Rejected",
            "2_Upscaled",
            "2_QC2_Approved",
            "3_Batched_Ready",
            "4_Uploaded_Awaiting_Submit",
            "exports",
        ]:
            (ws_root / sub).mkdir(parents=True, exist_ok=True)

        folders = {
            "workspace_path": production_prefs.get("external_workspace_path") or str(ws_root),
            "data_dir": str(Config.get_user_data_dir()),
            "raw": len(list((ws_root / "0_Raw_Downloads").glob("*.*"))),
            "qc1_approved": len(list((ws_root / "1_QC1_Approved").glob("*.*"))),
            "borderline": len(list((ws_root / "1_QC_Borderline").glob("*.*"))),
            "upscaled": len(list((ws_root / "2_Upscaled").glob("*.*"))),
            "qc2_approved": len(list((ws_root / "2_QC2_Approved").glob("*.*"))),
            "batched": len(list((ws_root / "3_Batched_Ready").glob("Batch_*"))),
            "awaiting_submit": len(list((ws_root / "4_Uploaded_Awaiting_Submit").glob("Batch_*"))),
            "freepik_golden": fp_status.curated_count,
        }

        ftp_cred = get_secure_credential(self.db, "ftp")
        freepik_cred = get_secure_credential(self.db, "freepik")
        ftp_meta = (ftp_cred.get("metadata") if ftp_cred else {}) or {}
        freepik_meta = (freepik_cred.get("metadata") if freepik_cred else {}) or {}

        ftp_info = {
            "host": ftp_meta.get("host") or Config.get("ftp.host", "ftp.contributor.adobestock.com"),
            "port": int(ftp_meta.get("port") or Config.get("ftp.port", 21)),
            "username": (ftp_cred.get("username") if ftp_cred else None) or Config.get("ftp.username", ""),
            "configured": bool(
                (ftp_cred and ftp_cred.get("secret"))
                or (Config.get("ftp.username", "") and Config.get("ftp.password", ""))
            ),
        }

        freepik_info = {
            "username": (freepik_cred.get("username") if freepik_cred else None) or Config.get("freepik.username", ""),
            "mode": freepik_meta.get("mode") or Config.get("freepik.mode", "standby"),
            "configured": bool((freepik_cred and freepik_cred.get("secret")) or Config.get("freepik.username", "")),
        }

        learnings = self.dynamic.get_blacklisted_concepts()
        video_stats = self.db.get_video_stats()
        dual_breakdown = self.db.get_dual_platform_breakdown()
        strategic_intel = self.dynamic.get_strategic_intelligence()
        downloads_analytics = self.db.get_downloads_performance_analytics()
        commercial_evaluation = self.dynamic.get_commercial_download_evaluation()

        available_batches = ["ALL_APPROVED_VAULT"] + [
            b.name for b in (ws_root / "3_Batched_Ready").glob("Batch_*")
        ]

        monitor = get_monitor()
        mon_state = monitor.get_state()

        raw_count = folders["raw"]
        qc1_count = folders["qc1_approved"]
        is_busy = self.is_pipeline_busy or mon_state["is_running"] or self.coordinator.is_running_shift
        is_finished_today = (
            raw_count == 0
            and qc1_count == 0
            and not is_busy
            and shift_status["shift"].get("status") == "completed"
        )

        live_activity = {
            "is_busy": is_busy,
            "is_finished_today": is_finished_today,
            "stage_code": mon_state["current_stage_code"]
            if is_busy
            else ("COMPLETED_TODAY" if is_finished_today else "IDLE"),
            "stage_title_ar": mon_state["current_stage_title_ar"]
            if is_busy
            else (
                "🎉 أنهى الموظف الذكي وردية اليوم بنجاح!"
                if is_finished_today
                else shift_status.get("next_action_ar", "النظام في وضع الاستعداد")
            ),
            "stage_title_en": mon_state["current_stage_title_en"]
            if is_busy
            else ("Daily Shift Completed" if is_finished_today else "System Standing By"),
            "file": mon_state["current_filename"],
            "file_index": mon_state["current_file_index"],
            "total_files": mon_state["total_files_in_run"],
            "progress_pct": mon_state["percentage"],
            "upload_speed": mon_state["upload_speed"],
            "daily_stats": mon_state["daily_stats"],
            "events": mon_state["recent_events"],
        }

        state_data = {
            "metrics": metrics,
            "pro_burn_target": pro_burn,
            "plus_burn_target": plus_burn,
            "rolling_buffer": rolling_buffer,
            "video_model_plan": video_model_plan,
            "credit_pools_summary": credit_pools_summary,
            "production_preferences": production_prefs,
            "pre_shift_audit": pre_shift_audit,
            "agent_shift": shift_status,
            "memory_snapshots": memory_snapshots,
            "freepik_gate": {
                "curated": fp_status.curated_count,
                "target": fp_status.total_target,
                "needed": fp_status.needed_count,
                "isolated": fp_status.isolated_mockup_count,
                "backgrounds": fp_status.full_bleed_bg_count,
                "ready": fp_status.is_ready_for_submission,
                "total_ever_inspected": fp_status.total_ever_inspected,
                "target_folder": fp_status.target_folder,
                "source_folder": Config.get("freepik.candidate_source_dir", str(ws_root / "2_QC2_Approved")),
                "ledger": freepik_ledger,
            },
            "video_stats": video_stats,
            "dual_breakdown": dual_breakdown,
            "strategic_intelligence": strategic_intel,
            "downloads_analytics": downloads_analytics,
            "commercial_evaluation": commercial_evaluation,
            "available_batches": available_batches,
            "live_activity": live_activity,
            "accounts": accounts,
            "platform_alerts": platform_alerts,
            "discovered_profiles": discovered_profiles,
            "credit_pools": pools,
            "gemini_keys": keys,
            "keys": keys,
            "recent_assets": recent_assets,
            "folders": folders,
            "ftp_info": ftp_info,
            "freepik_info": freepik_info,
            "learnings": learnings,
            "is_busy": is_busy,
            "upscale_models_report": get_all_models_report(),
            "setup_completed": bool(Config.get("setup.completed", False) or len(keys) > 0 or len(accounts) > 0),
            "models": {
                "image": Config.get("models.image", "nano banana pro"),
                "video": video_model_plan.get("selected_model", Config.get("models.video", "omni flash")),
                "upscaler": f"{validate_upscale_model(Config.get('upscayl.default_model', 'high-fidelity-4x'))} (2x Strictly Enforced)",
            },
        }
        return json.dumps(state_data)

    # ── Daily Employee & Auto-Pilot Controls ──────────────────────────────────
    def start_daily_employee_shift(self) -> str:
        """Triggers the autonomous 5-step Daily Employee shift immediately."""
        res = self.coordinator.execute_daily_shift_async(force=True)
        return json.dumps(res)

    def run_pipeline_cycle(self) -> str:
        """Alias that triggers the full autonomous daily employee shift."""
        return self.start_daily_employee_shift()

    def toggle_autopilot(self, enabled: bool = True) -> str:
        """Toggles whether the Daily Employee runs automatically on startup."""
        res = self.coordinator.set_auto_pilot(bool(enabled))
        return json.dumps(res)

    # ── Multi-Account Gemini / Argon & Credit Pools Management ────────────────
    def set_primary_argon_account(self, profile_name: str) -> str:
        """Designates the Primary Master Argon account to preserve strategic conversation history."""
        if not profile_name:
            return json.dumps({"status": "error", "message": "Profile name is required."})
        self.db.set_primary_argon_account(profile_name)
        return json.dumps({
            "status": "success",
            "message": f"تم تعيين الحساب '{profile_name}' كحساب Argon الأساسي للحفاظ على سجل المحادثات.",
        })

    def update_pool_credits(self, pool_id: str, total_credits: int, remaining_credits: int) -> str:
        """Allows the user to update Plus (200) or Pro (1000) credit pool balances directly."""
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE credit_pools
                SET total_credits = ?, remaining_credits = ?
                WHERE pool_id = ?;
                """,
                (int(total_credits), int(remaining_credits), pool_id),
            )
        return json.dumps({
            "status": "success",
            "message": f"تم تحديث رصيد المحفظة ({pool_id}): المتبقي {remaining_credits} من {total_credits}.",
        })

    def reset_daily_free_credits(self) -> str:
        """Resets the daily 50 free credit counters across all accounts for a fresh day."""
        self.db.reset_daily_account_usage()
        return json.dumps({
            "status": "success",
            "message": "تم تصفير عدادات الـ 50 نقطة المجانية اليومية لجميع الحسابات.",
        })

    def simulate_credit_step(self, points: int = 10) -> str:
        """
        Tests the strict credit priority selector:
        1. Free 50/day accounts first
        2. Plus 200/mo pool second
        3. Pro 1000/mo pool third
        """
        chosen = self.db.select_next_account_for_credits(points_needed=int(points))
        if not chosen:
            return json.dumps({
                "status": "exhausted",
                "message": "تم استنفاد جميع النقاط المتاحة حالياً في كافة الحسابات.",
            })
        self.db.record_account_credit_spend(
            profile_name=chosen["profile_name"],
            points_spent=int(points),
            source_pool=chosen["credit_source"],
        )
        return json.dumps({
            "status": "success",
            "chosen": chosen,
            "message": f"تم سحب {points} نقاط من حساب '{chosen['account_name']}' ({chosen['reason_ar']})",
        })

    # ── Video Model Benchmark & 2x Upscale Tester ─────────────────────────────
    def select_video_model(self, model_name: str) -> str:
        """Manually sets the preferred low-credit video model (blocks 100-credit Quality modes)."""
        if "100" in model_name.lower() or "quality" in model_name.lower():
            return json.dumps({
                "status": "error",
                "message": "مرفوض: نظام Quality أبو 100 كريديت محظور نهائياً للحفاظ على الرصيد.",
            })
        Config.set("models.video", model_name.strip().lower())
        self.db.update_daily_shift(active_video_model=model_name.strip().lower())
        return json.dumps({
            "status": "success",
            "message": f"تم اعتماد موديل الفيديو '{model_name}' كخيار أساسي (مع حظر موديل الـ 100 نقطة).",
        })

    def benchmark_video_models_now(self) -> str:
        """Runs an evaluation of all eligible low-credit video models and locks onto the top scorer."""
        winner = self.dynamic.select_best_video_model()
        Config.set("models.video", winner["selected_model"])
        return json.dumps({
            "status": "success",
            "winner": winner,
            "message": f"تم تحليل أداء الموديلات واختيار الأفضل: {winner['selected_model'].upper()} (درجة الكفاءة: {winner['composite_score']})",
        })

    def test_upscale_2x_comparison(self) -> str:
        """Runs a 2x upscale comparison across commercial-safe models on the first available image."""
        ws_root = Config.get_workspace_dir()
        candidates = (
            list((ws_root / "2_QC2_Approved").glob("*.jpg"))
            + list((ws_root / "1_QC1_Approved").glob("*.jpg"))
            + list((ws_root / "0_Raw_Downloads").glob("*.jpg"))
        )
        if not candidates:
            return json.dumps({
                "status": "info",
                "message": "ضع صورة واحدة على الأقل في مجلد 0_Raw_Downloads لتجربة مقارنة التكبير 2x.",
                "default_model": "high-fidelity-4x (scale=2)",
            })
        res = self.pipeline.upscaler.compare_models_on_sample(candidates[0])
        return json.dumps({"status": "success", "comparison": res})

    # ── Freepik 150 Gate (Dedicated Tab & Stateful SHA-256 Ledger) ────────────
    def curate_freepik_golden(self, custom_source_dir: str = "") -> str:
        """
        Executes Freepik 150 incremental golden curation.
        Records every inspected image's SHA-256 in SQLite (`freepik_150_ledger`)
        so previously inspected images are automatically skipped on future runs.
        """
        if self.is_pipeline_busy:
            return json.dumps({"status": "error", "message": "انتظر انتهاء دورة الفحص الحالية أولاً."})

        try:
            if custom_source_dir and Path(custom_source_dir).exists():
                Config.set("freepik.candidate_source_dir", custom_source_dir)
                self.curator.source_dirs[0] = Path(custom_source_dir)

            res = self.curator.run_incremental_curation()
            return json.dumps({"status": "success", "result": res})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def set_freepik_source_folder(self, folder_path: str) -> str:
        """Sets the custom candidate source folder for the Freepik 150 Gate tab."""
        p = Path(folder_path.strip())
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return json.dumps({"status": "error", "message": f"مسار غير صالح: {e}"})
        Config.set("freepik.candidate_source_dir", str(p))
        return json.dumps({
            "status": "success",
            "folder": str(p),
            "message": f"تم تحديد مجلد فحص الـ 150 صورة لـ Freepik: {p}",
        })

    # ── Review Queue, Borderline Triage & Clean SEO Editing ───────────────────
    def approve_borderline_asset(self, filename: str) -> str:
        """Promotes a borderline ('Needs Quick Look') asset into 2_QC2_Approved."""
        ws_root = Config.get_workspace_dir()
        src = ws_root / "1_QC_Borderline" / filename
        dst = ws_root / "2_QC2_Approved" / filename
        if src.exists():
            src.replace(dst)
        self.db.update_asset(
            Path(filename).stem,
            filename=filename,
            status="qc2_pass",
            adobe_status="pending",
            freepik_status="candidate_150",
            current_path=str(dst),
        )
        return json.dumps({"status": "success", "message": f"تم اعتماد الملف '{filename}' ونقله إلى القائمة الجاهزة."})

    def reject_borderline_asset(self, filename: str) -> str:
        """Moves a borderline asset into Rejected."""
        ws_root = Config.get_workspace_dir()
        src = ws_root / "1_QC_Borderline" / filename
        dst = ws_root / "2_QC2_Rejected" / filename
        if src.exists():
            src.replace(dst)
        self.db.update_asset(
            Path(filename).stem,
            filename=filename,
            status="qc2_fail",
            current_path=str(dst),
        )
        return json.dumps({"status": "success", "message": f"تم استبعاد الملف '{filename}'."})

    def update_asset_seo(self, filename: str, title: str, keywords: str, category: str = "") -> str:
        """Updates SEO metadata in SQLite without touching the binary image/video file."""
        updates: dict[str, Any] = {
            "filename": filename,
            "seo_title": title.strip(),
            "seo_keywords": keywords.strip(),
        }
        if category:
            updates["category"] = str(category).strip()
        self.db.update_asset(Path(filename).stem, **updates)
        return json.dumps({
            "status": "success",
            "message": f"تم تحديث عنوان وكلمات '{filename}' في قاعدة البيانات لملفات CSV المنفصلة.",
        })

    def record_platform_outcome(
        self,
        filename: str,
        platform: str = "adobe",
        outcome: str = "accepted",
        rejection_reason: str = "",
    ) -> str:
        """
        Records Accepted or Rejected feedback from Adobe Stock or Freepik.
        Automatically updates the self-learning DynamicController and rolling buffer capacity.
        """
        col = "adobe_status" if platform.lower() == "adobe" else "freepik_status"
        status_val = f"{platform.lower()}_{outcome.lower()}"
        with self.db.get_connection() as conn:
            conn.execute(
                f"UPDATE assets SET {col} = ?, status = CASE WHEN ? = 'accepted' THEN 'adobe_accepted' ELSE status END WHERE filename = ?;",
                (outcome.lower(), outcome.lower(), filename),
            )
            if outcome.lower() == "rejected" and rejection_reason:
                conn.execute(
                    """
                    INSERT INTO rejections (asset_uuid, platform, rejection_reason, specific_details)
                    VALUES (?, ?, ?, ?);
                    """,
                    (Path(filename).stem, platform.lower(), rejection_reason, rejection_reason),
                )
        # Re-calibrate thresholds & rolling buffer
        self.dynamic.get_metrics()
        return json.dumps({
            "status": "success",
            "message": f"تم تسجيل حالة '{outcome.upper()}' على منصة {platform.upper()} وتحديث خوارزمية التعلم الذاتي.",
        })

    def get_asset_thumbnail(self, filename: str) -> str:
        """Returns a base64-encoded thumbnail for an image or middle frame for a video."""
        from PIL import Image

        ws_root = Config.get_workspace_dir()
        data_dir = Config.get_user_data_dir()
        candidate_paths = [
            ws_root / "2_QC2_Approved" / filename,
            ws_root / "1_QC_Borderline" / filename,
            ws_root / "2_Upscaled" / filename,
            ws_root / "1_QC1_Approved" / filename,
            ws_root / "0_Raw_Downloads" / filename,
            data_dir / "golden_freepik_150" / filename,
            PROJECT_ROOT / "data" / "golden_freepik_150" / filename,
        ]
        found = next((p for p in candidate_paths if p.exists()), None)
        if not found:
            return json.dumps({"status": "not_found"})

        try:
            if found.suffix.lower() in {".mp4", ".mov"}:
                import cv2
                cap = cv2.VideoCapture(str(found))
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(rgb)
                    pil_img.thumbnail((240, 240))
                    buf = io.BytesIO()
                    pil_img.save(buf, format="JPEG", quality=80)
                    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    return json.dumps({"status": "success", "data_uri": f"data:image/jpeg;base64,{b64}"})
                return json.dumps({"status": "not_found"})

            with Image.open(found) as img:
                img.thumbnail((240, 240))
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                return json.dumps({"status": "success", "data_uri": f"data:image/jpeg;base64,{b64}"})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    # ── API Keys, FTP, Backup & Health Checks ─────────────────────────────────
    def backup_to_gdrive(self) -> str:
        """Triggers immediate local/cloud backup snapshot."""
        try:
            snap = self.cloud.create_snapshot()
            return json.dumps({"status": "success", "path": str(snap)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def save_api_key(self, alias: str, key: str) -> str:
        """Saves a new Google AI Studio API key to local SQLite database with encryption."""
        if not key or not alias:
            return json.dumps({"status": "error", "message": "الاسم المستعار والمفتاح مطلوبان."})

        encrypted_key = SecurityVault.encrypt(key.strip())
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO gemini_keys (key_alias, api_key, priority, status)
                VALUES (?, ?, 1, 'active')
                ON CONFLICT(key_alias) DO UPDATE SET
                    api_key = excluded.api_key,
                    status = 'active';
                """,
                (alias.strip(), encrypted_key),
            )
        Config.load()
        return json.dumps({"status": "success", "message": f"تم تشفير وحفظ مفتاح '{alias}' بنجاح."})

    add_gemini_key = save_api_key

    def delete_api_key(self, alias: str) -> str:
        """Removes an API key from local database."""
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM gemini_keys WHERE key_alias = ?", (alias.strip(),))
        Config.load()
        return json.dumps({"status": "success", "message": f"تم حذف المفتاح '{alias}'."})

    delete_gemini_key = delete_api_key

    def test_api_key(self, alias: str) -> str:
        """Pings Google AI Studio with `gemini-2.5-flash` to verify connectivity and quota."""
        raw_key = alias
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT api_key FROM gemini_keys WHERE key_alias = ?", (alias.strip(),))
            row = cursor.fetchone()
            if row:
                raw_key = row["api_key"]

        key_str = SecurityVault.decrypt(raw_key)
        try:
            from google import genai
            client = genai.Client(api_key=key_str)
            t0 = time.perf_counter()
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents="Reply with 'OK'.",
            )
            elapsed = int((time.perf_counter() - t0) * 1000)
            self.db.clear_platform_alerts("Google AI Studio API", alias)
            return json.dumps({
                "status": "success",
                "message": f"المفتاح يعمل بنجاح! زمن الاستجابة: {elapsed}ms ({(resp.text or 'OK').strip()})",
            })
        except Exception as e:
            err_str = str(e)
            err_type = "RATE_LIMIT_429" if "429" in err_str else ("AUTH_403" if "403" in err_str else "API_ERROR")
            hint = (
                "المفتاح وصل للحد المؤقت وسيقوم النظام بالتدوير التلقائي لمفتاح آخر."
                if "429" in err_str
                else "تأكد من صحة المفتاح من Google AI Studio."
            )
            self.db.record_platform_alert(
                "Google AI Studio API",
                alias,
                err_type,
                err_str,
                hint,
                severity="critical" if "403" in err_str else "warning",
            )
            return json.dumps({"status": "error", "message": f"فشل اختبار المفتاح: {e}"})

    test_gemini_key = test_api_key

    def save_ftp_credentials(self, username: str, password: str, host: str, port: int) -> str:
        """Encrypts and saves Adobe Stock SFTP/FTP credentials in local SQLite database."""
        save_secure_credential(
            self.db,
            service="ftp",
            username=username.strip(),
            secret=password.strip(),
            metadata={"host": host.strip(), "port": int(port)},
        )
        Config.set("ftp.username", username.strip())
        Config.set("ftp.host", host.strip())
        Config.set("ftp.port", int(port))
        return json.dumps({"status": "success", "message": "تم تشفير وحفظ بيانات رفع Adobe Stock بنجاح."})

    def save_freepik_credentials(self, username: str, password: str, mode: str = "standby") -> str:
        """Encrypts and saves Freepik credentials in local SQLite database."""
        save_secure_credential(
            self.db,
            service="freepik",
            username=username.strip(),
            secret=password.strip(),
            metadata={"mode": mode},
        )
        Config.set("freepik.username", username.strip())
        Config.set("freepik.mode", mode)
        return json.dumps({"status": "success", "message": f"تم حفظ إعدادات Freepik (الوضع: {mode.upper()})."})

    def test_ftp_connection(self, platform: str = "adobe") -> str:
        """Tests live FTP connection using encrypted credentials stored in local DB."""
        import ftplib

        if platform == "adobe":
            cred = get_secure_credential(self.db, "ftp")
            meta = (cred.get("metadata") if cred else {}) or {}
            host = meta.get("host") or Config.get("ftp.host", "ftp.contributor.adobestock.com")
            port = int(meta.get("port") or Config.get("ftp.port", 21))
            user = (cred.get("username") if cred else None) or Config.get("ftp.username", "")
            pwd = (cred.get("secret") if cred else None) or Config.get_ftp_password()
        else:
            cred = get_secure_credential(self.db, "freepik")
            meta = (cred.get("metadata") if cred else {}) or {}
            host = meta.get("host") or Config.get("freepik.ftp_host", "ftp.freepik.com")
            port = int(meta.get("port") or Config.get("freepik.ftp_port", 21))
            user = (cred.get("username") if cred else None) or Config.get("freepik.username", "")
            pwd = (cred.get("secret") if cred else None) or Config.get_freepik_password()

        if not user or not pwd:
            hint = "أدخل اسم المستخدم وكلمة المرور في الإعدادات أولاً."
            self.db.record_platform_alert(
                f"{platform.upper()} FTP",
                str(host),
                "MISSING_CREDENTIALS",
                "بيانات الاتصال غير مكتملة",
                hint,
                severity="warning",
            )
            return json.dumps({"status": "error", "message": f"بيانات {platform.upper()} FTP غير مكتملة."})

        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=10)
            ftp.login(user, pwd)
            welcome = ftp.getwelcome()
            ftp.quit()
            self.db.clear_platform_alerts(f"{platform.upper()} FTP", user)
            return json.dumps({"status": "success", "message": f"تم الاتصال بـ {host} بنجاح!\n{welcome}"})
        except Exception as e:
            err_str = str(e)
            hint = (
                "تأكد من استخدام Contributor ID وكلمة مرور FTP المخصصة من حساب المساهم."
                if "530" in err_str
                else "تحقق من اتصال الإنترنت والمنفذ."
            )
            self.db.record_platform_alerts if hasattr(self.db, "record_platform_alerts") else None
            self.db.record_platform_alert(
                f"{platform.upper()} FTP",
                user or host,
                "AUTH_FAILED" if "530" in err_str else "CONNECTION_TIMEOUT",
                err_str,
                hint,
                severity="critical",
            )
            return json.dumps({"status": "error", "message": f"فشل الاتصال بـ {host}: {e}"})

    def ask_argon_copilot(
        self,
        prompt: str,
        model_choice: str = "gemini-2.5-pro",
        thinking_level: str = "medium",
    ) -> str:
        """
        Sends strategic query to Gemini / Argon with SQLite Handoff Report injection
        so if Primary Account #1 rotates to Account #2, zero strategic history is lost.
        """
        from stockpilot.strategy.memory_context import MemoryContextBuilder

        mem = MemoryContextBuilder()
        primary_acc = self.db.get_primary_argon_account()
        acc_label = (primary_acc.get("account_name") or primary_acc.get("email")) if primary_acc else "Primary_Argon"
        header = mem.build_memory_prompt_header(current_account_name=acc_label, is_failover=False)
        full_query = f"{header}\nThinking Level: {thinking_level.upper()}\nUser Request: {prompt}"

        key = self.pipeline.qc1.rotator.get_key()
        if not key:
            return json.dumps({
                "status": "error",
                "reply": "يرجى إضافة مفتاح Google AI Studio API واحد على الأقل من تبويب الإعدادات والحسابات.",
            })

        target_model = "gemini-2.5-pro" if "pro" in model_choice.lower() or "argon" in model_choice.lower() else "gemini-2.5-flash"

        try:
            from google import genai
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(model=target_model, contents=full_query)
            reply_text = resp.text or ""
            mem.save_snapshot_after_cycle(account_name=acc_label, summary_note=f"Copilot Q: {prompt[:80]} -> {reply_text[:120]}")
            return json.dumps({"status": "success", "reply": reply_text, "model": f"{target_model} ({acc_label})"})
        except Exception:
            try:
                from google import genai
                client = genai.Client(api_key=key)
                resp = client.models.generate_content(model="gemini-2.5-flash", contents=full_query)
                reply_text = resp.text or ""
                mem.save_snapshot_after_cycle(account_name=acc_label, summary_note=f"Fallback Q: {prompt[:80]}")
                return json.dumps({"status": "success", "reply": reply_text, "model": f"gemini-2.5-flash ({acc_label})"})
            except Exception as e2:
                return json.dumps({"status": "error", "reply": f"خطأ في الاتصال بالنموذج: {e2}"})

    def export_batch_csv(self, platform: str, batch_id: str = "ALL_APPROVED_VAULT") -> str:
        """
        Generates platform-specific CSV dynamically (without touching image/video binaries):
        - Adobe Stock: comma-separated (Filename, Title, Keywords, Category, Releases)
        - Freepik: semicolon-separated (File name; Title; Keywords; Prompt; Model)
        """
        from stockpilot.metadata.batch_exporter import BatchExporter

        exporter = BatchExporter()
        ws_root = Config.get_workspace_dir()
        export_dir = ws_root / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if batch_id == "ALL_APPROVED_VAULT":
                cursor.execute("""
                    SELECT uuid, filename, asset_type, seo_title, seo_keywords, original_prompt, concept_id, category, model_used, status, is_freepik_150_golden
                    FROM assets
                    WHERE status IN ('qc2_pass', 'uploaded', 'adobe_accepted')
                    ORDER BY id DESC
                """)
            else:
                cursor.execute(
                    """
                    SELECT uuid, filename, asset_type, seo_title, seo_keywords, original_prompt, concept_id, category, model_used, status, is_freepik_150_golden
                    FROM assets
                    WHERE batch_id = ?
                    ORDER BY id ASC
                    """,
                    (batch_id,),
                )
            assets = [dict(r) for r in cursor.fetchall()]

        if not assets:
            approved_files = list((ws_root / "2_QC2_Approved").glob("*.jpg")) + list((ws_root / "2_QC2_Approved").glob("*.mp4"))
            for p in approved_files:
                title_guess = p.stem.replace("_", " ")
                kws_guess = "commercial, premium, modern, stock concept, high quality, authentic"
                cat_id, cat_name = CategoryClassifier.get_adobe_category_id_and_name(title=title_guess, keywords=kws_guess)
                assets.append({
                    "filename": p.name,
                    "asset_type": "video" if p.suffix.lower() == ".mp4" else "image",
                    "seo_title": title_guess,
                    "seo_keywords": kws_guess,
                    "category": cat_id,
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "original_prompt": title_guess,
                    "model_used": "Nano Banana Pro",
                })

        if not assets:
            return json.dumps({"status": "error", "message": "لا توجد ملفات معتمدة جاهزة لتصدير CSV حالياً."})

        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", batch_id).lower()
        if platform.lower() == "both":
            res = exporter.export_both_platforms(assets, export_dir, batch_id=safe_id)
            return json.dumps(res)
        elif platform.lower() == "adobe":
            out_file = export_dir / f"Adobe_Stock_Batch_{safe_id}.csv"
            res = exporter.export_adobe_stock_csv(assets, out_file)
            return json.dumps(res)
        else:
            out_file = export_dir / f"Freepik_Batch_{safe_id}.csv"
            res = exporter.export_freepik_csv(assets, out_file)
            return json.dumps(res)

    def open_folder_in_explorer(self, folder_type: str = "exports") -> str:
        """Opens specific workspace folder in Windows File Explorer."""
        ws_root = Config.get_workspace_dir()
        mapping = {
            "exports": ws_root / "exports",
            "workspace": ws_root,
            "raw": ws_root / "0_Raw_Downloads",
            "borderline": ws_root / "1_QC_Borderline",
            "qc2": ws_root / "2_QC2_Approved",
            "batched": ws_root / "3_Batched_Ready",
            "uploaded": ws_root / "4_Uploaded_Awaiting_Submit",
            "freepik_150": Config.get_user_data_dir() / "golden_freepik_150",
        }
        target = mapping.get(folder_type, ws_root)
        target.mkdir(parents=True, exist_ok=True)
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(target))
            return json.dumps({"status": "success", "opened": str(target)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e), "path": str(target)})

    def run_comprehensive_health_check(self) -> str:
        """Runs an end-to-end health test on all browser accounts, Adobe FTP, Freepik, and Gemini API keys."""
        results: dict[str, Any] = {
            "browser_accounts": {"tested": 0, "healthy": 0, "failed": 0},
            "adobe_ftp": {"status": "untested"},
            "freepik": {"status": "untested"},
            "gemini_api": {"tested": 0, "healthy": 0, "failed": 0},
        }

        accounts = self.db.get_detailed_accounts()
        for acc in accounts:
            results["browser_accounts"]["tested"] += 1
            p_dir = acc.get("profile_dir", "Default")
            user_data = acc.get("browser", "chrome")
            roots = BrowserAccountResolver.get_standard_browser_roots()
            base_path = roots.get(user_data, roots.get("chrome", Path(".")))
            resolved = BrowserAccountResolver.resolve_profile_info(base_path, p_dir)
            if not resolved["is_valid"]:
                results["browser_accounts"]["failed"] += 1
                self.db.update_account_health(
                    acc["profile_name"],
                    "error",
                    resolved["error"],
                    "تأكد من وجود مجلد البروفايل أو اختر بروفايل من المكتشفة.",
                )
            else:
                results["browser_accounts"]["healthy"] += 1
                self.db.update_account_health(acc["profile_name"], "active", "", "")

        if Config.get("ftp.username"):
            results["adobe_ftp"] = json.loads(self.test_ftp_connection("adobe"))
        if Config.get("freepik.username"):
            results["freepik"] = json.loads(self.test_ftp_connection("freepik"))

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key_alias FROM gemini_keys WHERE status = 'active';")
            keys = cursor.fetchall()
            for k in keys:
                results["gemini_api"]["tested"] += 1
                key_res = json.loads(self.test_api_key(k["key_alias"]))
                if key_res["status"] == "success":
                    results["gemini_api"]["healthy"] += 1
                else:
                    results["gemini_api"]["failed"] += 1

        active_alerts = self.db.get_active_platform_alerts()
        return json.dumps({
            "status": "success",
            "results": results,
            "alerts_count": len(active_alerts),
            "alerts": active_alerts,
        })

    def resolve_alert(self, alert_id: int) -> str:
        self.db.resolve_platform_alert(int(alert_id))
        return json.dumps({"status": "success", "message": f"تم إغلاق التنبيه #{alert_id}."})

    def clear_all_alerts(self) -> str:
        with self.db.get_connection() as conn:
            conn.execute("UPDATE platform_alerts SET resolved = 1 WHERE resolved = 0;")
        return json.dumps({"status": "success", "message": "تم مسح جميع التنبيهات."})

    def save_google_account(
        self,
        profile_name: Any = "",
        account_name: str = "",
        email: str = "",
        tier: str = "auto",
        pool_id: str | None = None,
        browser: str = "chrome",
        profile_dir: str = "Default",
        is_primary_argon: bool = False,
        is_shared_pool: bool = False,
        renewal_day: int = 24,
        monthly_remaining: int | None = None,
        detected_models: str = "",
        **kwargs: Any,
    ) -> str:
        """
        Adds or updates a Google Gemini / Argon account in the database.
        Supports dynamic tier/model discovery based on entered email or explicit tier selection,
        shared vs. individual pool mode (`is_shared_pool`), and subscription renewal day.
        """
        if isinstance(profile_name, dict):
            data = profile_name
            profile_name = data.get("profile_name", "")
            account_name = data.get("account_name", "")
            email = data.get("email", "")
            tier = data.get("tier", "auto")
            pool_id = data.get("pool_id")
            browser = data.get("browser", "chrome")
            profile_dir = data.get("profile_dir", "Default")
            is_primary_argon = bool(data.get("is_primary_argon", False))
            is_shared_pool = bool(data.get("is_shared_pool", False))
            renewal_day = int(data.get("renewal_day", 24) or 24)
            if data.get("monthly_remaining") not in (None, ""):
                try:
                    monthly_remaining = int(data["monthly_remaining"])
                except ValueError:
                    monthly_remaining = None
            detected_models = str(data.get("detected_models", ""))

        email_clean = (email or account_name or "").strip()
        if not email_clean:
            return json.dumps({"status": "error", "message": "Email or account identifier is required / البريد الإلكتروني مطلوب."})

        if not account_name:
            account_name = email_clean.split("@")[0] if "@" in email_clean else email_clean

        if not profile_name:
            profile_name = re.sub(r"[^a-zA-Z0-9_-]", "_", email_clean).lower()

        tier_clean = (tier or "auto").strip().lower()
        if tier_clean == "auto":
            low_em = email_clean.lower()
            if "pro" in low_em or "1000" in low_em or "ultra" in low_em:
                tier_clean = "pro"
            elif "plus" in low_em or "200" in low_em or "adv" in low_em:
                tier_clean = "plus"
            else:
                tier_clean = "free"

        if tier_clean not in ("free", "plus", "pro"):
            tier_clean = "free"

        if not detected_models:
            if tier_clean == "pro":
                detected_models = "omni flash,veo fast,kling standard,hailuo minimax"
            elif tier_clean == "plus":
                detected_models = "omni flash,veo fast,kling standard"
            else:
                detected_models = "omni flash,wan 2.1"

        limit = 50
        pool = pool_id.strip() if (pool_id and str(pool_id).strip()) else ("pro_pool" if tier_clean == "pro" else ("plus_pool" if tier_clean == "plus" else "free_daily_pool"))

        self.db.upsert_account(
            profile_name=str(profile_name),
            account_name=account_name.strip(),
            email=email_clean,
            tier=tier_clean,
            pool_id=pool,
            daily_limit=limit,
            browser=browser,
            profile_dir=profile_dir,
            status="active",
            is_primary_argon=1 if is_primary_argon else 0,
            is_shared_pool=1 if is_shared_pool else 0,
            renewal_day=int(renewal_day or 24),
            monthly_remaining=monthly_remaining,
            detected_models=detected_models,
        )
        if is_primary_argon:
            self.db.set_primary_argon_account(str(profile_name))

        # Re-run Pre-Shift AI Audit so the dashboard reflects the new account immediately
        self.coordinator.run_pre_shift_ai_audit()

        return json.dumps({
            "status": "success",
            "tier_detected": tier_clean,
            "detected_models": detected_models,
            "message": f"Account '{email_clean}' saved ({tier_clean.upper()} tier + 50 Free/day) / تم حفظ الحساب وتحديث الرصيد بنجاح.",
        })

    def delete_google_account(self, profile_name: str) -> str:
        self.db.delete_account(profile_name)
        self.coordinator.run_pre_shift_ai_audit()
        return json.dumps({"status": "success", "message": f"Account '{profile_name}' removed / تم حذف الحساب."})

    def run_pre_shift_audit(self) -> str:
        """Runs the Daily Pre-Shift AI Flow & System Auditor on demand and returns structured advice."""
        audit = self.coordinator.run_pre_shift_ai_audit()
        return json.dumps({"status": "success", "audit": audit})

    def update_production_preferences(
        self,
        generation_mode: Any = "videos_only",
        adobe_enabled: bool = True,
        freepik_enabled: bool = True,
        external_workspace_path: str = "",
    ) -> str:
        """Updates whether the engine generates Videos Only, Images Only, or Both, and which stock platforms are active."""
        if isinstance(generation_mode, dict):
            data = generation_mode
            generation_mode = data.get("generation_mode", "videos_only")
            adobe_enabled = bool(data.get("adobe_enabled", True))
            freepik_enabled = bool(data.get("freepik_enabled", True))
            external_workspace_path = str(data.get("external_workspace_path", ""))

        prefs = self.db.set_production_preferences(
            generation_mode=str(generation_mode),
            adobe_enabled=bool(adobe_enabled),
            freepik_enabled=bool(freepik_enabled),
            external_workspace_path=external_workspace_path if external_workspace_path else None,
        )
        if external_workspace_path and external_workspace_path.strip():
            Config.set("paths.workspace_root", external_workspace_path.strip())
        self.coordinator.run_pre_shift_ai_audit()
        return json.dumps({
            "status": "success",
            "preferences": prefs,
            "message": "Production preferences updated / تم تحديث إعدادات الإنتاج والمنصات.",
        })

    def select_external_folder(self, folder_purpose: str = "workspace", custom_path: str = "") -> str:
        """
        Opens a native OS folder picker dialog when running on desktop (or accepts a selected external path)
        so all workspace/candidate media files stay outside the application code directory.
        """
        chosen_dir = custom_path.strip() if custom_path else ""
        if not chosen_dir and self.window_ref:
            try:
                import webview
                win = self.window_ref[0]
                res = win.create_file_dialog(webview.FOLDER_DIALOG)
                if res and len(res) > 0:
                    chosen_dir = str(res[0])
            except Exception:
                pass

        if not chosen_dir:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                selected = filedialog.askdirectory(title="Select External Workspace Folder (Outside Project)")
                root.destroy()
                if selected:
                    chosen_dir = str(selected)
            except Exception:
                pass

        if not chosen_dir:
            # Default external path in user home directory (outside project repo)
            ext_default = Path.home() / "StockNova_External_Workspace"
            ext_default.mkdir(parents=True, exist_ok=True)
            chosen_dir = str(ext_default)

        target_path = Path(chosen_dir)
        target_path.mkdir(parents=True, exist_ok=True)

        if folder_purpose == "freepik_source":
            Config.set("freepik.candidate_source_dir", str(target_path))
        else:
            Config.set("paths.workspace_root", str(target_path))
            self.db.set_adaptive_rule("production.external_workspace_path", str(target_path), "External workspace folder")

        return json.dumps({
            "status": "success",
            "folder": str(target_path),
            "purpose": folder_purpose,
            "message": f"External folder selected: {target_path}",
        })

    def override_asset_qc(self, filename: str, decision: str = "approve") -> str:
        """Manual 1-click QC override for videos or images."""
        if decision == "approve":
            return self.approve_borderline_asset(filename)
        return self.reject_borderline_asset(filename)

    def auto_detect_browser_accounts(self) -> str:
        try:
            updated = BrowserAccountResolver.sync_accounts_with_db(self.db)
            discovered = BrowserAccountResolver.discover_all_browser_profiles()
            return json.dumps({
                "status": "success",
                "message": f"تم اكتشاف {len(discovered)} بروفايل متصفح ومزامنة {len(updated)} حساب.",
                "accounts": self.db.get_detailed_accounts(),
            })
        except Exception as e:
            return json.dumps({"status": "error", "message": f"خطأ أثناء الاكتشاف التلقائي: {e}"})

    def record_manual_downloads(
        self,
        filename: str,
        platform: str = "adobe",
        downloads: int = 1,
        earnings: float = 0.0,
    ) -> str:
        success = self.db.record_asset_downloads(filename, platform, int(downloads), float(earnings))
        if success:
            return json.dumps({
                "status": "success",
                "message": f"تم تسجيل {downloads} تحميلات على {platform.upper()} للملف '{filename}'.",
            })
        return json.dumps({"status": "error", "message": f"الملف '{filename}' غير موجود في قاعدة البيانات."})

    def import_sales_report_csv(self, platform: str, csv_content: str) -> str:
        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            records = []
            for row in reader:
                lower_row = {k.strip().lower() if k else "": v for k, v in row.items()}
                ident = (
                    lower_row.get("file name")
                    or lower_row.get("filename")
                    or lower_row.get("asset id")
                    or lower_row.get("file id")
                    or lower_row.get("title")
                    or ""
                )
                sales_str = lower_row.get("sales") or lower_row.get("downloads") or lower_row.get("count") or "1"
                royalty_str = lower_row.get("royalty") or lower_row.get("royalties") or lower_row.get("earnings") or "0.0"
                try:
                    sales_val = int(re.sub(r"[^0-9]", "", str(sales_str)) or 1)
                except ValueError:
                    sales_val = 1
                try:
                    earn_val = float(re.sub(r"[^0-9.]", "", str(royalty_str)) or 0.0)
                except ValueError:
                    earn_val = 0.0

                if ident:
                    records.append({"filename": ident, "downloads": sales_val, "earnings": earn_val})

            res = self.db.import_contributor_sales_data(platform, records)
            return json.dumps({
                "status": "success",
                "message": f"تم استيراد {len(records)} صف من {platform.upper()} وتحديث {res['updated_assets']} ملف.",
            })
        except Exception as e:
            return json.dumps({"status": "error", "message": f"فشل قراءة ملف CSV: {e}"})

    def complete_first_run_setup(self, workspace_path: str = "", theme: str = "dark") -> str:
        """Saves first-run wizard completion in user's isolated config."""
        if workspace_path.strip():
            Config.set("paths.workspace_root", workspace_path.strip())
            self.db.set_adaptive_rule("production.external_workspace_path", workspace_path.strip(), "External workspace folder")
        Config.set("ui.theme", theme)
        Config.set("setup.completed", True)
        return json.dumps({"status": "success", "message": "تم حفظ إعدادات البداية بنجاح!"})
