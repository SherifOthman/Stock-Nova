"""
SEO Metadata and Adobe CSV Exporter.
Generates search-optimized Titles (<70 chars) and 45-50 Keywords using Gemini 2.5 Flash,
and exports backup CSV files per batch according to Adobe Stock guidelines.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator
from stockpilot.utils.image_utils import compress_for_gemini
from stockpilot.metadata.category_classifier import CategoryClassifier, ADOBE_CATEGORIES

logger = get_logger("seo_generator")


class SEOGenerator:
    """Generates stock titles and keywords."""

    def __init__(self) -> None:
        self.rotator = APIKeyRotator()

    def generate(self, image_path: Path, prompt_context: str = "") -> dict[str, Any]:
        """
        Generates dual-platform SEO metadata in a single API call:
        - adobe_title: strictly <70 characters, literal commercial description.
        - freepik_title: strictly <100 characters, graphic design/mockup/template oriented.
        - keywords: 45 to 50 keywords ordered by relevance.
        """
        key = self.rotator.get_key()
        stem_clean = image_path.stem[:35].replace("_", " ").strip()
        if not key:
            ad_t = f"Commercial stock media {stem_clean}"[:70]
            fp_t = f"Modern creative design background and mockup template {stem_clean}"[:100]
            return {
                "title": ad_t,
                "adobe_title": ad_t,
                "freepik_title": fp_t,
                "keywords": ["stock", "photo", "creative", "commercial", "modern", "template", "background", "design", "business", "concept"] * 5,
            }

        prompt = (
            "You are a top-tier Stock Media SEO Specialist for both Adobe Stock and Freepik.\n"
            f"Context prompt of generation: '{prompt_context}'\n\n"
            "Analyze this stock visual and generate in ONE JSON response:\n"
            "1. 'adobe_title': Literal, high-converting commercial buyer title strictly under 70 characters (NO filler words like 'photo of' or 'generative ai').\n"
            "2. 'freepik_title': Design, background, banner, and mockup-oriented title under 100 characters tailored for graphic designers on Freepik.\n"
            "3. 'keywords': Exactly 45 to 50 comma-separated high-volume commercial keywords, ordered from MOST relevant (first 10 are critical) to broad.\n\n"
            "Respond ONLY with valid JSON:\n"
            "{\n"
            '  "adobe_title": "Modern Financial Analyst Reviewing Data On Glass Screen",\n'
            '  "freepik_title": "Futuristic Data Analytics Glass Dashboard Concept With Copy Space For Business Presentation",\n'
            '  "keywords": ["analyst", "finance", "business", "data", "technology"]\n'
            "}"
        )

        compressed = compress_for_gemini(image_path)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=Config.get("gemini.model", "gemini-2.5-flash"),
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=compressed, mime_type="image/jpeg"),
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )

            data = json.loads(response.text or "{}")
            adobe_title = (data.get("adobe_title") or data.get("title") or f"Commercial stock {stem_clean}")[:70]
            freepik_title = (data.get("freepik_title") or adobe_title)[:100]
            keywords = data.get("keywords", [])
            keywords = [k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()]

            cat_id, cat_name = CategoryClassifier.get_adobe_category_id_and_name(
                title=adobe_title,
                keywords=keywords,
                explicit_category=data.get("category_id") or data.get("category"),
                concept=prompt_context,
            )

            return {
                "title": adobe_title,
                "adobe_title": adobe_title,
                "freepik_title": freepik_title,
                "keywords": keywords,
                "category_id": cat_id,
                "category_name": cat_name,
            }

        except Exception as e:
            logger.error(f"SEO generation error: {e}")
            fallback_title = f"Professional commercial visual {stem_clean}"[:70]
            fallback_fp = f"Professional creative visual and layout background {stem_clean}"[:100]
            fallback_kws = ["stock", "commercial", "background", "professional", "concept"] * 9
            cat_id, cat_name = CategoryClassifier.get_adobe_category_id_and_name(
                title=fallback_title,
                keywords=fallback_kws,
                concept=prompt_context,
            )
            return {
                "title": fallback_title,
                "adobe_title": fallback_title,
                "freepik_title": fallback_fp,
                "keywords": fallback_kws,
                "category_id": cat_id,
                "category_name": cat_name,
            }


class CSVExporter:
    """Exports Adobe Stock CSV metadata."""

    @staticmethod
    def export_batch_csv(batch_dir: Path, assets_info: list[dict[str, Any]]) -> Path:
        """
        Creates an Adobe Stock compliant CSV file inside the batch folder.
        Columns: Filename, Title, Keywords, Category, Releases
        """
        csv_path = batch_dir / "adobe_stock_metadata.csv"
        with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])

            for item in assets_info:
                fname = item["filename"]
                title = item.get("title", "")
                kws = item.get("keywords", [])
                if isinstance(kws, list):
                    kws_str = ", ".join(kws)
                else:
                    kws_str = str(kws)

                cat_id, _ = CategoryClassifier.get_adobe_category_id_and_name(
                    title=title,
                    keywords=kws_str,
                    explicit_category=item.get("category_id") or item.get("category"),
                    concept=item.get("concept_id") or ""
                )
                releases = item.get("releases", "")
                writer.writerow([fname, title, kws_str, cat_id, releases])

        logger.info(f"Generated Adobe Stock CSV backup at: {csv_path}")
        return csv_path
