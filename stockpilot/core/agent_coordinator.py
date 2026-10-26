"""
StockNova AI — Self-Driving Daily Employee Coordinator (`AgentCoordinator`).
Operates as an autonomous digital employee ("موظف ذكي يشتغل لوحده يومياً"):
1. Checks today's shift state (`daily_shifts`) on launch.
2. Evaluates Adobe Stock & Freepik upload/submit window status and rolling buffer.
3. Resumes any unfinished raw videos or images in the workspace.
4. Executes Daily Video Plan FIRST (Free 50/day accounts -> Plus 200 -> Pro 1000 dynamic 10-20 day pace),
   strictly banning 100-credit 'Quality' modes and locking onto the highest-acceptance video model.
5. Maintains the Dynamic Rolling Image Buffer (strictly `2x` upscaling via High-Fidelity).
6. Exports separate clean CSVs for Adobe Stock & Freepik (zero binary IPTC injection),
   checkpoints strategic memory in SQLite for zero history loss across Argon accounts,
   and sends the safe daily Telegram summary.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.dynamic_controller import DynamicController
from stockpilot.core.logger import get_logger
from stockpilot.core.status_monitor import get_monitor
from stockpilot.app import StockNovaPipeline
from stockpilot.strategy.memory_context import MemoryContextBuilder
from stockpilot.reporting.telegram_notifier import NotificationManager

logger = get_logger("agent_coordinator")


class AgentCoordinator:
    """Autonomous daily shift state-machine and multi-account credit coordinator."""

    def __init__(self) -> None:
        self.db = Database()
        self.dynamic = DynamicController()
        self.pipeline = StockNovaPipeline()
        self.memory = MemoryContextBuilder()
        self.notifier = NotificationManager()
        self.auto_pilot_enabled: bool = bool(Config.get("autopilot.enabled", True))
        self.is_running_shift: bool = False
        self._last_decision_ar: str = "الموظف الذكي جاهز لبدء وردية اليوم"
        self._current_step_num: int = 0
        self._total_steps: int = 5

    def get_shift_status(self) -> dict[str, Any]:
        """Returns the live state of today's autonomous shift and credit execution plan."""
        shift = self.db.get_or_create_daily_shift()
        pools_summary = self.db.get_credit_pools_summary()
        buffer_plan = self.dynamic.calculate_rolling_image_buffer()
        video_model_plan = self.dynamic.select_best_video_model()
        next_account = self.db.select_next_account_for_credits(points_needed=10)
        primary_argon = self.db.get_primary_argon_account()

        # Check workspace queues
        ws = Config.get_workspace_dir()
        raw_videos = len(list((ws / "0_Raw_Downloads").glob("*.mp4"))) + len(list((ws / "0_Raw_Downloads").glob("*.mov")))
        raw_images = len(list((ws / "0_Raw_Downloads").glob("*.jpg"))) + len(list((ws / "0_Raw_Downloads").glob("*.png")))
        borderline_count = len(list((ws / "1_QC_Borderline").glob("*.*")))
        ready_count = len(list((ws / "2_QC2_Approved").glob("*.*")))

        # Determine next recommended autonomous action in clear Arabic
        if self.is_running_shift:
            next_action_ar = self._last_decision_ar
        elif raw_videos > 0:
            next_action_ar = f"الأولوية القصوى: فحص وإزالة الصوت من {raw_videos} فيديو خام في المجلد"
        elif pools_summary["free_daily"]["remaining_today"] > 0:
            rem_free = pools_summary["free_daily"]["remaining_today"]
            acc_Left = pools_summary["free_daily"]["accounts_remaining_today"]
            next_action_ar = f"استهلاك {rem_free} نقطة مجانية يومية متبقية عبر {acc_Left} حسابات (للفيديوهات أولاً)"
        elif raw_images > 0:
            next_action_ar = f"تكبير (2x) وفحص {raw_images} صورة خام لتغذية المخزون الجاهز"
        elif buffer_plan["need_to_generate"] > 0:
            next_action_ar = f"إنتاج {buffer_plan['need_to_generate']} صورة إضافية للوصول إلى حد الأمان الديناميكي ({buffer_plan['target_buffer_size']} صورة)"
        elif shift.get("status") == "completed":
            next_action_ar = "تم إنهاء وردية اليوم بنجاح — في انتظار المراجعة اليدوية النهائية (Submit 1%)"
        else:
            next_action_ar = "بدء الفحص اليومي لمنافذ أدوبي وفري بيك وتجهيز دفعة اليوم"

        return {
            "shift": shift,
            "auto_pilot_enabled": self.auto_pilot_enabled,
            "is_running_shift": self.is_running_shift,
            "current_step": self._current_step_num,
            "total_steps": self._total_steps,
            "next_action_ar": next_action_ar,
            "primary_argon_account": primary_argon,
            "next_credit_account": next_account,
            "credit_pools_summary": pools_summary,
            "rolling_buffer": buffer_plan,
            "video_model_plan": video_model_plan,
            "queues": {
                "raw_videos": raw_videos,
                "raw_images": raw_images,
                "borderline": borderline_count,
                "ready_vault": ready_count,
            },
        }

    def set_auto_pilot(self, enabled: bool) -> dict[str, Any]:
        """Enables or pauses the autonomous daily employee."""
        self.auto_pilot_enabled = bool(enabled)
        Config.set("autopilot.enabled", self.auto_pilot_enabled)
        return {
            "status": "success",
            "auto_pilot_enabled": self.auto_pilot_enabled,
            "message": "تم تفعيل الموظف التلقائي اليومي" if self.auto_pilot_enabled else "تم إيقاف التشغيل التلقائي مؤقتاً",
        }

    def execute_daily_shift_async(self, force: bool = False) -> dict[str, Any]:
        """Launches the autonomous 5-step daily shift in a background thread."""
        if self.is_running_shift:
            return {"status": "busy", "message": "الوردية اليومية قيد التشغيل بالفعل حالياً."}

        threading.Thread(target=self._run_shift_workflow, kwargs={"force": force}, daemon=True).start()
        return {
            "status": "started",
            "message": "بدأ الموظف الذكي تنفيذ خطة عمل اليوم تلقائياً في الخلفية.",
        }

    def run_pre_shift_ai_audit(self) -> dict[str, Any]:
        """
        Daily Pre-Shift AI Flow & System Auditor ("التقرير والتقييم الذكي اليومي قبل الشغل").
        Collects all critical telemetry (registered accounts, credit pools, queues, acceptance rate,
        production scope, stock platforms, and API keys), evaluates whether the workflow is healthy
        or has bottlenecks/errors, and optionally queries Gemini 2.5 Flash for strategic advice.
        """
        import json as _json
        from stockpilot.quality.api_key_rotator import APIKeyRotator

        pools = self.db.get_credit_pools_summary()
        prefs = self.db.get_production_preferences()
        dual = self.db.get_dual_platform_breakdown()
        video_plan = self.dynamic.select_best_video_model()
        buffer_plan = self.dynamic.calculate_rolling_image_buffer()
        acc_rate_pct = round(self.db.get_acceptance_rate() * 100, 1)
        rotator = APIKeyRotator()
        has_api_key = bool(rotator.get_key())

        ws = Config.get_workspace_dir()
        raw_videos = len(list((ws / "0_Raw_Downloads").glob("*.mp4"))) + len(list((ws / "0_Raw_Downloads").glob("*.mov")))
        raw_images = len(list((ws / "0_Raw_Downloads").glob("*.jpg"))) + len(list((ws / "0_Raw_Downloads").glob("*.png")))

        findings: list[dict[str, str]] = []
        recommendations: list[dict[str, str]] = []
        health_score = 100
        flow_status = "healthy"  # 'healthy' | 'warning' | 'action_required'

        # 1. Check Registered Accounts & Credit Pools
        total_accs = pools.get("total_registered_accounts", 0)
        free_rem = pools["free_daily"]["remaining_today"]
        plus_rem = pools["plus_200"]["remaining"]
        pro_rem = pools["pro_1000"]["remaining"]
        total_available_credits = free_rem + plus_rem + pro_rem

        if total_accs == 0:
            health_score -= 35
            flow_status = "action_required"
            findings.append({
                "severity": "critical",
                "title_en": "No Gemini / Argon Accounts Registered Yet",
                "title_ar": "لم يتم إدخال أي حسابات Gemini / Argon حتى الآن",
                "detail_en": "Credit pools accurately show 0 credits because 0 accounts are registered.",
                "detail_ar": "عدادات النقاط تعرض 0 بصدق لأنه لم يتم تسجيل أي إيميلات بعد.",
            })
            recommendations.append({
                "type": "data_missing",
                "action_en": "Add at least one Free, Plus (200), or Pro (1000) email in the Accounts Manager so the engine can calculate your real daily quota and select the #1 Primary Argon account.",
                "action_ar": "أضف حساباً واحداً على الأقل (مجاني 50 أو Plus 200 أو Pro 1000) من زر إضافة حساب ليقوم البرنامج بحساب رصيدك الفعلي وتحديد الحساب الأساسي.",
            })
        elif total_available_credits == 0:
            health_score -= 20
            flow_status = "warning"
            findings.append({
                "severity": "warning",
                "title_en": "All Registered Credit Pools Exhausted for Today",
                "title_ar": "جميع أرصدة الحسابات المسجلة مستنفدة اليوم",
                "detail_en": f"{total_accs} account(s) registered, but 0 credits remain across Free/Plus/Pro pools.",
                "detail_ar": f"تم تسجيل {total_accs} حسابات ولكن الرصيد المتاح حالياً 0 نقطة.",
            })
            recommendations.append({
                "type": "credits",
                "action_en": "Add another backup Free/Plus/Pro account or wait for the daily 50-credit reset before generating new videos.",
                "action_ar": "أضف حساباً إضافياً احتياطياً أو انتظر تجديد الـ 50 نقطة اليومية، وسيكتفي البرنامج اليوم بمعالجة الملفات الخام الموجودة.",
            })
        else:
            next_acc = self.db.select_next_account_for_credits(15)
            next_email = next_acc.get("email", "Active Account") if next_acc else "None"
            findings.append({
                "severity": "ok",
                "title_en": f"Credit Queue Ready ({total_available_credits} pts available)",
                "title_ar": f"طابور الحسابات جاهز ({total_available_credits} نقطة متاحة)",
                "detail_en": f"Next account in turn: {next_email} (Free: {free_rem}, Plus: {plus_rem}, Pro: {pro_rem}).",
                "detail_ar": f"الحساب الذي عليه الدور الآن: {next_email} (المجاني: {free_rem}، بلس: {plus_rem}، برو: {pro_rem}).",
            })

        # 2. Check Google AI Studio API Keys
        if not has_api_key:
            health_score -= 15
            if flow_status == "healthy":
                flow_status = "warning"
            findings.append({
                "severity": "warning",
                "title_en": "No Google AI Studio API Key Configured",
                "title_ar": "مفتاح Google AI Studio API غير مضاف",
                "detail_en": "Local OpenCV QC will run, but Gemini 8-frame Storyboard Vision & Dual SEO require an API key.",
                "detail_ar": "سيعمل الفحص المحلي OpenCV، لكن فحص الـ 8 لقطات بالذكاء الاصطناعي وكتابة الـ SEO يتطلبان مفتاح API.",
            })
            recommendations.append({
                "type": "config_fix",
                "action_en": "Add 1–3 free Google AI Studio API keys in Settings to enable 8-frame Storyboard Vision QC and Dual-Platform SEO.",
                "action_ar": "أضف مفتاح Google AI Studio مجاني من الإعدادات لتفعيل فحص الـ 8 لقطات وتوليد عناوين أدوبي وفري بيك تلقائياً.",
            })

        # 3. Check Production Scope & Stock Platforms
        gen_mode = prefs.get("generation_mode", "videos_only")
        adobe_en = prefs.get("adobe_enabled", True)
        freepik_en = prefs.get("freepik_enabled", True)

        if not adobe_en and not freepik_en:
            health_score -= 25
            flow_status = "action_required"
            recommendations.append({
                "type": "platform_fix",
                "action_en": "Both Adobe Stock and Freepik are disabled. Enable at least one target stock platform.",
                "action_ar": "تم إيقاف Adobe Stock و Freepik معاً — يرجى تفعيل منصة واحدة على الأقل للرفع.",
            })
        else:
            mode_label_en = "Videos Only (No Images)" if gen_mode == "videos_only" else ("Images Only" if gen_mode == "images_only" else "Videos + Images")
            mode_label_ar = "فيديوهات فقط (بدون صور)" if gen_mode == "videos_only" else ("صور فقط" if gen_mode == "images_only" else "فيديوهات + صور")
            findings.append({
                "severity": "ok",
                "title_en": f"Production Mode: {mode_label_en}",
                "title_ar": f"نظام الإنتاج المحدد: {mode_label_ar}",
                "detail_en": f"Winning video model: {video_plan.get('selected_model', 'omni flash')} (100-credit Quality excluded). Upscale locked at 2x.",
                "detail_ar": f"موديل الفيديو المختار: {video_plan.get('selected_model', 'omni flash')} (مع استبعاد باقة 100 نقطة) والتكبير مضبوط على 2x فقط.",
            })

        # 4. Check Rejection Rate & Model Performance
        adobe_rej = int(dual.get("adobe_rejected", 0) or 0)
        adobe_acc = int(dual.get("adobe_accepted", 0) or 0)
        if (adobe_acc + adobe_rej) >= 5 and acc_rate_pct < 55.0:
            health_score -= 15
            if flow_status == "healthy":
                flow_status = "warning"
            recommendations.append({
                "type": "flow_optimization",
                "action_en": f"Acceptance rate is {acc_rate_pct}%. The auditor recommends switching video benchmark to '{video_plan.get('selected_model', 'veo fast')}' and reviewing borderline clips before upload.",
                "action_ar": f"نسبة القبول الحالية {acc_rate_pct}% — ينصح المدقق الذكي بالاعتماد على موديل '{video_plan.get('selected_model', 'veo fast')}' ومراجعة الفيديوهات المتوسطة قبل الرفع.",
            })

        # Optional live Gemini AI Flow Review if API key is present
        ai_note_en = "Flow validated: Priority #1 Free 50/day -> Plus 200 -> Pro 1000 (renewal-paced), 2x upscale lock, and 100-credit exclusion are active."
        ai_note_ar = "تم التحقق من سلامة الفلو اليومي: الأولوية للـ 50 نقطة المجانية ثم Plus 200 ثم Pro 1000 وفق موعد التجديد، مع قفل التكبير على 2x واستبعاد موديل الـ 100 نقطة."

        key = rotator.get_key()
        if key:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=key)
                telemetry_snapshot = {
                    "registered_accounts": total_accs,
                    "free_daily_remaining": free_rem,
                    "plus_200_remaining": plus_rem,
                    "pro_1000_remaining": pro_rem,
                    "generation_mode": gen_mode,
                    "adobe_enabled": adobe_en,
                    "freepik_enabled": freepik_en,
                    "winning_video_model": video_plan.get("selected_model", "omni flash"),
                    "acceptance_rate_pct": acc_rate_pct,
                    "raw_videos_queued": raw_videos,
                    "raw_images_queued": raw_images,
                }
                prompt = (
                    "You are the Pre-Shift Chief AI Systems Auditor for StockNova AI (automated stock video/image pipeline).\n"
                    f"Live System Telemetry: {_json.dumps(telemetry_snapshot)}\n"
                    "Evaluate if today's workflow configuration and data are healthy or need an adjustment.\n"
                    "Respond ONLY with JSON:\n"
                    "{\n"
                    '  "ai_note_en": "1-2 sentence sharp technical assessment and recommendation in English.",\n'
                    '  "ai_note_ar": "1-2 sentence sharp technical assessment and recommendation in Arabic."\n'
                    "}"
                )
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
                )
                parsed = _json.loads(resp.text or "{}")
                if parsed.get("ai_note_en"):
                    ai_note_en = str(parsed["ai_note_en"])
                if parsed.get("ai_note_ar"):
                    ai_note_ar = str(parsed["ai_note_ar"])
            except Exception as e:
                logger.debug(f"Pre-shift AI audit fallback used: {e}")

        audit_result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "flow_status": flow_status,
            "health_score": max(10, health_score),
            "ai_note_en": ai_note_en,
            "ai_note_ar": ai_note_ar,
            "findings": findings,
            "recommendations": recommendations,
            "production_preferences": prefs,
        }
        self.db.set_adaptive_rule("audit.last_pre_shift_json", _json.dumps(audit_result, ensure_ascii=False), "Daily Pre-Shift AI Audit")
        return audit_result

    def _run_shift_workflow(self, force: bool = False) -> None:
        """Executes the 5-step daily employee loop safely, respecting dynamic account pools and production mode."""
        self.is_running_shift = True
        monitor = get_monitor()
        monitor.set_running(True)

        try:
            # Run Pre-Shift AI Audit automatically before starting work
            self.run_pre_shift_ai_audit()

            shift = self.db.get_or_create_daily_shift()
            pools = self.db.get_credit_pools_summary()
            prefs = self.db.get_production_preferences()
            buffer_plan = self.dynamic.calculate_rolling_image_buffer()
            video_plan = self.dynamic.select_best_video_model()

            videos_enabled = prefs.get("videos_enabled", True)
            images_enabled = prefs.get("images_enabled", False)

            free_videos = pools["free_daily"]["remaining_today"] // 15 if videos_enabled else 0
            plus_burn = self.dynamic.calculate_dynamic_daily_burn("plus_pool") if pools["plus_200"]["is_configured"] else {"recommended_videos_today": 0}
            pro_burn = self.dynamic.calculate_dynamic_daily_burn("pro_pool") if pools["pro_1000"]["is_configured"] else {"recommended_videos_today": 0}
            planned_videos = (
                free_videos + int(plus_burn.get("recommended_videos_today", 0)) + int(pro_burn.get("recommended_videos_today", 0))
            ) if videos_enabled else 0
            planned_images = int(buffer_plan.get("need_to_generate", 0)) if images_enabled else 0

            self.db.update_daily_shift(
                status="running",
                current_step="STEP_1_PLATFORM_SYNC",
                videos_planned=planned_videos,
                images_planned=planned_images,
                active_video_model=video_plan.get("selected_model", "omni flash"),
            )

            # STEP 1: Pre-Shift AI Audit & Memory Sync
            self._current_step_num = 1
            self._last_decision_ar = "الخطوة 1/5: التقييم الذكي اليومي للفلو والحسابات ومنافذ الرفع..."
            monitor.update_stage("SHIFT_STEP_1", self._last_decision_ar, "Step 1/5: Pre-Shift AI Audit & Pool Sync", pct=15)
            time.sleep(0.4)

            primary_acc = self.db.get_primary_argon_account()
            primary_name = (primary_acc.get("account_name") or primary_acc.get("email")) if primary_acc else "No_Account_Configured"
            self.memory.save_snapshot_after_cycle(
                account_name=primary_name,
                summary_Note=(
                    f"Shift started {datetime.now().strftime('%Y-%m-%d %H:%M')}. "
                    f"Mode: {prefs.get('generation_mode')}. "
                    f"Video Model: {video_plan.get('selected_model')} (100-credit Quality excluded)."
                ),
            )

            # STEP 2: Process Priority #1 Videos (if enabled)
            vid_stats = {"approved": 0, "borderline": 0, "rejected": 0}
            if videos_enabled:
                self._current_step_num = 2
                self._last_decision_ar = (
                    f"الخطوة 2/5: معالجة الفيديوهات بالموديل الفائز ({video_plan.get('selected_model')}) "
                    f"وفحص الـ 8 لقطات وإزالة الصوت (-an)..."
                )
                self.db.update_daily_shift(current_step="STEP_2_VIDEOS_FIRST")
                vid_stats = self.pipeline.process_raw_videos()

            # STEP 3: Process Raw & Approved Images at Strictly 2x Upscale (ONLY if images_enabled)
            img_stats = {"approved": 0, "borderline": 0, "rejected": 0}
            if images_enabled:
                self._current_step_num = 3
                self._last_decision_ar = "الخطوة 3/5: تكبير الصور 2x فقط (High-Fidelity) وفحص الجودة..."
                self.db.update_daily_shift(current_step="STEP_3_IMAGES_2X_BUFFER")
                img_stats = self.pipeline.process_raw_images()

            # STEP 4: Export Separate Clean CSVs (Adobe Stock & Freepik) + Batch Upload
            self._current_step_num = 4
            self._last_decision_ar = "الخطوة 4/5: تصدير ملفات CSV منفصلة للمنصات المفعلة..."
            self.db.update_daily_shift(current_step="STEP_4_DUAL_CSV_AND_UPLOAD")
            self.pipeline.assemble_batches_and_upload()

            # STEP 5: Update Shift Ledger & Send Safe Daily Report
            self._current_step_num = 5
            self._last_decision_ar = "الخطوة 5/5: تحديث ذاكرة الموظف الذكي وإصدار ملخص نهاية الوردية..."
            updated_pools = self.db.get_credit_pools_summary()

            videos_done = int(shift.get("videos_completed", 0)) + int(vid_stats.get("approved", 0))
            images_done = int(shift.get("images_completed", 0)) + int(img_stats.get("approved", 0))

            notes_ar = (
                f"تم إنجاز وردية اليوم: {videos_done} فيديو معتمد، {images_done} صورة معتمدة (2x)، "
                f"و {vid_stats.get('borderline', 0) + img_stats.get('borderline', 0)} ملف في قائمة المراجعة."
            )
            self.db.update_daily_shift(
                status="completed",
                current_step="COMPLETED_SHIFT",
                videos_completed=videos_done,
                images_completed=images_done,
                free_credits_spent=updated_pools["free_daily"]["used_today"],
                plus_credits_spent=updated_pools["plus_monthly"]["used_today"],
                pro_credits_spent=updated_pools["pro_monthly"]["used_today"],
                notes=notes_ar,
            )

            submit_open = bool(buffer_plan.get("adobe_window_status") == "OPEN")
            self.notifier.notify_daily_summary(
                videos_ready=videos_done,
                images_ready=images_done,
                free_credits_used=updated_pools["free_daily"]["used_today"],
                pro_credits_remaining=updated_pools["pro_monthly"]["remaining"],
                plus_credits_remaining=updated_pools["plus_monthly"]["remaining"],
                submit_window_open=submit_open,
                active_video_model=video_plan.get("selected_model", "omni flash"),
            )

            self._last_decision_ar = f"✅ اكتملت وردية اليوم بنجاح! ({notes_ar})"
            monitor.update_stage("COMPLETED_TODAY", self._last_decision_ar, "Daily Shift Completed", pct=100)

        except Exception as e:
            logger.error(f"Error during autonomous daily shift: {e}")
            self._last_decision_ar = f"⚠️ توقفت الوردية مؤقتاً: {e}"
            self.db.update_daily_shift(status="paused", notes=str(e))
        finally:
            self.is_running_shift = False
            monitor.set_running(False)


# Global singleton coordinator
_coordinator_instance: AgentCoordinator | None = None


def get_coordinator() -> AgentCoordinator:
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = AgentCoordinator()
    return _coordinator_instance
