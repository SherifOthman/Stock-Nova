"""
StockNova AI — Multi-Platform Batch Exporter & CSV Studio.
Generates compliant metadata CSV files for Adobe Stock and Freepik according to their exact official specifications:
- Adobe Stock: Comma-delimited, Header (Filename,Title,Keywords,Category,Releases), Title (<70 chars), 45-50 Keywords, Category (Numeric ID 1-21 strictly). Accepts Images & Videos.
- Freepik: Semicolon-delimited, Header (File name;Title;Keywords;Prompt;Model), Title (<100 chars), Keywords (5-50 tags + _ai_generated tag, no spam), AI Prompt & Model. Photos ONLY (Videos blocked).
Dynamic Late-Binding: Vault assets remain platform-agnostic until the user chooses target platform at export time!
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.logger import get_logger
from stockpilot.metadata.category_classifier import CategoryClassifier, ADOBE_CATEGORIES

logger = get_logger("batch_exporter")
PROJECT_ROOT = Path(r"d:\Stock Automation")


class BatchExporter:
    """Handles dynamic metadata export and platform-specific CSV formatting."""

    def __init__(self) -> None:
        self.db = Database()

    @staticmethod
    def clean_freepik_keywords(keywords: list[str]) -> list[str]:
        """Removes format/filler spam banned by Freepik and ensures _ai_generated tag is included."""
        banned = {
            "image", "images", "photo", "photos", "picture", "pictures",
            "ai", "artificial intelligence", "generative", "vector", "eps", "illustration"
        }
        cleaned = []
        for kw in keywords:
            w = kw.strip().lower()
            if w and w not in banned and len(w) > 2:
                cleaned.append(kw.strip())
        
        # Freepik official standard: include _ai_generated tag for AI-created assets
        if "_ai_generated" not in [k.lower() for k in cleaned]:
            cleaned.append("_ai_generated")

        return cleaned[:50]

    def export_adobe_stock_csv(self, assets: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
        """
        Exports Adobe Stock CSV format strictly conforming to Adobe Contributor Portal specifications:
        - Columns: Filename,Title,Keywords,Category,Releases
        - Delimiter: comma (,)
        - Category: Must be official numeric ID (1 to 21)
        - Accepts: Images AND Videos.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows_exported = []

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=",", quoting=csv.QUOTE_MINIMAL)
            # Official Adobe Stock Header
            writer.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])

            for a in assets:
                filename = a.get("filename", "")
                title = (a.get("seo_title") or a.get("title") or filename.replace("_", " ").replace(".jpg", "").replace(".mp4", ""))[:70]
                
                # Keywords
                kws_raw = a.get("seo_keywords") or a.get("keywords") or "commercial, modern, stock, creative, premium"
                if isinstance(kws_raw, list):
                    kws_str = ", ".join(kws_raw[:50])
                else:
                    kws_str = str(kws_raw)

                # Strict Category Classification: Numeric ID (1 to 21)
                cat_id, cat_name = CategoryClassifier.get_adobe_category_id_and_name(
                    title=title,
                    keywords=kws_str,
                    explicit_category=a.get("category"),
                    concept=a.get("concept_id") or ""
                )

                # Releases column: optional, leave empty if not applicable
                releases = a.get("releases", "")

                row = [filename, title, kws_str, cat_id, releases]
                writer.writerow(row)
                rows_exported.append({
                    "filename": filename,
                    "title": title,
                    "keywords": kws_str,
                    "category": f"{cat_id} ({cat_name})",
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "releases": releases,
                    "type": a.get("asset_type", "image")
                })

        logger.info(f"Exported {len(rows_exported)} rows to Adobe Stock CSV: {output_path.name}")
        return {
            "status": "success",
            "platform": "adobe",
            "path": str(output_path),
            "total_exported": len(rows_exported),
            "columns": ["Filename", "Title", "Keywords", "Category", "Releases"],
            "delimiter": ",",
            "rows": rows_exported[:30]  # Preview top 30
        }

    def export_freepik_csv(self, assets: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
        """
        Exports Freepik Contributor CSV format:
        - Columns: File name;Title;Keywords;Prompt;Model
        - Delimiter: semicolon (;)
        - Keywords: Comma-separated with _ai_generated tag, banned filler tags stripped
        - Rule: Photos ONLY (Videos strictly blocked from Freepik CSV).
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows_exported = []
        rejected_videos = []

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            # Official Freepik AI Contributor Header
            writer.writerow(["File name", "Title", "Keywords", "Prompt", "Model"])

            for a in assets:
                filename = a.get("filename", "")
                asset_type = a.get("asset_type", "image").lower()

                # STRICT RULE: Freepik contributor does not take stock video in this mode
                if asset_type == "video" or filename.lower().endswith((".mp4", ".mov")):
                    rejected_videos.append(filename)
                    continue

                title = a.get("seo_title") or a.get("title") or filename.replace("_", " ").replace(".jpg", "").replace(".png", "")
                title = title[:100]

                # Keywords: Clean banned tags and inject _ai_generated
                kws_raw = a.get("seo_keywords") or a.get("keywords") or "commercial, modern, stock, creative, premium"
                if isinstance(kws_raw, str):
                    kws_list = [k.strip() for k in kws_raw.split(",") if k.strip()]
                else:
                    kws_list = list(kws_raw)

                cleaned_kws = self.clean_freepik_keywords(kws_list)
                if len(cleaned_kws) < 5:
                    cleaned_kws.extend(["commercial", "design", "creative", "authentic", "premium"])
                kws_str = ", ".join(cleaned_kws[:50])

                # AI Prompt and Model for Freepik AI contributor requirements
                prompt_text = a.get("prompt") or a.get("prompt_context") or title
                prompt_text = str(prompt_text)[:450].replace(";", ",")
                
                model_name = a.get("model_used") or "Nano Banana Pro"
                if "midjourney" in model_name.lower():
                    model_clean = "Midjourney"
                elif "imagen" in model_name.lower():
                    model_clean = "Imagen 3"
                elif "dall" in model_name.lower():
                    model_clean = "DALL-E 3"
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
                    "type": "image"
                })

        logger.info(f"Exported {len(rows_exported)} rows to Freepik CSV: {output_path.name} (Excluded {len(rejected_videos)} videos)")
        return {
            "status": "success",
            "platform": "freepik",
            "path": str(output_path),
            "total_exported": len(rows_exported),
            "rejected_videos_count": len(rejected_videos),
            "rejected_videos": rejected_videos,
            "columns": ["File name", "Title", "Keywords", "Prompt", "Model"],
            "delimiter": ";",
            "rows": rows_exported[:30]  # Preview top 30
        }
