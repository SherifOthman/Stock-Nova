"""
StockNova AI Adaptive Creative Prompt Generator.
Enforces strict rules:
1. Injects live historical memory (past rejections, blacklists, winners) into every prompt.
2. NO HUMANS / NO PEOPLE (no faces, hands, bodies).
3. Pure Photography (100% realistic) OR Pure Vector (100% flat illustration) - NEVER hybrid/in-between.
4. Omni Flash Video Prompts: Single continuous takes, locked camera motions, no scene cuts.
5. Target budget: 10-20 credit models only (Hard-bans 100-credit models).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.strategy.memory_context import MemoryContextBuilder

logger = get_logger("prompt_generator")


class CreativePromptGenerator:
    """Generates high-performing, compliant commercial prompts for StockNova."""

    CATEGORIES = [
        "technology", "architecture", "food_and_drink", "nature_and_landscapes",
        "textures_and_backgrounds", "business_objects", "industrial_and_science",
        "clean_energy", "abstract_3d", "minimalist_interiors", "vector_icons"
    ]

    REALISTIC_PHOTO_STYLES = [
        "commercial studio product photography, clean 8k resolution, softbox lighting, high-end catalog quality",
        "editorial architectural photography, straight lines, natural diffused daylight, sharp focus across frame",
        "macro detail photography, hyper-focused, natural light, high depth of field, crisp textures",
        "minimalist flatlay overhead shot, perfectly balanced composition, neutral background, sharp details",
        "cinematic modern interior design, golden hour sunlight streaming through window, photorealistic render",
        "industrial tech photography, clean metallic surfaces, precision engineering, dramatic rim lighting"
    ]

    VECTOR_STYLES = [
        "100% clean flat vector illustration, isolated on pure white background, minimal colors, SVG aesthetic",
        "modern infographic vector elements, geometric shapes, bold clean lines, corporate flat design",
        "seamless vector pattern, geometric modern motifs, repeatable tile, crisp vector curves",
        "minimalist line art icon set, black and white, uniform stroke weight, vector graphic style"
    ]

    OMNI_FLASH_CAMERA_MOTIONS = [
        "Single continuous take, slow smooth forward dolly pushing towards subject, stationary background, steady camera, no scene cuts, no zooms",
        "Single continuous take, slow elegant cinematic pan from left to right, locked horizon, gentle motion, no transitions, stable subject",
        "Single continuous take, locked tripod static shot, subtle natural motion of liquid/subject, constant studio lighting, no cuts, no angle changes",
        "Single continuous take, slow smooth tilt upward revealing structure, steadycam stabilization, 60fps stock footage, continuous flow"
    ]

    def __init__(self) -> None:
        self.memory_builder = MemoryContextBuilder()

    def generate_image_prompt(self, category: str | None = None, style_type: str = "realistic") -> dict[str, Any]:
        """Generates an image prompt adhering to strict memory, realism/vector, and zero-human rules."""
        blacklisted = self.memory_builder.get_blacklisted_patterns()
        cat = category or random.choice(self.CATEGORIES)

        no_humans_directive = (
            "Strictly no people, no human figures, no faces, no hands, completely unpopulated scene. "
        )

        if style_type == "vector" or cat == "vector_icons":
            style_desc = random.choice(self.VECTOR_STYLES)
            concept = f"Modern commercial {cat.replace('_', ' ')} elements"
            prompt = (
                f"{concept}, {style_desc}. {no_humans_directive}"
                "100% pure flat vector illustration, pure isolated colors, crisp edges, NO photorealism, NO shading gradient noise."
            )
            purity_type = "pure_vector"
        else:
            style_desc = random.choice(self.REALISTIC_PHOTO_STYLES)
            concept = f"Modern commercial {cat.replace('_', ' ')}"
            prompt = (
                f"{concept}, {style_desc}. {no_humans_directive}"
                "100% hyper-realistic photography, authentic textures, true-to-life reflections, NO cartoonish effects, NO painting filters."
            )
            purity_type = "pure_realistic"

        # Pivot if concept matches blacklisted memory
        for bad in blacklisted:
            if bad.lower() in prompt.lower():
                logger.info(f"Memory triggered: Pivoting away from blacklisted '{bad}'.")
                return self.generate_image_prompt(style_type="vector" if style_type == "realistic" else "realistic")

        slug = f"{cat}_{purity_type}_{random.randint(100, 999)}"
        return {
            "prompt": prompt,
            "category": cat,
            "style_type": purity_type,
            "concept_slug": slug,
            "model": Config.get("models.image", "nano banana pro"),
            "memory_header": self.memory_builder.build_memory_prompt_header()
        }

    def generate_video_prompt(self, category: str | None = None, duration_seconds: int = 10) -> dict[str, Any]:
        """
        Generates an Omni Flash video prompt (10-20 credit class):
        - Single continuous take (Strictly NO scene cuts, NO sudden zooms, NO morphing).
        - Explicit motion parameters (constant angle, continuous fluid movement).
        - Unpopulated / Zero humans.
        """
        cat = category or random.choice(self.CATEGORIES)
        motion = random.choice(self.OMNI_FLASH_CAMERA_MOTIONS)

        prompt = (
            f"Commercial 4k stock footage of modern {cat.replace('_', ' ')}. "
            f"{motion}. "
            "Strictly unpopulated, no humans, no pedestrians. "
            "Single continuous camera take, steady perspective, NO jump cuts, NO angle switches, NO sudden zooms, NO morphing. "
            "High production commercial b-roll, pristine optical quality, 60fps."
        )

        slug = f"video_{cat}_{duration_seconds}s_{random.randint(100, 999)}"
        return {
            "prompt": prompt,
            "category": cat,
            "duration_seconds": duration_seconds,
            "concept_slug": slug,
            "model": Config.get("models.video", "omni flash"),
            "max_credit_limit": Config.get("models.max_video_credit_per_generation", 20),
            "memory_header": self.memory_builder.build_memory_prompt_header()
        }
