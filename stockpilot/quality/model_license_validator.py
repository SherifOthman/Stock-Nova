"""
License and Model Policy Validator for Upscayl.
Enforces strict commercial compliance for Stock Photography:
- BANS non-commercial community models (UltraSharp, Remacri) to prevent legal/TOS copyright traps.
- PERMITS only 100% commercially licensed models:
  1. 'high-fidelity-4x' (4xHFA2k / Real-ESRGAN Compact - Permissive / OpenModelDB approved for commercial)
  2. 'upscayl-standard-4x' (Real-ESRGAN - BSD 3-Clause permissive commercial license)
  3. 'upscayl-lite-4x' (Fast commercial fallback)
"""

from __future__ import annotations

from stockpilot.core.logger import get_logger

logger = get_logger("model_license")

COMMERCIALLY_PERMITTED_MODELS = {
    "high-fidelity-4x": {
        "license": "Permissive (Real-ESRGAN Compact / 4xHFA2k)",
        "commercial_use": True,
        "quality_rating": "5/5 (Best for stock photography - preserves natural texture)",
        "default": True
    },
    "upscayl-standard-4x": {
        "license": "BSD 3-Clause (Real-ESRGAN original)",
        "commercial_use": True,
        "quality_rating": "4.5/5 (Sharp and reliable)",
        "default": False
    },
    "upscayl-lite-4x": {
        "license": "BSD 3-Clause",
        "commercial_use": True,
        "quality_rating": "4/5 (Fast lightweight)",
        "default": False
    }
}

STRICTLY_BANNED_NON_COMMERCIAL_MODELS = {
    "ultrasharp-4x": "Created by Kim2091 with CC-BY-NC 4.0 (Non-Commercial). BANNED from stock sales.",
    "remacri-4x": "Created by Foolhardy with non-commercial / restricted terms. BANNED from stock sales."
}


def validate_upscale_model(model_name: str) -> str:
    """
    Validates model name for commercial safety.
    If a non-commercial or banned model is requested, automatically overrides to 'high-fidelity-4x'.
    """
    clean_name = model_name.lower().strip()

    if clean_name in STRICTLY_BANNED_NON_COMMERCIAL_MODELS:
        reason = STRICTLY_BANNED_NON_COMMERCIAL_MODELS[clean_name]
        logger.warning(f"🚨 LEGAL WARNING: Model '{clean_name}' is NON-COMMERCIAL ({reason}). Auto-overriding to 'high-fidelity-4x'.")
        return "high-fidelity-4x"

    if clean_name in COMMERCIALLY_PERMITTED_MODELS:
        return clean_name

    logger.warning(f"Unknown model '{model_name}'. Defaulting to safe commercial model 'high-fidelity-4x'.")
    return "high-fidelity-4x"
