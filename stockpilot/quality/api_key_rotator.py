"""
Gemini 2.5 Flash API Key Rotator.
Handles automatic switching across multiple API keys upon HTTP 429 / Rate Limit.
"""

from __future__ import annotations

import threading
import time
from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger

logger = get_logger("api_key_rotator")


class APIKeyRotator:
    """Thread-safe key rotator."""

    _instance: APIKeyRotator | None = None
    _lock = threading.Lock()

    def __new__(cls) -> APIKeyRotator:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._keys = []
                cls._instance._current_idx = 0
                cls._instance._cooldowns = {}
                cls._instance._load_keys()
            return cls._instance

    def _load_keys(self) -> None:
        self._keys = Config.get_api_keys()
        if not self._keys:
            # Check environment variable as fallback
            import os
            env_key = os.getenv("GEMINI_API_KEY")
            if env_key:
                self._keys = [env_key]

        logger.info(f"Loaded {len(self._keys)} Gemini API keys into rotator.")

    def get_key(self) -> str | None:
        """Retrieves the next valid, non-cooldown API key."""
        with self._lock:
            if not self._keys:
                return None

            now = time.time()
            # Try finding an active key
            for _ in range(len(self._keys)):
                key = self._keys[self._current_idx]
                cooldown_until = self._cooldowns.get(key, 0)

                if now >= cooldown_until:
                    # Key is valid
                    return key

                # Advance to next key
                self._current_idx = (self._current_idx + 1) % len(self._keys)

            # If all are cooling down, return the one with shortest remaining wait
            logger.warning("All Gemini API keys are temporarily on cooldown.")
            return self._keys[self._current_idx]

    def report_rate_limit(self, key: str, cooldown_seconds: int = 60) -> None:
        """Marks a key as rate-limited (HTTP 429) and rotates immediately."""
        with self._lock:
            self._cooldowns[key] = time.time() + cooldown_seconds
            logger.warning(f"Key ...{key[-6:] if len(key)>6 else key} rate-limited. Cooldown for {cooldown_seconds}s.")
            if self._keys:
                self._current_idx = (self._current_idx + 1) % len(self._keys)
