"""
Dynamic Controller, Rolling Buffer Predictor & Self-Evolving Strategy Engine for StockNova AI.
Implements:
1. Priority Credit Pacing:
   - Priority #1: Exhaust all 50 daily Free credits across all accounts first.
   - Priority #2: Consume Plus (200 monthly) credits at a fast pace (5-7 days).
   - Priority #3: Consume Pro (1000 monthly) credits over a dynamic 10-20 active-day window
     (never 30 days, so credits never expire unused if the PC is off for a few days).
2. Dynamic Rolling Image Buffer (Adobe Stock & Freepik):
   - Predicts the next upload window capacity from recent Accepted vs. Rejected counts.
   - Maintains a ready buffer (+25% surplus) waiting for Submit to open.
   - Stops image generation when the buffer is full, while Videos run EVERY day.
3. Persistent Adaptive QC Thresholds:
   - Saves updated sharpness and similarity thresholds directly to SQLite and user_settings.yaml.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger

logger = get_logger("dynamic_controller")


class DynamicController:
    """Central adaptive brain for StockNova AI."""

    def __init__(self) -> None:
        self.db = Database()
        self.strategy_file = Config.get_user_data_dir() / "creative_strategy.json"

    # =========================================================================
    # 1. DYNAMIC ACCEPTANCE METRICS
    # =========================================================================
    def get_metrics(self) -> dict[str, Any]:
        """Calculates live acceptance rates and review outcomes across platforms."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN status = 'adobe_accepted' OR adobe_status = 'accepted' THEN 1 END) as accepted,
                    COUNT(CASE WHEN status = 'adobe_rejected' OR adobe_status = 'rejected' THEN 1 END) as rejected,
                    COUNT(CASE WHEN status IN ('adobe_accepted', 'adobe_rejected') OR adobe_status IN ('accepted', 'rejected') THEN 1 END) as reviewed_total,
                    COUNT(CASE WHEN status = 'submitted' OR adobe_status = 'uploaded' THEN 1 END) as pending_review,
                    COUNT(CASE WHEN status = 'qc2_pass' AND (adobe_status = 'pending' OR adobe_status IS NULL) AND asset_type = 'image' THEN 1 END) as ready_images_adobe,
                    COUNT(CASE WHEN status = 'qc2_pass' AND (freepik_status != 'uploaded' OR freepik_status IS NULL) AND asset_type = 'image' THEN 1 END) as ready_images_freepik,
                    COUNT(CASE WHEN status = 'qc2_pass' AND asset_type = 'video' THEN 1 END) as ready_videos
                FROM assets;
            """)
            row = cursor.fetchone()
            acc = (row["accepted"] or 0) if row else 0
            rej = (row["rejected"] or 0) if row else 0
            total = (row["reviewed_total"] or 0) if row else 0
            pending = (row["pending_review"] or 0) if row else 0
            ready_img_adobe = (row["ready_images_adobe"] or 0) if row else 0
            ready_img_freepik = (row["ready_images_freepik"] or 0) if row else 0
            ready_vid = (row["ready_videos"] or 0) if row else 0

            rate = (float(acc) / float(total)) if total > 0 else 0.0

            return {
                "accepted_count": acc,
                "rejected_count": rej,
                "reviewed_total": total,
                "pending_review": pending,
                "ready_images_adobe": ready_img_adobe,
                "ready_images_freepik": ready_img_freepik,
                "ready_videos": ready_vid,
                "acceptance_rate": round(rate, 3),
                "rejection_rate": round(1.0 - rate, 3) if total > 0 else 0.0,
            }

    # =========================================================================
    # 2. PRIORITY CREDIT PACING (FREE 50 -> PLUS 200 -> PRO 1000 IN 10-20 DAYS)
    # =========================================================================
    def calculate_dynamic_daily_burn(self, pool_id: str = "pro_pool") -> int:
        """
        Calculates how many credits to burn today from a monthly pool (Plus 200 or Pro 1000):
        - Plus 200 Pool: Fast burn over 5-7 active days so it finishes quickly.
        - Pro 1000 Pool: Paced over 10-20 active days (NEVER 30 days!) so credits are never wasted
          if the user doesn't open the app on some days.
        - Adjusts dynamically based on acceptance rate:
          * High acceptance (>=70%): finishes Pro 1000 in ~10-12 active days.
          * Testing / normal: finishes Pro 1000 in ~14-15 active days.
          * High rejection (<=45% with 5+ reviews): slows to ~18-20 active days while pivoting styles.
        """
        metrics = self.get_metrics()
        rate = metrics["acceptance_rate"]
        reviewed = metrics["reviewed_total"]

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT remaining_credits, total_credits, target_consumption_days FROM credit_pools WHERE pool_id = ?",
                (pool_id,),
            )
            row = cursor.fetchone()
            if not row or row["remaining_credits"] <= 0:
                return 0

            remaining = int(row["remaining_credits"])

            if "plus" in pool_id:
                # Plus 200 pool: finish fast in 5 to 7 days (~35-40 credits/day)
                target_days = 5 if rate >= 0.70 else 7
            else:
                # Pro 1000 pool: dynamic 10 to 20 active days
                if reviewed >= 5 and rate >= 0.70:
                    target_days = 11  # Fast burn on winning streak
                elif reviewed >= 5 and rate <= 0.45:
                    target_days = 19  # Throttle while changing video niche/model
                else:
                    target_days = 14  # Balanced 2-week target so credits never expire unused

            daily_credits = max(15, int(round(remaining / max(1, target_days))))
            rec_credits = min(remaining, daily_credits)
            return {
                "pool_id": pool_id,
                "remaining_credits": remaining,
                "target_active_days": target_days,
                "recommended_daily_credits": rec_credits,
                "recommended_videos_today": max(1, rec_credits // 15),
                "pacing_mode": f"توزيع ديناميكي ({target_days} يوم عمل نشط)",
            }

    def get_daily_video_production_plan(self) -> dict[str, Any]:
        """
        Builds today's exact Video Production Plan (Priority #1 every single day):
        1. Exhaust all 50 daily Free credits across all active accounts first.
        2. Then pull today's fast-burn slice from the Plus 200 pool.
        3. Then pull today's dynamic 10-20 day slice from the Pro 1000 pool.
        4. Hard-bans any 100-credit Quality video mode.
        """
        pools = self.db.get_credit_pools_summary()
        free_rem = pools["free_daily"]["remaining_today"]
        plus_rem = pools["plus_200"]["remaining"]
        pro_rem = pools["pro_1000"]["remaining"]

        plus_burn = self.calculate_dynamic_daily_burn("plus_pool")
        pro_burn = self.calculate_dynamic_daily_burn("pro_pool")
        plus_today = plus_burn["recommended_daily_credits"] if plus_rem > 0 else 0
        pro_today = pro_burn["recommended_daily_credits"] if pro_rem > 0 else 0

        total_credits_today = free_rem + plus_today + pro_today
        avg_cost_per_video = 15
        target_videos_today = max(1, total_credits_today // avg_cost_per_video)

        return {
            "priority": 1,
            "run_even_if_submit_closed": True,
            "excluded_modes": ["quality_100_credits"],
            "free_credits_to_use_first": free_rem,
            "plus_credits_to_use_second": plus_today,
            "pro_credits_to_use_third": pro_today,
            "total_video_credits_today": total_credits_today,
            "target_videos_today": target_videos_today,
        }

    get_daily_video_credit_plan = get_daily_video_production_plan

    def select_best_video_model(self) -> dict[str, Any]:
        """
        Benchmarks eligible low-credit video models and locks onto the highest-scoring model.
        Strictly excludes any 100-credit Quality mode (points_cost >= 100).
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT model_name, points_cost, total_generated, qc_passed, adobe_accepted, adobe_rejected, status
                FROM model_performance
                WHERE asset_type = 'video'
                  AND points_cost < 100
                  AND status != 'banned_100_credit'
                ORDER BY is_winner DESC, id ASC;
            """)
            rows = [dict(r) for r in cursor.fetchall()]

        eligible = []
        best_model = Config.get("models.video", "omni flash")
        best_score = -1.0

        for r in rows:
            gen = int(r.get("total_generated") or 0)
            qc_pass = int(r.get("qc_passed") or 0)
            ad_acc = int(r.get("adobe_accepted") or 0)
            ad_rej = int(r.get("adobe_rejected") or 0)
            cost = int(r.get("points_cost") or 15)

            qc_rate = (qc_pass / gen) if gen > 0 else 0.88
            ad_total = ad_acc + ad_rej
            ad_rate = (ad_acc / ad_total) if ad_total > 0 else 0.85
            efficiency = max(0.5, (25 - cost) / 20.0)
            composite = round((qc_rate * 45.0) + (ad_rate * 45.0) + (efficiency * 10.0), 1)

            r["avg_quality_score"] = composite
            eligible.append(r)
            if composite > best_score:
                best_score = composite
                best_model = r["model_name"]

        return {
            "selected_model": best_model,
            "composite_score": best_score if best_score > 0 else 89.5,
            "banned_100_credit_mode": "quality (100 credits)",
            "all_eligible_models": eligible,
        }

    def record_video_model_attempt(
        self,
        model_name: str,
        qc_passed: bool,
        quality_score: float = 85.0,
        points_cost: int = 15,
    ) -> None:
        if points_cost >= 100 or "100" in model_name.lower():
            return
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO model_performance (model_name, asset_type, points_cost, total_generated, qc_passed, qc_failed, avg_sharpness)
                VALUES (?, 'video', ?, 1, ?, ?, ?)
                ON CONFLICT(model_name) DO UPDATE SET
                    total_generated = total_generated + 1,
                    qc_passed = qc_passed + ?,
                    qc_failed = qc_failed + ?,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    model_name.lower(),
                    int(points_cost),
                    1 if qc_passed else 0,
                    0 if qc_passed else 1,
                    float(quality_score),
                    1 if qc_passed else 0,
                    0 if qc_passed else 1,
                ),
            )

    # =========================================================================
    # 3. DYNAMIC ROLLING IMAGE BUFFER (ADOBE STOCK & FREEPIK)
    # =========================================================================
    def get_dynamic_image_buffer_plan(self) -> dict[str, Any]:
        """
        Calculates how many images to keep in the Ready Buffer and how many new images
        to produce today based on rolling Accepted vs. Rejected history.
        """
        metrics = self.get_metrics()
        acc = metrics["accepted_count"]
        rej = metrics["rejected_count"]
        rate = metrics["acceptance_rate"]
        ready_adobe = metrics["ready_images_adobe"]
        ready_freepik = metrics["ready_images_freepik"]

        base_weekly = int(Config.get("batching.default_weekly_image_prediction", 36))
        surplus_ratio = float(Config.get("batching.image_buffer_surplus_ratio", 1.25))

        if acc + rej >= 10:
            if rate >= 0.70:
                predicted_window = int(max(base_weekly, acc * 1.20))
            elif rate <= 0.45:
                predicted_window = int(max(25, base_weekly * 0.80))
            else:
                predicted_window = base_weekly
        else:
            predicted_window = base_weekly

        target_buffer_size = int(round(predicted_window * surplus_ratio))

        freepik_enabled = bool(Config.get("platforms.freepik.enabled", False))
        adobe_deficit = max(0, target_buffer_size - ready_adobe)
        freepik_deficit = max(0, target_buffer_size - ready_freepik) if freepik_enabled else 0

        images_needed_total = max(adobe_deficit, freepik_deficit)
        images_to_generate_today = min(40, images_needed_total)

        return {
            "priority": 2,
            "predicted_next_window": predicted_window,
            "target_buffer_with_surplus": target_buffer_size,
            "target_buffer_size": target_buffer_size,
            "current_ready_images": ready_adobe,
            "ready_for_adobe": ready_adobe,
            "ready_for_freepik": ready_freepik,
            "freepik_active": freepik_enabled,
            "adobe_deficit": adobe_deficit,
            "freepik_deficit": freepik_deficit,
            "buffer_is_full": images_needed_total == 0,
            "images_to_generate_today": images_to_generate_today,
            "need_to_generate": images_to_generate_today,
            "adobe_window_status": "OPEN" if Config.get("platforms.adobe_stock.submit_window_open", True) else "BUFFERING",
        }

    calculate_rolling_image_buffer = get_dynamic_image_buffer_plan

    # =========================================================================
    # 4. AUTO-PIVOT & REJECTION FEEDBACK LEARNING (ACTUALLY PERSISTED!)
    # =========================================================================
    def record_review_outcome(
        self,
        asset_uuid: str,
        outcome: str,
        rejection_reason: str = "",
        platform: str = "adobe",
    ) -> dict[str, Any]:
        """
        Logs an Accepted or Rejected outcome from Adobe Stock or Freepik,
        updates strategy_learnings, and persists adaptive QC threshold adjustments.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT uuid, concept_id, category, visual_pattern, model_used, asset_type FROM assets WHERE uuid = ? OR filename = ?",
                (asset_uuid, asset_uuid),
            )
            asset = cursor.fetchone()
            if not asset:
                return {"status": "not_found"}

            real_uuid = asset["uuid"]
            concept = asset["concept_id"] or asset["visual_pattern"] or asset["category"] or "general_commercial"
            category = asset["category"] or "general"
            model_used = asset["model_used"] or "omni flash"

            if platform.lower() == "freepik":
                fp_status = "accepted" if outcome == "accepted" else "rejected"
                cursor.execute("""
                    UPDATE assets
                    SET freepik_status = ?, freepik_rejection_notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE uuid = ?
                """, (fp_status, rejection_reason, real_uuid))
            else:
                new_status = "adobe_accepted" if outcome == "accepted" else "adobe_rejected"
                ad_status = "accepted" if outcome == "accepted" else "rejected"
                cursor.execute("""
                    UPDATE assets 
                    SET status = ?, adobe_status = ?, adobe_rejection_reason = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE uuid = ?
                """, (new_status, ad_status, rejection_reason, real_uuid))

                # Also update model_performance table for video/image model benchmarking
                if outcome == "accepted":
                    cursor.execute("UPDATE model_performance SET adobe_accepted = adobe_accepted + 1 WHERE model_name = ?;", (model_used,))
                else:
                    cursor.execute("UPDATE model_performance SET adobe_rejected = adobe_rejected + 1 WHERE model_name = ?;", (model_used,))

            cursor.execute("""
                INSERT INTO strategy_learnings (pattern_or_concept, category, total_submitted, total_accepted, total_rejected)
                VALUES (?, ?, 1, CASE WHEN ? = 'accepted' THEN 1 ELSE 0 END, CASE WHEN ? = 'rejected' THEN 1 ELSE 0 END)
                ON CONFLICT(pattern_or_concept) DO UPDATE SET
                    total_submitted = total_submitted + 1,
                    total_accepted = total_accepted + CASE WHEN excluded.total_accepted = 1 THEN 1 ELSE 0 END,
                    total_rejected = total_rejected + CASE WHEN excluded.total_rejected = 1 THEN 1 ELSE 0 END,
                    rejection_rate = CAST(total_rejected + CASE WHEN excluded.total_rejected = 1 THEN 1 ELSE 0 END AS REAL) / 
                                     CAST(total_submitted + 1 AS REAL),
                    updated_at = CURRENT_TIMESTAMP;
            """, (concept, category, outcome, outcome))

        self._evaluate_concept_for_blacklist(concept)

        adaptation_note = ""
        if outcome == "rejected" and rejection_reason:
            adaptation_note = self._adapt_qc_thresholds(rejection_reason)

        return {
            "status": "success",
            "uuid": real_uuid,
            "outcome": outcome,
            "concept": concept,
            "adaptation_note": adaptation_note,
        }

    def _evaluate_concept_for_blacklist(self, concept: str) -> None:
        """Blacklists a concept if rejection rate is >= 65% over at least 5 submissions."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT total_submitted, total_rejected, rejection_rate FROM strategy_learnings WHERE pattern_or_concept = ?",
                (concept,),
            )
            row = cursor.fetchone()
            if not row:
                return

            submitted = row["total_submitted"]
            rejected = row["total_rejected"]
            rate = row["rejection_rate"]

            if submitted >= 5 and rate >= 0.65:
                logger.warning(f"Auto-Pivot: Blacklisting '{concept}' (Rejection Rate: {rate*100:.1f}%)")
                cursor.execute("""
                    UPDATE strategy_learnings 
                    SET action_taken = 'blacklisted', reason = ?
                    WHERE pattern_or_concept = ?
                """, (f"Auto-blacklisted due to {rejected}/{submitted} rejections ({rate*100:.0f}%)", concept))
                self._add_to_creative_strategy_blacklist(concept)

    def get_blacklisted_concepts(self) -> list[str]:
        res = set()
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pattern_or_concept FROM strategy_learnings WHERE action_taken = 'blacklisted'")
            for r in cursor.fetchall():
                res.add(r["pattern_or_concept"])

        if self.strategy_file.exists():
            try:
                with open(self.strategy_file, "r", encoding="utf-8") as f:
                    strat = json.load(f)
                    for item in strat.get("blacklisted_patterns", []):
                        res.add(item)
            except Exception:
                pass
        return sorted(list(res)) if res else ["humans", "faces", "hands", "blurry_edges", "watermarks"]

    def _add_to_creative_strategy_blacklist(self, concept: str) -> None:
        strat: dict[str, Any] = {"blacklisted_patterns": []}
        if self.strategy_file.exists():
            try:
                with open(self.strategy_file, "r", encoding="utf-8") as f:
                    strat = json.load(f) or {"blacklisted_patterns": []}
            except Exception:
                strat = {"blacklisted_patterns": []}

        blacklisted = set(strat.get("blacklisted_patterns", []))
        if concept not in blacklisted:
            blacklisted.add(concept)
            strat["blacklisted_patterns"] = sorted(list(blacklisted))
            strat["last_updated"] = "auto_pivot"
            self.strategy_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.strategy_file, "w", encoding="utf-8") as f:
                json.dump(strat, f, indent=2)

    def _adapt_qc_thresholds(self, rejection_reason: str) -> str:
        """
        Dynamically adjusts QC settings in response to rejection feedback AND saves them
        permanently to both user_settings.yaml and the SQLite adaptive_rules table!
        """
        reason_lower = rejection_reason.lower()
        notes = []

        if any(w in reason_lower for w in ["quality", "artifacts", "noise", "focus", "sharpness", "blur", "technical"]):
            curr_sharpness = float(Config.get("qc.stage2.min_sharpness", 100.0))
            new_sharpness = min(155.0, round(curr_sharpness + 8.0, 1))
            Config.set("qc.stage2.min_sharpness", new_sharpness, persist=True)
            self.db.set_adaptive_rule(
                "qc.stage2.min_sharpness",
                new_sharpness,
                f"Tightened from {curr_sharpness} due to rejection: {rejection_reason}",
            )
            msg = f"Increased minimum sharpness filter from {curr_sharpness} to {new_sharpness}"
            logger.warning(msg)
            notes.append(msg)

        if any(w in reason_lower for w in ["similar", "spam", "duplicate", "variation"]):
            curr_sim = int(Config.get("batching.similarity_threshold", 12))
            new_sim = max(6, curr_sim - 2)
            Config.set("batching.similarity_threshold", new_sim, persist=True)
            self.db.set_adaptive_rule(
                "batching.similarity_threshold",
                new_sim,
                f"Tightened from {curr_sim} due to similarity rejection: {rejection_reason}",
            )
            msg = f"Tightened duplicate similarity filter from {curr_sim} to {new_sim}"
            logger.warning(msg)
            notes.append(msg)

        return "; ".join(notes)

    def get_strategic_intelligence(self) -> dict[str, Any]:
        """Provides dual-platform analytical insights, buffer status, and learned rules."""
        metrics = self.get_metrics()
        buffer_plan = self.get_dynamic_image_buffer_plan()
        video_plan = self.get_daily_video_credit_plan()
        adaptive_rules = self.db.get_all_adaptive_rules()

        adobe_insights = {
            "platform": "Adobe Stock",
            "media_types": "Videos (Priority #1 Daily) & 2x 4K Photos (Dynamic Buffer)",
            "accepted_count": metrics["accepted_count"],
            "rejected_count": metrics["rejected_count"],
            "acceptance_rate": f"{metrics['acceptance_rate']*100:.1f}%",
            "buffer_status": f"{buffer_plan['ready_for_adobe']} / {buffer_plan['target_buffer_with_surplus']} Ready in Buffer",
            "where_we_improved": [
                "Videos stripped of audio (-an) and inspected via 8-frame Storyboard Contact Sheet",
                "Photos upscaled strictly at 2x (4K) using High-Fidelity commercial weights",
                "Clean files without embedded IPTC tags + separate platform CSV export",
            ],
            "where_we_got_rejected": [
                r["reason"] for r in adaptive_rules[:3] if r.get("reason")
            ] or ["No recent rejections recorded yet — monitoring portfolio outcomes."],
            "upcoming_plan": [
                f"Daily Video Target: {video_plan['target_videos_today']} videos (Free 50s first -> Plus 200 -> Pro 1000)",
                f"Image Rolling Buffer Target: {buffer_plan['target_buffer_with_surplus']} ready images (+25% surplus)",
                "100-credit Quality video mode permanently blocked to protect credit pools",
            ],
            "trending_direction": "Sustainable technology, architectural interiors, clean culinary, commercial B-roll",
        }

        freepik_insights = {
            "platform": "Freepik",
            "media_types": "Photos (Shared Vault + Dedicated 150 Onboarding Gate)",
            "status": "Active Dual Loop" if buffer_plan["freepik_active"] else "150 Golden Gate Onboarding Mode",
            "target_gate": "150 Golden Assets (Stateful Incremental Check)",
            "where_we_improved": [
                "Dedicated Freepik 150 Gate remembers every checked file hash and skips previously reviewed photos",
                "Separate semicolon-delimited Freepik CSV generated from the same clean 2x 4K image pool",
                "Strict uniqueness (pHash) and sharpness (>= 115) enforced for manual human review",
            ],
            "where_we_got_rejected": [
                "Previously inspected suboptimal candidates automatically locked out of the 150 pool",
            ],
            "upcoming_plan": [
                "Use the dedicated Freepik 150 Gate tab to incrementally reach 150/150 approved images",
                "Reuse Adobe Stock approved images automatically on Freepik with zero duplicate generation cost",
            ],
            "trending_direction": "Isolated studio product mockups, minimalist backgrounds, commercial textures",
        }

        return {
            "adobe": adobe_insights,
            "freepik": freepik_insights,
            "video_plan": video_plan,
            "buffer_plan": buffer_plan,
            "adaptive_rules": adaptive_rules,
        }

    def get_commercial_download_evaluation(self) -> dict[str, Any]:
        analytics = self.db.get_downloads_performance_analytics()
        categories = analytics.get("downloads_by_category", [])

        winning_niches = []
        for cat in categories:
            winning_niches.append({
                "name": cat["category_name"],
                "downloads": cat["category_downloads"],
                "earnings": cat["category_earnings"],
                "recommendation": f"High commercial demand ({cat['category_downloads']} downloads) — prioritized in daily shifts.",
            })

        if not winning_niches:
            winning_niches = [
                {"name": "Clean Energy & Modern Tech", "downloads": 0, "earnings": 0.0, "recommendation": "High acceptance & commercial demand for 4K continuous B-roll and 2x photos."},
                {"name": "Minimalist Product Mockups", "downloads": 0, "earnings": 0.0, "recommendation": "Top performing category across both Adobe Stock and Freepik."},
                {"name": "Food & Healthy Culinary", "downloads": 0, "earnings": 0.0, "recommendation": "Strong buyer conversion when shot with crisp studio lighting."},
            ]

        zero_count = analytics.get("zero_download_assets_count", 0)
        zero_strategy = {
            "zero_download_count": zero_count,
            "diagnosis": "Assets with zero downloads typically need stronger buyer-intent keywords in the first 10 positions.",
            "recommended_actions": [
                "Put the most specific commercial nouns in the first 7 keywords.",
                "Leave clean copy-space in compositions for marketing designers.",
                "Prioritize winning video models with smooth continuous camera motion.",
            ],
        }

        dual_comparison = {
            "adobe": {
                "title": "Adobe Stock Portfolio",
                "downloads": analytics["adobe"]["downloads"],
                "earnings_usd": analytics["adobe"]["earnings"],
                "buyer_profile": "Agencies and video editors buying silent 4K B-roll and 2x upscaled photography.",
                "focus_advice": "Keep videos 100% silent (-an) and maintain a ready buffer of 2x upscaled images for dynamic upload windows.",
            },
            "freepik": {
                "title": "Freepik Portfolio",
                "downloads": analytics["freepik"]["downloads"],
                "earnings_usd": analytics["freepik"]["earnings"],
                "buyer_profile": "Designers needing clean isolated objects, mockups, and commercial backgrounds.",
                "focus_advice": "Complete the 150 Golden Gate batch first, then recycle all Adobe Stock photos via Freepik CSV.",
            },
        }

        return {
            "analytics": analytics,
            "winning_niches": winning_niches,
            "zero_strategy": zero_strategy,
            "dual_comparison": dual_comparison,
        }
