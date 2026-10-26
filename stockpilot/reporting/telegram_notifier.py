"""
Telegram and Windows Notifications Manager (Safe Daily Employee Report).
Follows strict account-safety rules:
1. Sends a comprehensive daily summary when the Digital Employee finishes its shift.
2. Includes the direct Submit URL ONLY when the Submit window is safely confirmed open
   ('submit_window_open = True').
3. If Submit is closed (or unknown), sends ONLY the clean summary report without any submit link
   so the contributor account is never exposed to unnecessary risk.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

try:
    import requests
except ImportError:
    requests = None

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("notifications")


class NotificationManager:
    """Dispatches safe Telegram messages and Windows desktop notifications."""

    def __init__(self) -> None:
        self.bot_token = str(Config.get("telegram.bot_token", "")).strip()
        self.chat_id = str(Config.get("telegram.chat_id", "")).strip()

    def reload_credentials(self) -> None:
        self.bot_token = str(Config.get("telegram.bot_token", "")).strip()
        self.chat_id = str(Config.get("telegram.chat_id", "")).strip()

    def send_telegram(self, message: str) -> bool:
        """Sends a message to the configured Telegram chat."""
        self.reload_credentials()
        if not self.bot_token or not self.chat_id:
            logger.info(f"[Telegram Simulation]:\n{message}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            if requests is not None:
                res = requests.post(url, json=payload, timeout=10)
                if res.status_code == 200:
                    logger.info("Telegram notification sent successfully.")
                    return True
                logger.error(f"Telegram API error ({res.status_code}): {res.text[:200]}")
                return False
            else:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_windows_toast(self, title: str, message: str) -> None:
        """Sends a native Windows 10/11 notification."""
        try:
            from win10toast_click import ToastNotifier

            toaster = ToastNotifier()
            toaster.show_toast(title=title, msg=message, duration=7, threaded=True)
        except Exception:
            import subprocess
            import sys

            if sys.platform != "win32":
                return
            ps_cmd = (
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
                f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                f"$textNodes = $template.GetElementsByTagName('text'); "
                f"$textNodes.Item(0).AppendChild($template.CreateTextNode('{title}')) > $null; "
                f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{message}')) > $null; "
                f"$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('StockNova AI').Show($toast);"
            )
            try:
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, check=False)
            except Exception:
                pass

    def notify_daily_shift_summary(self, summary_data: dict[str, Any]) -> bool:
        """
        Sends the end-of-shift summary report.
        Includes the Submit link ONLY if Submit is safely confirmed OPEN.
        """
        videos_done = summary_data.get("videos_ready", 0)
        images_done = summary_data.get("images_ready", 0)
        borderline = summary_data.get("borderline_count", 0)
        rejected = summary_data.get("rejected_count", 0)
        winning_model = summary_data.get("winning_video_model") or summary_data.get("active_video_model") or "omni flash"
        free_used = summary_data.get("free_credits_used", 0)
        plus_rem = summary_data.get("plus_remaining") if "plus_remaining" in summary_data else summary_data.get("plus_credits_remaining", 200)
        pro_rem = summary_data.get("pro_remaining") if "pro_remaining" in summary_data else summary_data.get("pro_credits_remaining", 1000)

        submit_is_open = bool(
            summary_data.get("submit_window_open")
            or Config.get("platforms.adobe_stock.submit_window_open", False)
        )

        lines = [
            "✅ *StockNova AI — انتهى شغل اليوم (Daily Report)*",
            "",
            f"🎬 *الفيديوهات الجاهزة (بدون صوت -an):* `{videos_done}` (الموديل الفائز: `{winning_model}`)",
            f"🖼️ *الصور الجاهزة (مكبرة 2x 4K):* `{images_done}`",
            f"🔍 *ملفات تحتاج نظرة سريعة (Borderline):* `{borderline}`",
            f"🛡️ *ملفات مستبعدة بالفلتر:* `{rejected}`",
            "",
            "💳 *حالة الكريديت اليوم:*",
            f"• الكريديت المجاني (50/يوم): تم استهلاك `{free_used}` أولاً",
            f"• المتبقي في Plus (200): `{plus_rem}`",
            f"• المتبقي في Pro (1000): `{pro_rem}`",
            "• شيتات الـ CSV منفصلة وجاهزة لـ Adobe Stock و Freepik (بدون حقن داخل الملفات).",
        ]

        if submit_is_open:
            submit_url = Config.get(
                "platforms.adobe_stock.contributor_uploads_url",
                "https://contributor.stock.adobe.com/en/uploads",
            )
            lines.extend([
                "",
                "🟢 *حالة الـ Submit حالياً مفتوحة:*",
                f"🔗 [اضغط هنا لفتح صفحة الـ Submit مباشرة]({submit_url})",
            ])
        else:
            lines.extend([
                "",
                "🔒 *حالة الـ Submit حالياً مغلقة أو في وضع التجهيز الاحتياطي (Buffer):*",
                "تم حفظ كل الملفات وشيتات الـ CSV في المخزون الجاهز لحين فتح نافذة الرفع (لم يتم إرسال رابط حفاظاً على أمان الحساب).",
            ])

        msg = "\n".join(lines)
        self.send_windows_toast(
            "StockNova AI — Daily Shift Complete",
            f"Prepared {videos_done} videos & {images_done} images.",
        )
        return self.send_telegram(msg)

    def notify_daily_summary(
        self,
        videos_ready: int = 0,
        images_ready: int = 0,
        free_credits_used: int = 0,
        pro_credits_remaining: int = 1000,
        plus_credits_remaining: int = 200,
        submit_window_open: bool = False,
        active_video_model: str = "omni flash",
    ) -> bool:
        """Convenience wrapper used by AgentCoordinator."""
        return self.notify_daily_shift_summary({
            "videos_ready": videos_ready,
            "images_ready": images_ready,
            "free_credits_used": free_credits_used,
            "pro_credits_remaining": pro_credits_remaining,
            "plus_credits_remaining": plus_credits_remaining,
            "submit_window_open": submit_window_open,
            "active_video_model": active_video_model,
        })

    def notify_batch_uploaded(
        self,
        batch_id: str,
        count: int,
        submit_open: bool | None = None,
        submit_window_open: bool | None = None,
    ) -> None:
        """Backwards-compatible batch notification respecting the safe submit-link rule."""
        flag = submit_window_open if submit_window_open is not None else submit_open
        is_open = flag if flag is not None else bool(Config.get("platforms.adobe_stock.submit_window_open", False))
        self.notify_daily_shift_summary({
            "videos_ready": 0,
            "images_ready": count,
            "submit_window_open": is_open,
        })
