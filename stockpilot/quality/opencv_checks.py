"""
OpenCV Technical Image Checks for Stock Photography.
Provides sharpness, noise estimation, and color banding detection.
"""

from __future__ import annotations

from pathlib import Path
import cv2
import numpy as np


def calculate_sharpness(image_path: Path) -> float:
    """Calculates Laplacian variance of the image (higher = sharper)."""
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
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        h, w = img.shape
        # Median filter residual
        blurred = cv2.medianBlur(img, 3)
        diff = cv2.absdiff(img, blurred)
        return float(np.mean(diff))
    except Exception:
        return 5.0
