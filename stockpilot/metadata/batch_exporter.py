"""
StockNova AI — Multi-Platform Clean CSV Exporter (No Binary Metadata Injection).
Because the exact same prepared images are uploaded to both Adobe Stock and Freepik—which
require different metadata formats—StockNova AI NEVER embeds keywords inside image/video files.
Instead, files stay 100% clean and this module generates separate, platform-compliant CSV sheets:
1. Adobe Stock CSV (Comma-delimited: Filename,Title,Keywords,Category,Releases) — Images & Videos.
2. Freepik CSV (Semicolon-delimited: File name;Title;Keywords;Prompt;Model) — Photos.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.metadata.category_classifier import CategoryClassifier

logger = get_logger("batch_exporter")


class BatchExporter:
    """Handles dynamic metadata export and separate platform-specific CSV formatting."""

    def __init__(self) -> None:
        self.db = Database()

    @staticmethod
    def clean_freepik_keywords(keywords: list[str]) -> list[str]:
        """Removes format/filler spam banned by Freepik and ensures _ai_generated tag is included."""
        banned = {
            "image", "images", "photo", "photos", "picture", "pictures",
            "ai", "artificial intelligence", "generative", "vector", "eps", "illustration",
        }
        cleaned = []
        for kw in keywords:
            w = kw.strip().lower()
            if w and w not in banned and len(w) > 2:
                cleaned.append(kw.strip())

        if "_ai_generated" not in [k.lower() for k in cleaned]:
            cleaned.append("_ai_generated")

        return cleaned[:49]

    def export_adobe_stock_csv(self, assets: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
        """
        Exports Adobe Stock CSV format strictly conforming to Adobe Contributor Portal specifications:
        - Columns: Filename,Title,Keywords,Category,Releases
        - Delimiter: comma (,)
        - Category: Official numeric ID (1 to 21)
        - Accepts: Both Silent Videos (-an) and 2x 4K Images.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows_exported = []

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=",", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])

            for a in assets:
                filename = a.get("filename", "")
                title = (
                    a.get("seo_title")
                    or a.get("title")
                    or Path(filename).stem.replace("_", " ")
                )[:70]

                kws_raw = a.get("seo_keywords") or a.get("keywords") or "commercial, modern, stock, creative, premium"
                if isinstance(kws_raw, list):
                    kws_str = ", ".join(kws_raw[:49])
                else:
                    kws_list = [k.strip() for k in str(kws_raw).split(",") if k.strip()]
                    kws_str = ", ".join(kws_list[:49])

                cat_id, cat_name = CategoryClassifier.get_adobe_category_id_and_name(
                    title=title,
                    keywords=kws_str,
                    explicit_category=a.get("category"),
                    concept=a.get("concept_id") or "",
                )

                releases = a.get("releases", "")
                writer.writerow([filename, title, kws_str, cat_id, releases])
                rows_exported.append({
                    "filename": filename,
                    "title": title,
                    "keywords": kws_str,
                    "category": f"{cat_id} ({cat_name})",
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "releases": releases,
                    "type": a.get("asset_type", "image"),
                })

        logger.info(f"Exported {len(rows_exported)} clean rows to Adobe Stock CSV: {output_path.name}")
        return {
            "status": "success",
            "platform": "adobe",
            "path": str(output_path),
            "total_exported": len(rows_exported),
            "columns": ["Filename", "Title", "Keywords", "Category", "Releases"],
            "delimiter": ",",
            "rows": rows_exported[:40],
        }

    def export_freepik_csv(self, assets: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
        """
        Exports Freepik Contributor CSV format from the exact same clean image pool:
        - Columns: File name;Title;Keywords;Prompt;Model
        - Delimiter: semicolon (;)
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows_exported = []
        rejected_videos = []

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(["File name", "Title", "Keywords", "Prompt", "Model"])

            for a in assets:
                filename = a.get("filename", "")
                asset_type = a.get("asset_type", "image").lower()

                if asset_type == "video" or filename.lower().endswith((".mp4", ".mov")):
                    rejected_videos.append(filename)
                    continue

                title = (
                    a.get("seo_title")
                    or a.get("title")
                    or Path(filename).stem.replace("_", " ")
                )[:100]

                kws_raw = a.get("seo_keywords") or a.get("keywords") or "commercial, modern, stock, creative, premium"
                if isinstance(kws_raw, str):
                    kws_list = [k.strip() for k in kws_raw.split(",") if k.strip()]
                else:
                    kws_list = list(kws_raw)

                cleaned_kws = self.clean_freepik_keywords(kws_list)
                if len(cleaned_kws) < 5:
                    cleaned_kws.extend(["commercial", "design", "creative", "authentic", "premium"])
                kws_str = ", ".join(cleaned_kws[:49])

                prompt_text = a.get("original_prompt") or a.get("prompt") or title
                prompt_text = str(prompt_text)[:450].replace(";", ",")

                model_name = str(a.get("model_used") or "Nano Banana Pro")
                if "midjourney" in model_name.lower():
                    model_clean = "Midjourney"
                elif "imagen" in model_name.lower():
                    model_clean = "Imagen 3"
                else:
                    model_clean = "Nano Banana Pro"

                safe_title = title.replace(";", ",")
                writer.writerow([filename, safe_title, kws_str, prompt_text, model_clean])

                rows_exported.append({
                    "filename": filename,
                    "title": safe_title,
                    "keywords": kws_str,
                    "prompt": prompt_text,
                    "model": model_clean,
                    "category": "Photos (AI-Generated)",
                    "type": "image",
                })

        logger.info(f"Exported {len(rows_exported)} clean rows to Freepik CSV: {output_path.name}")
        return {
            "status": "success",
            "platform": "freepik",
            "path": str(output_path),
            "total_exported": len(rows_exported),
            "rejected_videos_count": len(rejected_videos),
            "rejected_videos": rejected_videos,
            "columns": ["File name", "Title", "Keywords", "Prompt", "Model"],
            "delimiter": ";",
            "rows": rows_exported[:40],
        }
