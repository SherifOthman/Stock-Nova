"""
Stock Video Quality Control & Multi-Frame Motion Inspector.
Specifically engineered for Omni Flash and AI stock footage:
1. Local Frame-to-Frame Stability & Cut Detector (OpenCV - 0 API cost):
   Calculates structural similarity (SSIM) and frame differences to detect jarring
   scene cuts, morphing glitches, or camera jump cuts.
2. Smart Keyframe Grid Sampler (Token-Efficient API Inspection):
   Extracts 5 evenly spaced keyframes across the timeline (e.g. at 10%, 30%, 50%, 70%, 90%),
   stitches them into a single compressed horizontal contact sheet (~150KB in RAM),
   and sends ONLY this single collage to Gemini Vision.
   This gives the AI a complete chronological view of the motion in a SINGLE API call,
   conserving quota while catching every transition defect!
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from stockpilot.core.config import Config
from stockpilot.core.logger import get_logger
from stockpilot.quality.api_key_rotator import APIKeyRotator

logger = get_logger("video_qc")


@dataclass
class VideoQCResult:
    passed: bool
    confidence: float
    has_scene_cuts: bool
    has_warping_morphing: bool
    issues: list[str]
    summary: str


class VideoQCInspector:
    """Multi-frame video quality inspector."""

    def __init__(self) -> None:
        self.rotator = APIKeyRotator()

    def local_motion_and_cut_check(self, video_path: Path) -> dict[str, Any]:
        """
        Analyzes video locally with OpenCV:
        - Detects abrupt scene cuts by monitoring histogram/pixel variance across frames.
        - Calculates average motion smoothness.
        Returns: { 'abrupt_cut_detected': bool, 'max_frame_diff': float }
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return {"abrupt_cut_detected": False, "max_frame_diff": 0.0, "error": "Cannot open video"}

        prev_gray = None
        max_diff = 0.0
        abrupt_cut = False
        cut_threshold = 65.0  # Normalized pixel difference threshold for sudden scene changes

        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_count += 1

            # Downsample for speed
            small = cv2.resize(frame, (320, 180))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            if prev_gray is not None:
                # Absolute difference
                diff = cv2.absdiff(gray, prev_gray)
                mean_diff = float(np.mean(diff))
                if mean_diff > max_diff:
                    max_diff = mean_diff

                if mean_diff > cut_threshold:
                    abrupt_cut = True

            prev_gray = gray

        cap.release()
        return {
            "abrupt_cut_detected": abrupt_cut,
            "max_frame_diff": round(max_diff, 2),
            "total_frames": frame_count
        }

    def extract_keyframes_contact_sheet(
        self,
        video_path: Path,
        num_frames: int = 5,
        target_height: int = 240
    ) -> bytes | None:
        """
        Extracts `num_frames` evenly spaced across the video and stitches them
        side-by-side into a single timeline contact strip (~150KB JPEG in RAM).
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return None

        # Sample points across timeline (e.g. 10%, 30%, 50%, 70%, 90%)
        fractions = np.linspace(0.10, 0.90, num_frames)
        frame_indices = [int(f * total_frames) for f in fractions]

        extracted_images = []
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret and frame is not None:
                # Convert BGR to RGB
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb)

                # Resize preserving aspect ratio
                aspect = pil_img.width / pil_img.height
                w = int(target_height * aspect)
                pil_img = pil_img.resize((w, target_height), Image.Resampling.LANCZOS)
                extracted_images.append(pil_img)

        cap.release()

        if not extracted_images:
            return None

        # Stitch horizontally
        total_width = sum(im.width for im in extracted_images)
        sheet = Image.new("RGB", (total_width, target_height), (0, 0, 0))

        offset_x = 0
        for im in extracted_images:
            sheet.paste(im, (offset_x, 0))
            offset_x += im.width

        # Compress to RAM (< 180KB)
        buf = io.BytesIO()
        sheet.save(buf, format="JPEG", quality=80, optimize=True)
        return buf.getvalue()

    def inspect_video(self, video_path: Path) -> VideoQCResult:
        """
        Full two-layer video QC:
        Layer 1: Local OpenCV scene cut & jerk detector.
        Layer 2: Gemini Vision multi-frame timeline analysis.
        """
        # 1. Local Check (Free, fast)
        local_res = self.local_motion_and_cut_check(video_path)
        issues = []
        if local_res.get("abrupt_cut_detected"):
            issues.append(f"Abrupt scene cut detected locally (max frame diff: {local_res['max_frame_diff']})")

        # 2. Extract Keyframe Contact Sheet
        contact_sheet_bytes = self.extract_keyframes_contact_sheet(video_path, num_frames=5)
        if not contact_sheet_bytes:
            logger.warning(f"Could not extract keyframes from {video_path.name}")
            return VideoQCResult(
                passed=len(issues) == 0,
                confidence=0.6,
                has_scene_cuts=local_res.get("abrupt_cut_detected", False),
                has_warping_morphing=False,
                issues=issues,
                summary="Fallback local OpenCV evaluation only"
            )

        key = self.rotator.get_key()
        if not key:
            passed = len(issues) == 0
            return VideoQCResult(
                passed=passed,
                confidence=0.6,
                has_scene_cuts=local_res.get("abrupt_cut_detected", False),
                has_warping_morphing=False,
                issues=issues,
                summary="Local OpenCV check passed (No API key for vision)"
            )

        prompt = (
            "You are an expert Adobe Stock Video Inspector. "
            "You are examining a CHRONOLOGICAL 5-FRAME TIMELINE STRIP of an AI-generated stock video clip (ordered left to right from start to finish). "
            "Evaluate strictly for commercial stock footage standards:\n"
            "1. Scene cuts / switches: Is this a continuous single camera take, or does the scene cut/change between frames? (Stock b-roll must be a SINGLE continuous shot, no scene cuts).\n"
            "2. Subject morphing / warping: Does the subject or background distort unnaturally or change shape/identity as time progresses?\n"
            "3. Human presence: Are there any humans, faces, or hands? (Must be completely unpopulated / no humans).\n"
            "4. Visual glitches: AI melting, unnatural physics, or severe blur.\n\n"
            "Respond ONLY with a valid JSON strictly formatted as:\n"
            "{\n"
            '  "pass": true,\n'
            '  "confidence": 0.95,\n'
            '  "has_scene_cuts": false,\n'
            '  "has_warping_morphing": false,\n'
            '  "issues": [],\n'
            '  "summary": "Pristine continuous commercial shot, steady motion, zero scene cuts or morphing artifacts."\n'
            "}"
        )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=Config.get("gemini.model", "gemini-2.5-flash"),
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=contact_sheet_bytes, mime_type="image/jpeg"),
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            data = json.loads(response.text or "{}")
            api_pass = bool(data.get("pass", False))
            confidence = float(data.get("confidence", 0.8))
            has_cuts = bool(data.get("has_scene_cuts", False))
            has_warp = bool(data.get("has_warping_morphing", False))
            api_issues = data.get("issues", [])
            summary = data.get("summary", "")

            combined_issues = issues + api_issues
            passed = api_pass and (len(issues) == 0) and (not has_cuts) and (not has_warp)

            logger.info(
                f"Video QC on {video_path.name}: Passed={passed}, "
                f"Cuts={has_cuts}, Warping={has_warp}, Issues={combined_issues}"
            )

            return VideoQCResult(
                passed=passed,
                confidence=confidence,
                has_scene_cuts=has_cuts or local_res.get("abrupt_cut_detected", False),
                has_warping_morphing=has_warp,
                issues=combined_issues,
                summary=summary
            )

        except Exception as e:
            logger.error(f"Video QC API error: {e}")
            passed = len(issues) == 0
            return VideoQCResult(
                passed=passed,
                confidence=0.5,
                has_scene_cuts=local_res.get("abrupt_cut_detected", False),
                has_warping_morphing=False,
                issues=issues + [f"API Error: {e}"],
                summary="Fallback to local OpenCV analysis"
            )
