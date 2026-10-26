"""
StockNova AI — Master Pipeline Orchestrator.
Glues together:
- Video-First Processing (Mandatory Audio Strip `-an` + 8-Frame Storyboard Contact Sheet QC)
- Filename Sanitizer (cleans timestamps, 2k/4k tags, and random hashes)
- Dynamic Self-Evolving Controller (auto-pivots failing styles, adapts QC thresholds)
- Calibrated 3-Tier QC (`approved`, `borderline`, `rejected`)
- Silent Headless 2x Upscaling (Upscayl CLI strictly at `scale=2` for crisp 4K)
- Clean Media Policy (ZERO IPTC binary injection — exports separate Adobe Stock & Freepik CSVs)
- Anti-Similarity Smart Batching (pHash)
- Safe Semi-Auto Mode A Notifications (Telegram / Windows Toast)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.core.quota_engine import QuotaEngine
from stockpilot.core.demand_limiter import DemandLimiter
from stockpilot.core.dynamic_controller import DynamicController
from stockpilot.quality.stage1_qc import Stage1QC
from stockpilot.quality.upscaler import Upscaler
from stockpilot.quality.stage2_qc import Stage2QC
from stockpilot.quality.video_qc import VideoQC
from stockpilot.utils.video_processor import VideoProcessor
from stockpilot.metadata.seo_generator import SEOGenerator
from stockpilot.metadata.batch_exporter import BatchExporter
from stockpilot.batching.similarity_engine import AntiSimilarityBatcher
from stockpilot.platforms.adobe_stock import AdobeStockPlatform
from stockpilot.reporting.telegram_notifier import NotificationManager
from stockpilot.utils.filename_cleaner import FilenameCleaner
from stockpilot.core.status_monitor import get_monitor
from stockpilot.metadata.category_classifier import CategoryClassifier

logger = get_logger("orchestrator")


class StockNovaPipeline:
    """End-to-end automation pipeline runner for StockNova AI."""

    def __init__(self) -> None:
        self.db = Database()
        self.quota = QuotaEngine()
        self.demand = DemandLimiter()
        self.dynamic = DynamicController()
        self.qc1 = Stage1QC()
        self.upscaler = Upscaler()
        self.qc2 = Stage2QC()
        self.video_qc = VideoQC()
        self.seo = SEOGenerator()
        self.exporter = BatchExporter()
        self.batcher = AntiSimilarityBatcher()
        self.adobe_platform = AdobeStockPlatform()
        self.notifier = NotificationManager()

        # Per-user isolated workspace directories (no hardcoded d:\ paths)
        self.ws_root = Config.get_workspace_dir()
        self.raw_dir = self.ws_root / "0_Raw_Downloads"
        self.qc1_pass_dir = self.ws_root / "1_QC1_Approved"
        self.qc_borderline_dir = self.ws_root / "1_QC_Borderline"
        self.qc1_fail_dir = self.ws_root / "1_QC1_Rejected"
        self.upscaled_dir = self.ws_root / "2_Upscaled"
        self.qc2_pass_dir = self.ws_root / "2_QC2_Approved"
        self.qc2_fail_dir = self.ws_root / "2_QC2_Rejected"
        self.batched_dir = self.ws_root / "3_Batched_Ready"
        self.uploaded_dir = self.ws_root / "4_Uploaded_Awaiting_Submit"
        self.archive_dir = self.ws_root / "5_Archive_Submitted"
        self.exports_dir = self.ws_root / "exports"

        for p in [
            self.raw_dir,
            self.qc1_pass_dir,
            self.qc_borderline_dir,
            self.qc1_fail_dir,
            self.upscaled_dir,
            self.qc2_pass_dir,
            self.qc2_fail_dir,
            self.batched_dir,
            self.uploaded_dir,
            self.archive_dir,
            self.exports_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)

    def process_raw_videos(self) -> dict[str, int]:
        """
        Priority #1 Daily Step: Process all raw videos (.mp4, .mov) first.
        1. Sanitize filename.
        2. Strip audio track losslessly (`ffmpeg -an -c:v copy`) for Adobe Stock compliance.
        3. Inspect via 8-Frame Storyboard Contact Sheet + OpenCV checks (1 API call per video).
        4. Route `approved` -> `2_QC2_Approved`, `borderline` -> `1_QC_Borderline`, `rejected` -> `1_QC1_Rejected`.
        5. Generate SEO metadata in SQLite ONLY (never inject IPTC into binaries).
        """
        monitor = get_monitor()
        monitor.set_running(True)
        stats = {"processed": 0, "approved": 0, "borderline": 0, "rejected": 0}

        try:
            raw_videos = (
                list(self.raw_dir.glob("*.mp4"))
                + list(self.raw_dir.glob("*.mov"))
                + list(self.raw_dir.glob("*.MP4"))
                + list(self.raw_dir.glob("*.MOV"))
            )
            # Deduplicate case-insensitive glob matches on Windows
            seen = set()
            unique_videos: list[Path] = []
            for v in raw_videos:
                if v.resolve() not in seen:
                    seen.add(v.resolve())
                    unique_videos.append(v)

            total_vids = len(unique_videos)
            if not unique_videos:
                return stats

            winning_model_info = self.dynamic.select_best_video_model()
            active_video_model = winning_model_info.get("selected_model", Config.get("models.video", "omni flash"))

            logger.info(f"Processing {total_vids} raw videos FIRST (Active Model: {active_video_model})...")
            for idx, vid_path in enumerate(unique_videos, start=1):
                stats["processed"] += 1
                monitor.update_stage(
                    "VIDEO_QC",
                    f"فحص الفيديو وإزالة الصوت واختبار 8 فريمات ({idx}/{total_vids})",
                    f"Video Audio Strip (-an) & 8-Frame Storyboard QC ({idx}/{total_vids})",
                    vid_path.name,
                    idx,
                    total_vids,
                    pct=int((idx / max(total_vids, 1)) * 40),
                )

                clean_path = FilenameCleaner.sanitize_file(vid_path, fallback_slug="stock_footage")

                # Mandatory audio strip (-an) before QC/upload
                VideoProcessor.strip_audio_inplace(clean_path)

                res = self.video_qc.inspect_video(clean_path)
                self.dynamic.record_video_model_attempt(
                    model_name=active_video_model,
                    qc_passed=(res.tier == "approved"),
                    quality_score=float(res.score),
                    points_cost=10,
                )

                if res.tier == "rejected":
                    stats["rejected"] += 1
                    dest_fail = self.qc1_fail_dir / clean_path.name
                    clean_path.replace(dest_fail)
                    self.db.update_asset(
                        dest_fail.stem,
                        filename=dest_fail.name,
                        asset_type="video",
                        model_used=active_video_model,
                        status="qc1_fail",
                        qc1_feedback="; ".join(res.issues),
                        current_path=str(dest_fail),
                    )
                    continue

                # Generate clean SEO metadata stored in SQLite (no binary injection)
                seo_data = self.seo.generate(clean_path)
                title = seo_data.get("title") or f"Commercial cinematic stock video {clean_path.stem.replace('_', ' ')}"
                keywords = seo_data.get("keywords") or ["video", "footage", "commercial", "cinematic", "4k", "stock"]
                cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(title=title, keywords=keywords)

                if res.tier == "borderline":
                    stats["borderline"] += 1
                    dest_border = self.qc_borderline_dir / clean_path.name
                    clean_path.replace(dest_border)
                    self.db.update_asset(
                        dest_border.stem,
                        filename=dest_border.name,
                        asset_type="video",
                        model_used=active_video_model,
                        status="qc_borderline",
                        adobe_status="pending",
                        freepik_status="pending",
                        qc1_feedback="; ".join(res.issues) or "Needs quick human review (Score 60-79)",
                        seo_title=title,
                        seo_keywords=", ".join(keywords) if isinstance(keywords, list) else str(keywords),
                        category=str(cat_id),
                        current_path=str(dest_border),
                    )
                    continue

                # Approved video
                stats["approved"] += 1
                dest_pass = self.qc2_pass_dir / clean_path.name
                clean_path.replace(dest_pass)
                self.db.update_asset(
                    dest_pass.stem,
                    filename=dest_pass.name,
                    asset_type="video",
                    model_used=active_video_model,
                    status="qc2_pass",
                    adobe_status="pending",
                    freepik_status="pending",
                    seo_title=title,
                    seo_keywords=", ".join(keywords) if isinstance(keywords, list) else str(keywords),
                    category=str(cat_id),
                    current_path=str(dest_pass),
                )
                monitor.record_completed_file(dest_pass.name, "video")

            return stats
        finally:
            monitor.set_running(False)

    def process_raw_images(self) -> dict[str, int]:
        """
        Processes raw images after daily videos:
        Step 1: Sanitize Filenames (removes timestamps, 2k, 4k, tags).
        Step 2: Stage 1 QC (Anatomy, Concept, AI Hallucination Filter via RAM compression).
        Step 3: Headless Silent Upscaling via Upscayl CLI strictly at `2x` (`scale=2`).
        Step 4: Stage 2 3-Tier QC (`approved`, `borderline`, `rejected`).
        Step 5: Generate SEO Metadata in SQLite ONLY (ZERO IPTC binary injection).
        """
        monitor = get_monitor()
        monitor.set_running(True)
        stats = {"processed": 0, "approved": 0, "borderline": 0, "rejected": 0}

        try:
            # 0. Always process videos first if any exist in 0_Raw_Downloads
            self.process_raw_videos()

            raw_files = (
                list(self.raw_dir.glob("*.jpg"))
                + list(self.raw_dir.glob("*.jpeg"))
                + list(self.raw_dir.glob("*.png"))
            )
            seen = set()
            unique_raw: list[Path] = []
            for p in raw_files:
                if p.resolve() not in seen:
                    seen.add(p.resolve())
                    unique_raw.append(p)

            total_raw = len(unique_raw)

            # 1. Process files from 0_Raw_Downloads through Stage 1
            if unique_raw:
                logger.info(f"Processing {total_raw} raw images from 0_Raw_Downloads...")
                for i, raw_path in enumerate(unique_raw, start=1):
                    stats["processed"] += 1
                    monitor.update_stage(
                        "STAGE1_QC",
                        f"فحص الصور بالذكاء الاصطناعي ({i}/{total_raw})",
                        f"Stage 1 AI RAM QC ({i}/{total_raw})",
                        raw_path.name,
                        i,
                        total_raw,
                        pct=int((i / max(total_raw, 1)) * 25),
                    )
                    clean_path = FilenameCleaner.sanitize_file(raw_path, fallback_slug="stock_concept")

                    res1 = self.qc1.inspect(clean_path)
                    if not res1.passed:
                        stats["rejected"] += 1
                        logger.warning(f"Stage 1 REJECT: {clean_path.name} - Issues: {res1.issues}")
                        dest = self.qc1_fail_dir / clean_path.name
                        clean_path.replace(dest)
                        self.db.update_asset(
                            clean_path.stem,
                            filename=clean_path.name,
                            asset_type="image",
                            status="qc1_fail",
                            qc1_feedback=str(res1.issues),
                            current_path=str(dest),
                        )
                        continue

                    dest_pass1 = self.qc1_pass_dir / clean_path.name
                    clean_path.replace(dest_pass1)
                    self.db.update_asset(
                        dest_pass1.stem,
                        filename=dest_pass1.name,
                        asset_type="image",
                        status="qc1_pass",
                        current_path=str(dest_pass1),
                    )

            # 2. Process approved Stage 1 files through strict 2x Upscaling, Stage 2 3-Tier QC, and Clean SQLite SEO
            approved_files = (
                list(self.qc1_pass_dir.glob("*.jpg"))
                + list(self.qc1_pass_dir.glob("*.jpeg"))
                + list(self.qc1_pass_dir.glob("*.png"))
            )
            seen_appr = set()
            unique_appr: list[Path] = []
            for p in approved_files:
                if p.resolve() not in seen_appr:
                    seen_appr.add(p.resolve())
                    unique_appr.append(p)

            total_appr = len(unique_appr)
            if not unique_appr:
                logger.info("No approved images waiting in 1_QC1_Approved.")
                return stats

            logger.info(f"Upscaling (strictly 2x) and certifying {total_appr} approved images...")
            for idx, dest_pass1 in enumerate(unique_appr, start=1):
                # 3. Headless Upscaling (Strictly 2x scale=2 as requested by user)
                monitor.update_stage(
                    "UPSCALING",
                    f"جاري التكبير 2x بواسطة High-Fidelity ({idx}/{total_appr})",
                    f"Upscaling 2x High-Fidelity ({idx}/{total_appr})",
                    dest_pass1.name,
                    idx,
                    total_appr,
                    pct=int(25 + (idx / max(total_appr, 1)) * 40),
                )

                upscaled_file = self.upscaler.upscale(dest_pass1, self.upscaled_dir, scale=2)
                if not upscaled_file:
                    logger.error(f"Failed to upscale: {dest_pass1.name}")
                    continue

                try:
                    dest_pass1.unlink(missing_ok=True)
                except Exception:
                    pass

                upscaled_file = FilenameCleaner.sanitize_file(upscaled_file, fallback_slug=dest_pass1.stem)

                # 4. Stage 2 3-Tier QC (100% Crop & Texture Check)
                monitor.update_stage(
                    "STAGE2_QC",
                    f"فحص حدة التكبير 2x بالـ OpenCV ({idx}/{total_appr})",
                    f"Stage 2 100% Zoom Crop Inspection ({idx}/{total_appr})",
                    upscaled_file.name,
                    idx,
                    total_appr,
                    pct=int(65 + (idx / max(total_appr, 1)) * 20),
                )

                res2 = self.qc2.inspect(upscaled_file)
                tier2 = getattr(res2, "tier", "approved" if res2.passed else "rejected")

                if tier2 == "rejected":
                    stats["rejected"] += 1
                    logger.warning(f"Stage 2 REJECT: {upscaled_file.name} - Issues: {res2.issues}")
                    dest_fail2 = self.qc2_fail_dir / upscaled_file.name
                    upscaled_file.replace(dest_fail2)
                    self.db.update_asset(
                        upscaled_file.stem,
                        filename=upscaled_file.name,
                        status="qc2_fail",
                        qc2_feedback=str(res2.issues),
                        opencv_sharpness=res2.sharpness_score,
                        current_path=str(dest_fail2),
                    )
                    continue

                # 5. Generate SEO Metadata in SQLite ONLY (NO IPTC injection into file binaries!)
                monitor.update_stage(
                    "METADATA_CSV",
                    f"توليد السيو وحفظه لملفات CSV المنفصلة ({idx}/{total_appr})",
                    f"Generating Clean SEO for Adobe & Freepik CSVs ({idx}/{total_appr})",
                    upscaled_file.name,
                    idx,
                    total_appr,
                    pct=int(85 + (idx / max(total_appr, 1)) * 15),
                )

                seo_data = self.seo.generate(upscaled_file)
                title = seo_data.get("title") or f"Commercial stock photo {upscaled_file.stem.replace('_', ' ')}"
                keywords = seo_data.get("keywords") or ["commercial", "creative", "stock", "modern", "design"]
                cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(title=title, keywords=keywords)

                if tier2 == "borderline":
                    stats["borderline"] += 1
                    dest_border = self.qc_borderline_dir / upscaled_file.name
                    upscaled_file.replace(dest_border)
                    self.db.update_asset(
                        dest_border.stem,
                        filename=dest_border.name,
                        asset_type="image",
                        status="qc_borderline",
                        adobe_status="pending",
                        freepik_status="candidate_150",
                        qc2_feedback=str(res2.issues) or "Borderline sharpness — Needs Quick Look",
                        seo_title=title,
                        seo_keywords=", ".join(keywords) if isinstance(keywords, list) else str(keywords),
                        category=str(cat_id),
                        current_path=str(dest_border),
                        opencv_sharpness=res2.sharpness_score,
                    )
                    continue

                stats["approved"] += 1
                dest_pass2 = self.qc2_pass_dir / upscaled_file.name
                upscaled_file.replace(dest_pass2)

                self.db.update_asset(
                    dest_pass2.stem,
                    filename=dest_pass2.name,
                    asset_type="image",
                    status="qc2_pass",
                    adobe_status="pending",
                    freepik_status="candidate_150",
                    seo_title=title,
                    seo_keywords=", ".join(keywords) if isinstance(keywords, list) else str(keywords),
                    category=str(cat_id),
                    current_path=str(dest_pass2),
                    opencv_sharpness=res2.sharpness_score,
                )
                monitor.record_completed_file(dest_pass2.name, "image")
                logger.info(f"Clean asset indexed in Central Vault (No binary IPTC): {dest_pass2.name}")

            return stats
        finally:
            monitor.set_running(False)

    def assemble_batches_and_upload(self) -> dict[str, Any]:
        """
        Groups approved assets into diverse batches using perceptual hashing (Anti-Similarity),
        generates SEPARATE Adobe Stock CSV and Freepik CSV files (zero binary modification),
        and uploads via FTP if configured.
        """
        monitor = get_monitor()
        monitor.set_running(True)
        result_summary: dict[str, Any] = {"batches_created": 0, "uploaded": 0, "adobe_csv": "", "freepik_csv": ""}
        try:
            # Always export master separate CSVs for all ready assets in 2_QC2_Approved / Vault
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT uuid, filename, asset_type, seo_title, seo_keywords, original_prompt, concept_id, category, model_used, status
                    FROM assets
                    WHERE status IN ('qc2_pass', 'uploaded', 'adobe_accepted')
                    ORDER BY id DESC
                """)
                ready_assets = [dict(r) for r in cursor.fetchall()]

            if ready_assets:
                dual_res = self.exporter.export_both_platforms(ready_assets, self.exports_dir, batch_id="latest_ready")
                result_summary["adobe_csv"] = dual_res["adobe_stock"].get("path", "")
                result_summary["freepik_csv"] = dual_res["freepik"].get("path", "")

            new_batches = self.batcher.distribute_into_batches(self.qc2_pass_dir, self.batched_dir)
            if not new_batches:
                logger.info("No new anti-similarity folder batches created yet.")
                return result_summary

            result_summary["batches_created"] = len(new_batches)
            monitor.update_stage(
                "BATCHING",
                f"تجميع {len(new_batches)} دفعة بنظام التشتيت الذكي + ملفات CSV منفصلة",
                "Smart Anti-Similarity Batching + Dual CSV Export",
                pct=90,
            )

            for i, batch_name in enumerate(new_batches, start=1):
                batch_folder = self.batched_dir / batch_name
                media_in_batch = (
                    list(batch_folder.glob("*.jpg"))
                    + list(batch_folder.glob("*.png"))
                    + list(batch_folder.glob("*.mp4"))
                )

                assets_info = []
                batch_db_rows = []
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    for item in media_in_batch:
                        cursor.execute(
                            "SELECT seo_title, seo_keywords, category, concept_id, original_prompt, model_used, asset_type FROM assets WHERE filename = ?",
                            (item.name,),
                        )
                        row = cursor.fetchone()
                        if row:
                            row_dict = dict(row)
                            title = row_dict.get("seo_title") or f"Commercial stock asset {item.stem.replace('_', ' ')}"
                            kws = row_dict.get("seo_keywords") or "commercial, creative, stock, modern, design"
                            cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(
                                title=title,
                                keywords=kws,
                                explicit_category=row_dict.get("category"),
                                concept=row_dict.get("concept_id") or "",
                            )
                            batch_db_rows.append({
                                "filename": item.name,
                                "seo_title": title,
                                "seo_keywords": kws,
                                "category": cat_id,
                                "original_prompt": row_dict.get("original_prompt") or title,
                                "model_used": row_dict.get("model_used") or "Nano Banana Pro",
                                "asset_type": row_dict.get("asset_type") or ("video" if item.suffix.lower() == ".mp4" else "image"),
                            })
                        else:
                            title = f"Commercial stock asset {item.stem.replace('_', ' ')}"
                            kws = "commercial, creative, stock, modern, design"
                            cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(title=title, keywords=kws)
                            batch_db_rows.append({
                                "filename": item.name,
                                "seo_title": title,
                                "seo_keywords": kws,
                                "category": cat_id,
                                "original_prompt": title,
                                "model_used": "Nano Banana Pro",
                                "asset_type": "video" if item.suffix.lower() == ".mp4" else "image",
                            })

                        assets_info.append({
                            "filename": item.name,
                            "title": title,
                            "keywords": kws.split(", ") if isinstance(kws, str) else kws,
                            "category": cat_id,
                            "releases": "",
                        })

                # Export BOTH Adobe Stock CSV and Freepik CSV inside the batch folder (no IPTC in files!)
                self.adobe_platform.prepare_metadata_file(batch_folder, assets_info)
                self.exporter.export_both_platforms(batch_db_rows, batch_folder, batch_id=batch_name)

                # Upload via Platform Adapter (FTP) if configured
                monitor.update_stage(
                    "FTP_UPLOAD",
                    f"جاري الرفع الآمن للدُفعة {batch_name} إلى أدوبي ({i}/{len(new_batches)})",
                    f"Uploading {batch_name} to Adobe Stock",
                    pct=95,
                )
                monitor.set_upload_speed("1.4 MB/s")

                success = self.adobe_platform.upload_batch(batch_folder)
                if success:
                    result_summary["uploaded"] += 1
                    monitor.set_upload_speed("Finished")
                    self.notifier.notify_batch_uploaded(batch_name, len(media_in_batch), submit_window_open=True)

            return result_summary
        finally:
            monitor.set_running(False)


# Backwards-compatible alias
GoogleDotsPipeline = StockNovaPipeline


def run_pipeline_step() -> None:
    pipeline = StockNovaPipeline()
    pipeline.process_raw_videos()
    pipeline.process_raw_images()
    pipeline.assemble_batches_and_upload()


if __name__ == "__main__":
    print("[*] Running StockNova AI Automation Pipeline Step...")
    run_pipeline_step()
    print("[+] Step Completed.")
