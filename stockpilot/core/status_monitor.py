"""
StockNova AI — Central Real-Time Background Status & Mission Monitor.
Thread-safe singleton tracking the exact operation, file, percentage, and 'Finished Today' state
for instantaneous live reporting to the executive dashboard.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class PipelineStatusMonitor:
    """Thread-safe status broadcaster for all pipeline stages."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> PipelineStatusMonitor:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self) -> None:
        self.is_running = False
        self.current_stage_code = "IDLE"
        self.current_stage_title_ar = "النظام في وضع الاستعداد"
        self.current_stage_title_en = "System Standing By"
        self.current_filename = "None"
        self.current_file_index = 0
        self.total_files_in_run = 0
        self.percentage = 0
        self.upload_speed_str = "Idle"
        self.is_finished_today = False
        self.last_updated_time = time.time()
        self.events: list[dict[str, Any]] = [
            {
                "time": time.strftime("%H:%M:%S"),
                "text_ar": "تم تشغيل محرك المراقبة الحية بنجاح",
                "text_en": "Live Monitoring Engine Initialized",
                "type": "info"
            }
        ]
        self.daily_stats = {
            "files_completed_today": 0,
            "credits_used_today": 0,
            "photos_approved_today": 0,
            "videos_approved_today": 0
        }

    def set_running(self, running: bool) -> None:
        with self._lock:
            self.is_running = running
            self.last_updated_time = time.time()
            if not running and self.total_files_in_run > 0 and self.current_file_index >= self.total_files_in_run:
                self.is_finished_today = True
                self.current_stage_code = "COMPLETED_TODAY"
                self.current_stage_title_ar = "🎉 خلصنا شغل النهاردة بنجاح!"
                self.current_stage_title_en = "All Daily Tasks Completed Successfully!"
                self.add_event(
                    "تم إنهاء كافة مهام اليوم بنجاح وجميع الملفات معالجة بالكامل",
                    "All daily tasks finished successfully",
                    "success"
                )

    def update_stage(
        self,
        stage_code: str,
        title_ar: str,
        title_en: str,
        filename: str = "",
        index: int = 0,
        total: int = 0,
        pct: int = 0
    ) -> None:
        with self._lock:
            self.is_running = True
            self.current_stage_code = stage_code
            self.current_stage_title_ar = title_ar
            self.current_stage_title_en = title_en
            if filename:
                self.current_filename = filename
            if total > 0:
                self.total_files_in_run = total
            if index > 0:
                self.current_file_index = index
            self.percentage = max(0, min(100, pct))
            self.last_updated_time = time.time()

    def set_upload_speed(self, speed_str: str) -> None:
        with self._lock:
            self.upload_speed_str = speed_str

    def record_completed_file(self, filename: str, asset_type: str = "image") -> None:
        with self._lock:
            self.daily_stats["files_completed_today"] += 1
            if asset_type == "video":
                self.daily_stats["videos_approved_today"] += 1
            else:
                self.daily_stats["photos_approved_today"] += 1
            self.add_event(
                f"اكتملت معالجة واعتماد الملف: {filename}",
                f"Asset completed and certified: {filename}",
                "success"
            )

    def add_event(self, text_ar: str, text_en: str, event_type: str = "info") -> None:
        evt = {
            "time": time.strftime("%H:%M:%S"),
            "text_ar": text_ar,
            "text_en": text_en,
            "type": event_type
        }
        self.events.append(evt)
        if len(self.events) > 30:
            self.events = self.events[-30:]

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "is_running": self.is_running,
                "current_stage_code": self.current_stage_code,
                "current_stage_title_ar": self.current_stage_title_ar,
                "current_stage_title_en": self.current_stage_title_en,
                "current_filename": self.current_filename,
                "current_file_index": self.current_file_index,
                "total_files_in_run": self.total_files_in_run,
                "percentage": self.percentage,
                "upload_speed": self.upload_speed_str,
                "is_finished_today": self.is_finished_today,
                "daily_stats": dict(self.daily_stats),
                "recent_events": list(self.events[-15:]),
                "last_heartbeat_timestamp": self.last_updated_time
            }


# Global accessor
def get_monitor() -> PipelineStatusMonitor:
    return PipelineStatusMonitor()
