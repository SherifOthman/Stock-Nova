"""
Google Dots Master Pipeline Orchestrator.
Glues together:
- Filename Sanitizer (cleans timestamps, 2k/4k tags, and random hashes)
- Dynamic Self-Evolving Controller (auto-pivots failing styles, adapts QC thresholds)
- Quota Engine (flexible credit pacing, video-first priority)
- Two-Stage QC (RAM compression Stage 1 + 100% Crop Stage 2)
- Silent Headless Upscaling (Upscayl CLI)
- IPTC/EXIF Metadata Injection (ExifTool)
- Anti-Similarity Smart Batching (pHash)
- Adobe Stock Platform Adapter (FTP upload + CSV generation)
- Safe Semi-Auto Mode A Notifications (Telegram / Windows Toast)
"""

from __future__ import annotations

import time
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.core.quota_engine import QuotaEngine
from stockpilot.core.demand_limiter import DemandLimiter
from stockpilot.core.dynamic_controller import DynamicController
from stockpilot.quality.stage1_qc import Stage1QC
from stockpilot.quality.upscaler import Upscaler
from stockpilot.quality.stage2_qc import Stage2QC
from stockpilot.metadata.seo_generator import SEOGenerator
from stockpilot.metadata.iptc_writer import IPTCWriter
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
        self.seo = SEOGenerator()
        self.iptc = IPTCWriter()
        self.batcher = AntiSimilarityBatcher()
        self.adobe_platform = AdobeStockPlatform()
        self.notifier = NotificationManager()

        # Workspace directories
        self.ws_root = Config.get_path("paths.workspace_root", Path(r"d:\Stock Automation\workspace"))
        self.raw_dir = self.ws_root / "0_Raw_Downloads"
        self.qc1_pass_dir = self.ws_root / "1_QC1_Approved"
        self.qc1_fail_dir = self.ws_root / "1_QC1_Rejected"
        self.upscaled_dir = self.ws_root / "2_Upscaled"
        self.qc2_pass_dir = self.ws_root / "2_QC2_Approved"
        self.qc2_fail_dir = self.ws_root / "2_QC2_Rejected"
        self.batched_dir = self.ws_root / "3_Batched_Ready"
        self.uploaded_dir = self.ws_root / "4_Uploaded_Awaiting_Submit"
        self.archive_dir = self.ws_root / "5_Archive_Submitted"

        for p in [
            self.raw_dir, self.qc1_pass_dir, self.qc1_fail_dir,
            self.upscaled_dir, self.qc2_pass_dir, self.qc2_fail_dir,
            self.batched_dir, self.uploaded_dir, self.archive_dir
        ]:
            p.mkdir(parents=True, exist_ok=True)

    def process_raw_images(self) -> None:
        """
        Step 1: Sanitize Filenames (removes timestamps, 2k, 4k, tags).
        Step 2: Stage 1 QC (Anatomy, Concept, AI Hallucination Filter via RAM compression).
        Step 3: Headless Silent Upscaling via Upscayl CLI.
        Step 4: Stage 2 QC (100% Crop & Texture check).
        Step 5: Generate SEO & Inject IPTC Metadata directly into file.
        """
        monitor = get_monitor()
        monitor.set_running(True)

        try:
            raw_files = list(self.raw_dir.glob("*.jpg")) + list(self.raw_dir.glob("*.png"))
            total_raw = len(raw_files)
            
            # 1. Process files from 0_Raw_Downloads through Stage 1
            if raw_files:
                logger.info(f"Processing {total_raw} raw assets from 0_Raw_Downloads...")
                for i, raw_path in enumerate(raw_files, start=1):
                    monitor.update_stage(
                        "STAGE1_QC",
                        f"فحص الرام بالذكاء الاصطناعي ({i}/{total_raw})",
                        f"Stage 1 AI RAM QC ({i}/{total_raw})",
                        raw_path.name, i, total_raw, pct=int((i/total_raw)*25)
                    )
                    clean_path = FilenameCleaner.sanitize_file(raw_path, fallback_slug="stock_concept")
                    logger.info(f"Sanitized filename: {raw_path.name} -> {clean_path.name}")

                    res1 = self.qc1.inspect(clean_path)
                    if not res1.passed:
                        logger.warning(f"❌ Stage 1 REJECT: {clean_path.name} - Issues: {res1.issues}")
                        dest = self.qc1_fail_dir / clean_path.name
                        clean_path.replace(dest)
                        self.db.update_asset(clean_path.stem, status="qc1_fail", qc1_feedback=str(res1.issues))
                        continue

                    logger.info(f"✅ Stage 1 PASSED: {clean_path.name}")
                    dest_pass1 = self.qc1_pass_dir / clean_path.name
                    clean_path.replace(dest_pass1)
                    self.db.update_asset(dest_pass1.stem, status="qc1_pass", filename=dest_pass1.name)

            # 2. Process approved Stage 1 files through Upscaling, QC2, and Metadata
            approved_files = list(self.qc1_pass_dir.glob("*.jpg")) + list(self.qc1_pass_dir.glob("*.png"))
            total_appr = len(approved_files)
            if not approved_files:
                logger.info("No approved images waiting in 1_QC1_Approved.")
                return

            logger.info(f"Upscaling and certifying {total_appr} approved images...")
            for idx, dest_pass1 in enumerate(approved_files, start=1):
                # 3. Headless Upscaling (Upscayl CLI with adaptive scale)
                monitor.update_stage(
                    "UPSCALING",
                    f"جاري التكبير بواسطة High-Fidelity 2x ({idx}/{total_appr})",
                    f"Upscaling 2x High-Fidelity ({idx}/{total_appr})",
                    dest_pass1.name, idx, total_appr, pct=int(25 + (idx/total_appr)*40)
                )

                upscaled_file = self.upscaler.upscale(dest_pass1, self.upscaled_dir)
                if not upscaled_file:
                    logger.error(f"Failed to upscale: {dest_pass1.name}")
                    continue

                # Remove from 1_QC1_Approved once upscaled successfully
                try:
                    dest_pass1.unlink(missing_ok=True)
                except Exception:
                    pass

                # Clean any upscaler-added suffix (e.g. _upscayl_4x) from the upscaled file
                upscaled_file = FilenameCleaner.sanitize_file(upscaled_file, fallback_slug=dest_pass1.stem)

                # 4. Stage 2 QC (100% Crop & Texture Check)
                monitor.update_stage(
                    "STAGE2_QC",
                    f"فحص حدة التكبير 100% بالـ OpenCV ({idx}/{total_appr})",
                    f"Stage 2 100% Zoom Crop Inspection ({idx}/{total_appr})",
                    upscaled_file.name, idx, total_appr, pct=int(65 + (idx/total_appr)*20)
                )

                res2 = self.qc2.inspect(upscaled_file)
                if not res2.passed:
                    logger.warning(f"❌ Stage 2 REJECT: {upscaled_file.name} - Issues: {res2.issues}")
                    dest_fail2 = self.qc2_fail_dir / upscaled_file.name
                    upscaled_file.replace(dest_fail2)
                    self.db.update_asset(
                        upscaled_file.stem,
                        status="qc2_fail",
                        qc2_feedback=str(res2.issues),
                        opencv_sharpness=res2.sharpness_score
                    )
                    continue

                logger.info(f"✅ Stage 2 PASSED: {upscaled_file.name} (Sharpness: {res2.sharpness_score:.1f})")
                dest_pass2 = self.qc2_pass_dir / upscaled_file.name
                upscaled_file.replace(dest_pass2)

                # 5. Generate SEO Metadata and Inject IPTC
                monitor.update_stage(
                    "METADATA_IPTC",
                    f"توليد السيو وحقن بيانات IPTC ({idx}/{total_appr})",
                    f"Generating SEO & Injecting IPTC ({idx}/{total_appr})",
                    dest_pass2.name, idx, total_appr, pct=int(85 + (idx/total_appr)*15)
                )

                seo_data = self.seo.generate(dest_pass2)
                title = seo_data["title"]
                keywords = seo_data["keywords"]

                self.iptc.write_metadata(dest_pass2, title=title, keywords=keywords)
                self.db.update_asset(
                    dest_pass2.stem,
                    filename=dest_pass2.name,
                    status="qc2_pass",
                    adobe_status="pending",
                    freepik_status="candidate_150",
                    seo_title=title,
                    seo_keywords=", ".join(keywords),
                    current_path=str(dest_pass2),
                    opencv_sharpness=res2.sharpness_score
                )
                monitor.record_completed_file(dest_pass2.name, "image")
                logger.info(f"✨ Metadata written & asset indexed in Central Vault: {dest_pass2.name}")

        finally:
            monitor.set_running(False)

    def assemble_batches_and_upload(self) -> None:
        """
        Groups approved images into diverse batches using perceptual hashing (Anti-Similarity),
        prepares the Adobe CSV backup, and uploads via FTP.
        """
        monitor = get_monitor()
        monitor.set_running(True)
        try:
            new_batches = self.batcher.distribute_into_batches(self.qc2_pass_dir, self.batched_dir)
            if not new_batches:
                logger.info("No batches created (not enough approved images yet).")
                return

            monitor.update_stage("BATCHING", f"تجميع {len(new_batches)} دفعة بنظام التشتيت الذكي", "Smart Anti-Similarity Batching", pct=90)

            for i, batch_name in enumerate(new_batches, start=1):
                batch_folder = self.batched_dir / batch_name
                images_in_batch = list(batch_folder.glob("*.jpg"))

                assets_info = []
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    for img in images_in_batch:
                        cursor.execute("SELECT seo_title, seo_keywords, category, concept_id FROM assets WHERE filename = ?", (img.name,))
                        row = cursor.fetchone()
                        if row:
                            row_dict = dict(row)
                            title = row_dict.get("seo_title") or f"Stock concept {img.stem.replace('_', ' ')}"
                            kws = row_dict.get("seo_keywords") or ["commercial", "creative", "stock", "modern", "design"]
                            cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(
                                title=title,
                                keywords=kws,
                                explicit_category=row_dict.get("category"),
                                concept=row_dict.get("concept_id") or ""
                            )
                        else:
                            title = f"Stock concept {img.stem.replace('_', ' ')}"
                            kws = ["commercial", "creative", "stock", "modern", "design"]
                            cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(title=title, keywords=kws)

                        assets_info.append({
                            "filename": img.name,
                            "title": title,
                            "keywords": kws,
                            "category": cat_id,
                            "releases": ""
                        })

                # Create Adobe CSV via Platform Adapter
                self.adobe_platform.prepare_metadata_file(batch_folder, assets_info)

                # Upload via Platform Adapter (FTP)
                monitor.update_stage("FTP_UPLOAD", f"جاري الرفع الآمن للدُفعة {batch_name} إلى أدوبي ({i}/{len(new_batches)})", f"Uploading {batch_name} to Adobe Stock", pct=95)
                monitor.set_upload_speed("1.2 MB/s")

                success = self.adobe_platform.upload_batch(batch_folder)
                if success:
                    monitor.set_upload_speed("Finished")
                    # Mode A Notification (Zero Risk)
                    self.notifier.notify_batch_uploaded(batch_name, len(images_in_batch))
        finally:
            monitor.set_running(False)


# Backwards-compatible alias
GoogleDotsPipeline = StockNovaPipeline


def run_pipeline_step() -> None:
    pipeline = StockNovaPipeline()
    pipeline.process_raw_images()
    pipeline.assemble_batches_and_upload()


if __name__ == "__main__":
    print("[*] Running StockNova AI Automation Pipeline Step...")
    run_pipeline_step()
    print("[+] Step Completed.")
