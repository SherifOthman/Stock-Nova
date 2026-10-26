"""
Demand-driven download limiter for Google Dots.
Calculates the exact download target based on Adobe submission limits
and real-time acceptance rate, preventing disk clutter and HDD flooding.
"""

from __future__ import annotations

import math
from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("demand_limiter")


class DemandLimiter:
    """Calculates dynamic download volumes."""

    def __init__(self) -> None:
        self.db = Database()

    def calculate_target_downloads(self, current_adobe_limit: int | None = None) -> int:
        """
        Calculates:
        Target_Downloads = (Current_Adobe_Submission_Limit / Acceptance_Rate) + Safety_Buffer
        """
        if current_adobe_limit is None:
            current_adobe_limit = Config.get("qc.demand_limiter.default_adobe_limit", 30)

        acceptance_rate = self.db.get_acceptance_rate()
        # Avoid division by zero or unrealistic tiny rate
        eff_rate = max(0.20, min(1.0, acceptance_rate))

        safety_buffer = Config.get("qc.demand_limiter.safety_buffer_assets", 5)

        raw_target = (current_adobe_limit / eff_rate) + safety_buffer
        target = math.ceil(raw_target)

        logger.info(
            f"Demand calculation: Adobe Limit={current_adobe_limit}, "
            f"Acceptance Rate={eff_rate*100:.1f}%, Target Downloads={target} (buffer={safety_buffer})"
        )
        return target
