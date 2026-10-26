"""
StockNova AI — Modern WebView2 Desktop Application Controller.
Renders an executive-grade, dark-themed native desktop window powered by Microsoft Edge WebView2,
Tailwind CSS, Chart.js, and Lucide icons.
Connects directly to the local Python engine, SQLite database, and pipeline services.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import webview

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.dynamic_controller import DynamicController
from stockpilot.core.cloud_backup import CloudBackupEngine
from stockpilot.core.unified_vault import UnifiedVaultManager
from stockpilot.platforms.freepik_curator import FreepikOnboardingCurator
from stockpilot.quality.model_license_validator import validate_upscale_model
from stockpilot.app import GoogleDotsPipeline
from stockpilot.core.status_monitor import get_monitor
from stockpilot.core.browser_account_resolver import BrowserAccountResolver
from stockpilot.metadata.category_classifier import CategoryClassifier
from stockpilot.core.security import (
    SecurityVault,
    save_secure_credential,
    get_secure_credential,
    delete_secure_credential,
)

PROJECT_ROOT = Path(r"d:\Stock Automation")


class DesktopBridgeAPI:
    """Exposes safe Python methods directly to JavaScript inside WebView2."""

    def __init__(self, window_ref: list[Any]) -> None:
        self.window_ref = window_ref
        self.db = Database()
        self.pipeline = GoogleDotsPipeline()
        self.dynamic = DynamicController()
        self.vault = UnifiedVaultManager()
        self.curator = FreepikOnboardingCurator()
        self.cloud = CloudBackupEngine()
        self.is_pipeline_busy = False
        try:
            BrowserAccountResolver.sync_accounts_with_db(self.db)
        except Exception as e:
            print("Notice on initial account sync:", e)

    def get_full_state(self) -> str:
        """Serializes the entire live system metrics into JSON for UI rendering."""
        metrics = self.dynamic.get_metrics()
        pro_burn = self.dynamic.calculate_dynamic_daily_burn("pro_pool")
        plus_burn = self.dynamic.calculate_dynamic_daily_burn("plus_pool")
        fp_status = self.curator.get_status()

        # Database accounts with real identities and platform health alerts
        accounts = self.db.get_detailed_accounts()
        platform_alerts = self.db.get_active_platform_alerts()
        try:
            discovered_profiles = BrowserAccountResolver.discover_all_browser_profiles()
        except Exception:
            discovered_profiles = []

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pool_id, tier, total_credits, remaining_credits, used_today, target_consumption_days FROM credit_pools")
            pools = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT key_alias, api_key, priority, status, requests_today FROM gemini_keys")
            raw_keys = [dict(r) for r in cursor.fetchall()]
            keys = []
            for r in raw_keys:
                k_copy = dict(r)
                # NEVER expose raw key in UI bridge; return strictly masked representation
                k_copy["api_key"] = SecurityVault.mask_secret(k_copy.get("api_key", ""))
                keys.append(k_copy)

            cursor.execute("""
                SELECT uuid, filename, asset_type, model_used, status, adobe_status, freepik_status, is_freepik_150_golden, created_at 
                FROM assets ORDER BY id DESC LIMIT 50
            """)
            recent_assets = [dict(r) for r in cursor.fetchall()]

        # Workspace folders summary
        ws_root = Config.get_path("paths.workspace_root", PROJECT_ROOT / "workspace")
        folders = {
            "workspace_path": str(ws_root),
            "raw": len(list((ws_root / "0_Raw_Downloads").glob("*.*"))),
            "qc1_approved": len(list((ws_root / "1_QC1_Approved").glob("*.*"))),
            "upscaled": len(list((ws_root / "2_Upscaled").glob("*.*"))),
            "qc2_approved": len(list((ws_root / "2_QC2_Approved").glob("*.*"))),
            "batched": len(list((ws_root / "3_Batched_Ready").glob("Batch_*"))),
            "awaiting_submit": len(list((ws_root / "4_Uploaded_Awaiting_Submit").glob("Batch_*"))),
            "freepik_golden": fp_status.curated_count
        }

        # FTP & Credentials from Secure Local Database & Config
        ftp_cred = get_secure_credential(self.db, "ftp")
        freepik_cred = get_secure_credential(self.db, "freepik")
        ftp_meta = (ftp_cred.get("metadata") if ftp_cred else {}) or {}
        freepik_meta = (freepik_cred.get("metadata") if freepik_cred else {}) or {}

        ftp_info = {
            "host": ftp_meta.get("host") or Config.get("ftp.host", "ftp.contributor.adobestock.com"),
            "port": int(ftp_meta.get("port") or Config.get("ftp.port", 21)),
            "username": (ftp_cred.get("username") if ftp_cred else None) or Config.get("ftp.username", ""),
            "configured": bool((ftp_cred and ftp_cred.get("secret")) or (Config.get("ftp.username", "") and Config.get("ftp.password", "")))
        }

        freepik_info = {
            "username": (freepik_cred.get("username") if freepik_cred else None) or Config.get("freepik.username", ""),
            "mode": freepik_meta.get("mode") or Config.get("freepik.mode", "standby"),
            "configured": bool((freepik_cred and freepik_cred.get("secret")) or Config.get("freepik.username", ""))
        }

        # Strategy Learnings & Dynamic Blacklist
        learnings = self.dynamic.get_blacklisted_concepts()
        video_stats = self.db.get_video_stats()
        dual_breakdown = self.db.get_dual_platform_breakdown()
        strategic_intel = self.dynamic.get_strategic_intelligence()
        downloads_analytics = self.db.get_downloads_performance_analytics()
        commercial_evaluation = self.dynamic.get_commercial_download_evaluation()

        available_batches = ["ALL_APPROVED_VAULT"] + [b.name for b in (ws_root / "3_Batched_Ready").glob("Batch_*")]

        monitor = get_monitor()
        mon_state = monitor.get_state()

        raw_count = folders["raw"]
        qc1_count = folders["qc1_approved"]
        is_busy = self.is_pipeline_busy or mon_state["is_running"]
        is_finished_today = (raw_count == 0 and qc1_count == 0 and not is_busy)

        live_activity = {
            "is_busy": is_busy,
            "is_finished_today": is_finished_today,
            "stage_code": mon_state["current_stage_code"] if is_busy else ("COMPLETED_TODAY" if is_finished_today else "IDLE"),
            "stage_title_ar": mon_state["current_stage_title_ar"] if is_busy else ("🎉 خلصنا شغل النهاردة بنجاح!" if is_finished_today else "النظام في وضع الاستعداد"),
            "stage_title_en": mon_state["current_stage_title_en"] if is_busy else ("All Daily Tasks Completed" if is_finished_today else "System Standing By"),
            "file": mon_state["current_filename"],
            "file_index": mon_state["current_file_index"],
            "total_files": mon_state["total_files_in_run"],
            "progress_pct": mon_state["percentage"],
            "upload_speed": mon_state["upload_speed"],
            "daily_stats": mon_state["daily_stats"],
            "events": mon_state["recent_events"]
        }

        state_data = {
            "metrics": metrics,
            "pro_burn_target": pro_burn,
            "plus_burn_target": plus_burn,
            "freepik_gate": {
                "curated": fp_status.curated_count,
                "target": fp_status.total_target,
                "needed": fp_status.needed_count,
                "isolated": fp_status.isolated_mockup_count,
                "backgrounds": fp_status.full_bleed_bg_count,
                "ready": fp_status.is_ready_for_submission
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
            "is_busy": self.is_pipeline_busy,
            "models": {
                "image": Config.get("models.image", "nano banana pro"),
                "video": Config.get("models.video", "omni flash"),
                "upscaler": f"{validate_upscale_model(Config.get('upscayl.default_model', 'high-fidelity-4x'))} (2x Optimal 4K)"
            }
        }
        return json.dumps(state_data)

    def run_pipeline_cycle(self) -> str:
        """Runs one autonomous pipeline cycle in background."""
        if self.is_pipeline_busy:
            return json.dumps({"status": "error", "message": "Pipeline is already running!"})

        def _worker():
            self.is_pipeline_busy = True
            try:
                self.pipeline.process_raw_images()
                self.pipeline.assemble_batches_and_upload()
            finally:
                self.is_pipeline_busy = False

        threading.Thread(target=_worker, daemon=True).start()
        return json.dumps({"status": "started", "message": "Autonomous cycle launched in background."})

    def curate_freepik_golden(self) -> str:
        """Executes Freepik 150-200 incremental golden curation."""
        if self.is_pipeline_busy:
            return json.dumps({"status": "error", "message": "Cannot curate while pipeline is processing raw files."})

        try:
            res = self.curator.run_incremental_curation()
            return json.dumps({"status": "success", "result": res})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def backup_to_gdrive(self) -> str:
        """Triggers immediate Google Drive cloud backup."""
        try:
            snap = self.cloud.create_snapshot()
            return json.dumps({"status": "success", "path": str(snap)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def save_api_key(self, alias: str, key: str) -> str:
        """Saves a new Gemini / Argon API key to local SQLite database with DPAPI/AES encryption."""
        if not key or not alias:
            return json.dumps({"status": "error", "message": "Key and Alias are required."})

        # Encrypt key with local machine DPAPI / Fernet
        encrypted_key = SecurityVault.encrypt(key.strip())

        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO gemini_keys (key_alias, api_key, priority, status)
                VALUES (?, ?, 1, 'active')
                ON CONFLICT(key_alias) DO UPDATE SET 
                    api_key = excluded.api_key,
                    status = 'active';
            """, (alias.strip(), encrypted_key))

        # Reload in memory
        Config.load()
        return json.dumps({"status": "success", "message": f"API Key '{alias}' encrypted and saved locally to database."})

    # Frontend alias compatibility
    add_gemini_key = save_api_key

    def delete_api_key(self, alias: str) -> str:
        """Removes an API key from local database."""
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM gemini_keys WHERE key_alias = ?", (alias.strip(),))

        Config.load()
        return json.dumps({"status": "success", "message": f"API Key '{alias}' deleted from local vault."})

    # Frontend alias compatibility
    delete_gemini_key = delete_api_key

    def test_api_key(self, alias: str) -> str:
        """Pings Google AI Studio with this key to verify connectivity and quota."""
        import time
        raw_key = alias
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT api_key FROM gemini_keys WHERE key_alias = ?", (alias.strip(),))
            row = cursor.fetchone()
            if row:
                raw_key = row["api_key"]

        # Decrypt secret
        key_str = SecurityVault.decrypt(raw_key)

        try:
            from google import genai
            client = genai.Client(api_key=key_str)
            t0 = time.perf_counter()
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents="Test ping. Reply 'OK'."
            )
            elapsed = int((time.perf_counter() - t0) * 1000)
            self.db.clear_platform_alerts("Google AI Studio API", alias)
            return json.dumps({
                "status": "success",
                "message": f"Verified! Latency: {elapsed}ms. Response: {resp.text.strip()}"
            })
        except Exception as e:
            err_str = str(e)
            err_type = "RATE_LIMIT_429" if "429" in err_str else ("AUTH_403" if "403" in err_str else "API_ERROR")
            hint = "المفتاح تجاوز الكوتا المؤقتة أو اليومية. سيتولى النظام التدوير الآلي تلقائياً." if "429" in err_str else "المفتاح غير صالح أو تم إلغاؤه في Google AI Studio. يرجى استبداله."
            self.db.record_platform_alert("Google AI Studio API", alias, err_type, err_str, hint, severity="critical" if "403" in err_str else "warning")
            return json.dumps({
                "status": "error",
                "message": f"API Test Failed: {e}"
            })

    # Frontend alias compatibility
    test_gemini_key = test_api_key

    def save_ftp_credentials(self, username: str, password: str, host: str, port: int) -> str:
        """Encrypts and saves Adobe Stock FTP credentials in local SQLite database."""
        save_secure_credential(
            self.db,
            service="ftp",
            username=username.strip(),
            secret=password.strip(),
            metadata={"host": host.strip(), "port": int(port)}
        )

        # Update non-sensitive host/port in settings.yaml, clearing any plain password
        settings_file = PROJECT_ROOT / "config" / "settings.yaml"
        import yaml
        settings_data = {}
        if settings_file.exists():
            try:
                settings_data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
            except Exception:
                settings_data = {}

        settings_data.setdefault("ftp", {})
        settings_data["ftp"]["username"] = username.strip()
        settings_data["ftp"]["password"] = ""  # NEVER store plaintext password in YAML!
        settings_data["ftp"]["host"] = host.strip()
        settings_data["ftp"]["port"] = int(port)

        try:
            with open(settings_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(settings_data, f)
        except Exception as e:
            pass

        Config.load()
        return json.dumps({"status": "success", "message": "FTP Credentials encrypted and stored locally in database."})

    def save_freepik_credentials(self, username: str, password: str, mode: str = "standby") -> str:
        """Encrypts and saves Freepik credentials in local SQLite database."""
        save_secure_credential(
            self.db,
            service="freepik",
            username=username.strip(),
            secret=password.strip(),
            metadata={"mode": mode}
        )

        # Update non-sensitive mode in settings.yaml, clearing any plain password
        settings_file = PROJECT_ROOT / "config" / "settings.yaml"
        import yaml
        settings_data = {}
        if settings_file.exists():
            try:
                settings_data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
            except Exception:
                settings_data = {}

        settings_data.setdefault("freepik", {})
        settings_data["freepik"]["username"] = username.strip()
        settings_data["freepik"]["password"] = ""  # NEVER store plaintext password in YAML!
        settings_data["freepik"]["mode"] = mode

        try:
            with open(settings_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(settings_data, f)
        except Exception as e:
            pass

        Config.load()
        return json.dumps({"status": "success", "message": f"Freepik credentials encrypted locally (Mode: {mode.upper()})."})
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
            hint = "أدخل اسم المستخدم وكلمة المرور في إعدادات المنصة لحفظها."
            self.db.record_platform_alert(f"{platform.upper()} FTP", str(host), "MISSING_CREDENTIALS", "بيانات الاعتماد مفقودة", hint, severity="warning")
            return json.dumps({"status": "error", "message": f"Missing credentials for {platform.upper()} FTP. Please enter username and password."})

        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=10)
            ftp.login(user, pwd)
            welcome = ftp.getwelcome()
            ftp.quit()
            self.db.clear_platform_alerts(f"{platform.upper()} FTP", user)
            return json.dumps({"status": "success", "message": f"Connected to {host} successfully!\n{welcome}"})
        except Exception as e:
            err_str = str(e)
            hint = "تحقق من صحة اسم المستخدم وكلمة المرور وحالة حساب المساهم."
            self.db.record_platform_alert(f"{platform.upper()} FTP", host, "FTP_AUTH_FAILED", err_str, hint, severity="critical")
            return json.dumps({"status": "error", "message": f"Connection Failed: {e}"})
            ftp.quit()
            self.db.clear_platform_alerts(f"{platform.upper()} FTP", user)
            return json.dumps({"status": "success", "message": f"Connected to {host} successfully!\n{welcome}"})
        except Exception as e:
            err_str = str(e)
            hint = "تحقق من Contributor ID وكلمة مرور FTP المخصصة من صفحة Contributor في أدوبي ستوك وليس كلمة مرور أدوبي العادية." if "530" in err_str else "تحقق من اتصال الإنترنت والسماح لمنفذ 21."
            self.db.record_platform_alert(f"{platform.upper()} FTP", user or host, "AUTH_FAILED" if "530" in err_str else "CONNECTION_TIMEOUT", err_str, hint, severity="critical")
            return json.dumps({"status": "error", "message": f"FTP Connection to {host} failed: {e}"})

    def get_asset_thumbnail(self, filename: str) -> str:
        """Returns a base64-encoded thumbnail for the asset."""
        import base64
        import io
        from PIL import Image

        ws_root = Config.get_path("paths.workspace_root", PROJECT_ROOT / "workspace")
        candidate_paths = [
            ws_root / "2_Upscaled" / filename,
            ws_root / "2_QC2_Approved" / filename,
            ws_root / "1_QC1_Approved" / filename,
            ws_root / "0_Raw_Downloads" / filename,
            PROJECT_ROOT / "data" / "golden_freepik_150" / filename,
            Path(r"D:\images\Images to upload") / filename
        ]
        found = None
        for p in candidate_paths:
            if p.exists():
                found = p
                break

        if not found:
            return json.dumps({"status": "not_found"})

        try:
            with Image.open(found) as img:
                img.thumbnail((200, 200))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                return json.dumps({"status": "success", "data_uri": f"data:image/jpeg;base64,{b64}"})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def ask_argon_copilot(self, prompt: str, model_choice: str = "gemini-4-argon", thinking_level: str = "medium") -> str:
        """Sends user query to Argon 4 / Gemini with live memory injection and thinking settings."""
        from stockpilot.strategy.memory_context import MemoryContextBuilder
        mem = MemoryContextBuilder()
        header = mem.build_memory_prompt_header()
        full_query = f"{header}\nThinking Level Requested: {thinking_level.upper()}\nUser Query: {prompt}"

        key = self.pipeline.qc1.rotator.get_key()
        if not key:
            return json.dumps({"status": "error", "reply": "No API Key configured. Please add an API Key in Accounts & Settings."})

        target_model = model_choice if model_choice in ["gemini-4-argon", "gemini-3.8-flash", "gemini-3.5-flash-lite"] else "gemini-4-argon"

        try:
            from google import genai
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=target_model,
                contents=full_query
            )
            return json.dumps({"status": "success", "reply": resp.text, "model": target_model})
        except Exception as e:
            # Fallback to flash
            try:
                from google import genai
                client = genai.Client(api_key=key)
                resp = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=full_query
                )
                return json.dumps({"status": "success", "reply": resp.text, "model": "gemini-3.8-flash (fallback)"})
            except Exception as e2:
                return json.dumps({"status": "error", "reply": f"API Error: {e2}"})

    def export_batch_csv(self, platform: str, batch_id: str = "ALL_APPROVED_VAULT") -> str:
        """Generates platform-specific CSV (Adobe Stock comma or Freepik semicolon) dynamically."""
        from stockpilot.metadata.batch_exporter import BatchExporter
        exporter = BatchExporter()
        ws_root = Config.get_path("paths.workspace_root", PROJECT_ROOT / "workspace")
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
                cursor.execute("""
                    SELECT uuid, filename, asset_type, seo_title, seo_keywords, original_prompt, concept_id, category, model_used, status, is_freepik_150_golden
                    FROM assets 
                    WHERE batch_id = ?
                    ORDER BY id ASC
                """, (batch_id,))
            assets = [dict(r) for r in cursor.fetchall()]

        if not assets:
            # Fallback to files in 2_QC2_Approved if database was freshly initialized
            approved_files = list((ws_root / "2_QC2_Approved").glob("*.jpg")) + list((ws_root / "2_QC2_Approved").glob("*.mp4"))
            for p in approved_files:
                title_guess = p.stem.replace("_", " ")
                kws_guess = "commercial, premium, modern, stock concept, high quality, authentic"
                cat_id, cat_name = CategoryClassifier.get_adobe_category_id_and_name(
                    title=title_guess,
                    keywords=kws_guess
                )
                assets.append({
                    "filename": p.name,
                    "asset_type": "video" if p.suffix.lower() == ".mp4" else "image",
                    "seo_title": title_guess,
                    "seo_keywords": kws_guess,
                    "category": cat_id,
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "original_prompt": title_guess,
                    "model_used": "Nano Banana Pro"
                })

        if not assets:
            return json.dumps({"status": "error", "message": "No approved assets found to export."})

        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', batch_id).lower()
        if platform.lower() == "adobe":
            out_file = export_dir / f"adobe_stock_metadata_{safe_id}.csv"
            res = exporter.export_adobe_stock_csv(assets, out_file)
        else:
            out_file = export_dir / f"freepik_metadata_{safe_id}.csv"
            res = exporter.export_freepik_csv(assets, out_file)

        return json.dumps(res)

    def open_folder_in_explorer(self, folder_type: str = "exports") -> str:
        """Opens specific workspace folder in Windows File Explorer."""
        ws_root = Config.get_path("paths.workspace_root", PROJECT_ROOT / "workspace")
        mapping = {
            "exports": ws_root / "exports",
            "workspace": ws_root,
            "raw": ws_root / "0_Raw_Downloads",
            "qc2": ws_root / "2_QC2_Approved",
            "batched": ws_root / "3_Batched_Ready",
            "uploaded": ws_root / "4_Uploaded_Awaiting_Submit"
        }
        target = mapping.get(folder_type, ws_root)
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(target))
            return json.dumps({"status": "success", "opened": str(target)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def run_comprehensive_health_check(self) -> str:
        """
        Runs an end-to-end health test on all browser accounts, Adobe FTP, Freepik, and Gemini API keys.
        Records platform alerts for any failing component and clears alerts for healthy ones.
        """
        results = {
            "browser_accounts": {"tested": 0, "healthy": 0, "failed": 0},
            "adobe_ftp": {"status": "untested"},
            "freepik": {"status": "untested"},
            "gemini_api": {"tested": 0, "healthy": 0, "failed": 0}
        }

        # 1. Test Browser Accounts
        accounts = self.db.get_detailed_accounts()
        for acc in accounts:
            results["browser_accounts"]["tested"] += 1
            p_dir = acc.get("profile_dir", "Default")
            user_data = acc.get("browser", "chrome")
            roots = BrowserAccountResolver.get_standard_browser_roots()
            base_path = roots.get(user_data, roots["chrome"])
            resolved = BrowserAccountResolver.resolve_profile_info(base_path, p_dir)
            if not resolved["is_valid"]:
                results["browser_accounts"]["failed"] += 1
                self.db.update_account_health(acc["profile_name"], "error", resolved["error"], "تأكد من وجود مجلد البروفايل أو اختر بروفايل من المكتشفة.")
                self.db.record_platform_alert(
                    "Google Account",
                    acc.get("email") or acc["account_name"],
                    "PROFILE_DIR_MISSING",
                    resolved["error"],
                    "افتح المتصفح وأعد تسجيل الدخول بحساب Google أو اختر بروفايل صالح من القائمة.",
                    severity="warning"
                )
            else:
                results["browser_accounts"]["healthy"] += 1
                self.db.update_account_health(acc["profile_name"], "active", "", "")
                self.db.clear_platform_alerts("Google Account", acc.get("email") or acc["account_name"])

        # 2. Test Adobe FTP
        ftp_res = json.loads(self.test_ftp_connection("adobe"))
        results["adobe_ftp"] = ftp_res

        # 3. Test Freepik if configured
        if Config.get("freepik.username"):
            fp_res = json.loads(self.test_ftp_connection("freepik"))
            results["freepik"] = fp_res

        # 4. Test Gemini Keys
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
            "alerts": active_alerts
        })

    def resolve_alert(self, alert_id: int) -> str:
        """Marks a specific platform alert as resolved."""
        self.db.resolve_platform_alert(int(alert_id))
        return json.dumps({"status": "success", "message": f"Alert #{alert_id} resolved."})

    def clear_all_alerts(self) -> str:
        """Clears all active platform alerts."""
        with self.db.get_connection() as conn:
            conn.execute("UPDATE platform_alerts SET resolved = 1 WHERE resolved = 0;")
        return json.dumps({"status": "success", "message": "All platform alerts cleared."})

    def save_google_account(
        self,
        profile_name: Any = "",
        account_name: str = "",
        email: str = "",
        tier: str = "free",
        pool_id: str | None = None,
        browser: str = "chrome",
        profile_dir: str = "Default",
        **kwargs
    ) -> str:
        """Adds or updates a Google account in the database and local accounts_config.json."""
        if isinstance(profile_name, dict):
            data = profile_name
            profile_name = data.get("profile_name", "")
            account_name = data.get("account_name", "")
            email = data.get("email", "")
            tier = data.get("tier", "free")
            pool_id = data.get("pool_id")
            browser = data.get("browser", "chrome")
            profile_dir = data.get("profile_dir", "Default")

        if not account_name or not email:
            return json.dumps({"status": "error", "message": "Account Name and Gmail address are required."})

        limit = 50 if tier == "free" else 0
        pool = pool_id if tier in ["plus", "pro"] else None
        self.db.upsert_account(
            profile_name=profile_name,
            account_name=account_name,
            email=email,
            tier=tier,
            pool_id=pool,
            daily_limit=limit,
            browser=browser,
            profile_dir=profile_dir,
            status="active"
        )

        config_path = PROJECT_ROOT / "config" / "accounts_config.json"
        try:
            conf = {"system_settings": {}, "credit_strategy": {}, "accounts": []}
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    conf = json.load(f) or conf
            accounts = conf.get("accounts", [])
            existing_idx = next((i for i, a in enumerate(accounts) if a.get("profile_name") == profile_name), None)
            acc_entry = {
                "profile_name": profile_name,
                "account_name": account_name,
                "email": email,
                "tier": tier,
                "pool_id": pool,
                "chrome_user_data_dir": str(BrowserAccountResolver.get_standard_browser_roots().get(browser, "")),
                "profile_dir": profile_dir,
                "enabled": True
            }
            if existing_idx is not None:
                accounts[existing_idx] = acc_entry
            else:
                accounts.append(acc_entry)
            conf["accounts"] = accounts
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(conf, f, indent=2)
        except Exception as e:
            print("Error persisting account to config file:", e)

        return json.dumps({"status": "success", "message": f"Account '{account_name}' ({email}) saved successfully."})

    def delete_google_account(self, profile_name: str) -> str:
        """Deletes a Google account from the database and config."""
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM accounts WHERE profile_name = ?;", (profile_name,))

        config_path = PROJECT_ROOT / "config" / "accounts_config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                conf = json.load(f)
            conf["accounts"] = [a for a in conf.get("accounts", []) if a.get("profile_name") != profile_name]
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(conf, f, indent=2)
        except Exception as e:
            print("Error deleting account from config file:", e)

        return json.dumps({"status": "success", "message": f"Account '{profile_name}' deleted."})

    def auto_detect_browser_accounts(self) -> str:
        """Automatically scans local browsers and registers discovered accounts into the system."""
        try:
            updated = BrowserAccountResolver.sync_accounts_with_db(self.db)
            discovered = BrowserAccountResolver.discover_all_browser_profiles()
            return json.dumps({
                "status": "success",
                "message": f"Discovered {len(discovered)} profiles on machine. Synced {len(updated)} active accounts.",
                "accounts": self.db.get_detailed_accounts()
            })
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Auto-detection error: {e}"})

    def record_manual_downloads(
        self,
        filename: str,
        platform: str = "adobe",
        downloads: int = 1,
        earnings: float = 0.0
    ) -> str:
        """Manually records or adds downloads and earnings for an asset."""
        success = self.db.record_asset_downloads(filename, platform, downloads, earnings)
        if success:
            return json.dumps({
                "status": "success",
                "message": f"Successfully recorded {downloads} downloads on {platform.upper()} for '{filename}'."
            })
        else:
            return json.dumps({
                "status": "error",
                "message": f"Asset '{filename}' not found in database."
            })

    def import_sales_report_csv(self, platform: str, csv_content: str) -> str:
        """
        Parses contributor sales CSV content from Adobe Stock or Freepik and updates assets.
        Supports standard header formats:
        - Adobe Stock: Asset ID, Title, License, Media, Sales, Royalty, Date
        - Freepik: File ID, Title, Downloads, Likes, Date
        """
        import csv
        import io
        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            records = []
            for row in reader:
                lower_row = {k.strip().lower() if k else "": v for k, v in row.items()}
                ident = lower_row.get("file name") or lower_row.get("filename") or lower_row.get("asset id") or lower_row.get("file id") or lower_row.get("title") or ""
                sales_str = lower_row.get("sales") or lower_row.get("downloads") or lower_row.get("count") or "1"
                royalty_str = lower_row.get("royalty") or lower_row.get("royalties") or lower_row.get("earnings") or "0.0"
                try:
                    sales_val = int(re.sub(r'[^0-9]', '', str(sales_str)) or 1)
                except ValueError:
                    sales_val = 1
                try:
                    earn_val = float(re.sub(r'[^0-9.]', '', str(royalty_str)) or 0.0)
                except ValueError:
                    earn_val = 0.0

                if ident:
                    records.append({
                        "filename": ident,
                        "downloads": sales_val,
                        "earnings": earn_val
                    })

            res = self.db.import_contributor_sales_data(platform, records)
            return json.dumps({
                "status": "success",
                "message": f"Imported {len(records)} rows from {platform.upper()} report. Successfully matched and updated {res['updated_assets']} assets ({res['total_downloads_added']} downloads added)."
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to parse CSV report: {e}"
            })

    def simulate_sample_downloads(self) -> str:
        """Helper to populate realistic contributor sales data on approved assets for instant preview."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename FROM assets WHERE status IN ('qc2_pass', 'uploaded', 'adobe_accepted', 'downloaded');")
            assets = [r["filename"] for r in cursor.fetchall()]

        if not assets:
            return json.dumps({"status": "error", "message": "No assets found in database to simulate sales."})

        import random
        for i, fn in enumerate(assets):
            ad_dl = random.randint(4, 18) if i == 0 else random.randint(1, 8)
            fp_dl = random.randint(6, 28) if i == 0 else random.randint(2, 12)
            ad_earn = round(ad_dl * 0.99, 2)
            fp_earn = round(fp_dl * 0.12, 2)
            self.db.record_asset_downloads(fn, "adobe", ad_dl, ad_earn)
            self.db.record_asset_downloads(fn, "freepik", fp_dl, fp_earn)

        return json.dumps({
            "status": "success",
            "message": f"Simulated realistic sales on {len(assets)} assets. Dashboard updated!"
        })
