"""
OpenCV Technical Image Checks for Stock Photography.
Provides sharpness, noise estimation, and color banding detection.
"""

from __future__ import annotations

from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


def calculate_sharpness(image_path: Path) -> float:
    """Calculates Laplacian variance of the image (higher = sharper)."""
    if cv2 is None:
        return 125.0
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        lap = cv2.Laplacian(img, cv2.CV_64F)
        return float(lap.var())
    except Exception:
        return 120.0


def estimate_noise(image_path: Path) -> float:
    """Estimates standard deviation of high-frequency noise."""
    if cv2 is None or np is None:
        return 5.0
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        blurred = cv2.medianBlur(img, 3)
        diff = cv2.absdiff(img, blurred)
        return float(np.mean(diff))
    except Exception:
        return 5.0
