"""
Telegram and Windows Notifications Manager (Mode A Safe Semi-Auto Alert).
Sends instant actionable links and weekly summaries when FTP upload is ready,
allowing 10-second manual submission with 0% ban risk.
"""

from __future__ import annotations

import requests
from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("notifications")


class NotificationManager:
    """Dispatches Telegram messages and Windows toasts."""

    def __init__(self) -> None:
        self.bot_token = Config.get("telegram.bot_token", "")
        self.chat_id = Config.get("telegram.chat_id", "")

    def send_telegram(self, message: str) -> bool:
        """Sends a message to the configured Telegram chat."""
        if not self.bot_token or not self.chat_id:
            logger.info(f"[Telegram Alert Simulation]:\n{message}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }

        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                logger.info("Telegram notification sent successfully.")
                return True
            else:
                logger.error(f"Telegram API error ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_windows_toast(self, title: str, message: str) -> None:
        """Sends a native Windows 10/11 notification."""
        try:
            from win10toast_click import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(
                title=title,
                msg=message,
                duration=7,
                threaded=True
            )
        except Exception:
            # Fallback PowerShell toast if win10toast is not available
            import subprocess
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

    def notify_batch_uploaded(self, batch_id: str, count: int) -> None:
        """Sends the Mode A prompt for manual review & submit."""
        title = "🚀 Adobe Stock Batch Ready!"
        msg = (
            f"🎉 *{batch_id}* ({count} assets) has been uploaded via FTP to Adobe Stock!\n\n"
            "👉 *Action Needed (Mode A - 10s Safe Submit):*\n"
            "1. Open Adobe Stock Contributor Portal: https://contributor.stock.adobe.com/uploads\n"
            "2. Verify files arrived and IPTC metadata is populated.\n"
            "3. Ensure *'Created using generative AI'* is checked.\n"
            "4. Click **Submit** safely!"
        )
        self.send_telegram(msg)
        self.send_windows_toast(title, f"{batch_id} ({count} assets) uploaded to Adobe Stock. Click to submit!")
