"""Image and Video processing utilities for Google Dots."""

from __future__ import annotations

import io
from pathlib import Path
from PIL import Image


def compress_for_gemini(image_path: Path, max_bytes: int = 150_000) -> bytes:
    """
    Compresses an image in RAM (JPEG format) to stay within max_bytes (~150KB)
    for fast, low-bandwidth Gemini Vision API inspection.
    Preserves aspect ratio and uses binary search on JPEG quality.
    """
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        # Pre-resize if enormous (e.g. 4K/8K) down to a max 1600px dimension
        max_dim = 1600
        if max(img.size) > max_dim:
            scale = max_dim / max(img.size)
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        low = 20
        high = 85
        best_bytes = b""

        while low <= high:
            mid = (low + high) // 2
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=mid, optimize=True)
            data = buf.getvalue()

            if len(data) <= max_bytes:
                best_bytes = data
                low = mid + 1
            else:
                high = mid - 1

        if not best_bytes:
            # Fallback lowest quality
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=15, optimize=True)
            best_bytes = buf.getvalue()

        return best_bytes


def extract_100_percent_center_crop(image_path: Path, crop_ratio: float = 0.25) -> Path:
    """
    Extracts a 100% resolution center crop (e.g. 25% of image area) without downscaling,
    saving it next to the file for Stage 2 QC upscaling inspection.
    """
    with Image.open(image_path) as img:
        w, h = img.size
        cw = int(w * (crop_ratio ** 0.5))
        ch = int(h * (crop_ratio ** 0.5))
        left = (w - cw) // 2
        top = (h - ch) // 2
        right = left + cw
        bottom = top + ch

        crop = img.crop((left, top, right, bottom))
        crop_path = image_path.parent / f"{image_path.stem}_crop100.jpg"
        crop.save(crop_path, format="JPEG", quality=95)
        return crop_path
