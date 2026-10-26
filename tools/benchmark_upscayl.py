"""
Benchmark tool for Upscayl models.
Tests a sample image across available Upscayl models to compare quality and speed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Paths
DEFAULT_BIN = Path(r"C:\Program Files\Upscayl\resources\bin\upscayl-bin.exe")
DEFAULT_MODELS_DIR = Path(r"C:\Program Files\Upscayl\resources\models")
OUTPUT_BASE_DIR = Path(r"d:\Stock Automation\workspace\benchmark_results")


def list_available_models(models_dir: Path) -> list[str]:
    """Scans the Upscayl models directory for model names (.bin / .param)."""
    if not models_dir.exists():
        print(f"[!] Models directory not found: {models_dir}")
        return []

    # Models typically have .bin and .param files with same base name
    names = set()
    for f in models_dir.glob("*.bin"):
        names.add(f.stem)
    for f in models_dir.glob("*.param"):
        names.add(f.stem)
    return sorted(list(names))


def run_benchmark(
    sample_image: Path,
    models: list[str],
    scale: int = 4,
    bin_path: Path = DEFAULT_BIN,
    models_dir: Path = DEFAULT_MODELS_DIR,
    output_dir: Path = OUTPUT_BASE_DIR,
) -> None:
    """Runs the sample image through each model and outputs timing and file details."""
    if not bin_path.exists():
        print(f"[ERROR] upscayl-bin.exe not found at: {bin_path}")
        return

    if not sample_image.exists():
        print(f"[ERROR] Sample image not found at: {sample_image}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 60)
    print(f"🚀 Benchmarking Upscayl Models on: {sample_image.name}")
    print(f"📁 Output Directory: {output_dir}")
    print("=" * 60 + "\n")

    results = []

    for model in models:
        print(f"[*] Processing model: {model} (scale: {scale}x)...", end="", flush=True)
        model_out_dir = output_dir / model
        model_out_dir.mkdir(exist_ok=True)

        start_time = time.perf_counter()

        cmd = [
            str(bin_path),
            "-i", str(sample_image),
            "-o", str(model_out_dir),
            "-s", str(scale),
            "-m", str(models_dir),
            "-n", model,
            "-f", "jpg"
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                check=False
            )
            elapsed = time.perf_counter() - start_time

            if res.returncode == 0:
                # Find created file
                created_files = list(model_out_dir.glob("*.jpg")) + list(model_out_dir.glob("*.png"))
                file_size_kb = (created_files[0].stat().st_size / 1024) if created_files else 0
                print(f" ✅ DONE in {elapsed:.2f}s (Size: {file_size_kb:.1f} KB)")
                results.append({
                    "model": model,
                    "status": "SUCCESS",
                    "time": elapsed,
                    "size_kb": file_size_kb,
                    "path": created_files[0] if created_files else "N/A"
                })
            else:
                print(f" ❌ FAILED (code {res.returncode})")
                print(f"    Stderr: {res.stderr.strip()[:200]}")
                results.append({
                    "model": model,
                    "status": "FAILED",
                    "error": res.stderr.strip()
                })
        except subprocess.TimeoutExpired:
            print(" ⚠️ TIMED OUT (180s)")
            results.append({"model": model, "status": "TIMEOUT"})
        except Exception as e:
            print(f" ⚠️ EXCEPTION: {e}")
            results.append({"model": model, "status": "ERROR", "error": str(e)})

    # Summary table
    print("\n" + "=" * 60)
    print("📊 BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"{'Model Name':<25} | {'Status':<10} | {'Time (s)':<10} | {'Size (KB)':<10}")
    print("-" * 60)
    for r in results:
        status = r.get("status", "N/A")
        t_str = f"{r.get('time', 0):.2f}" if "time" in r else "N/A"
        s_str = f"{r.get('size_kb', 0):.1f}" if "size_kb" in r else "N/A"
        print(f"{r['model']:<25} | {status:<10} | {t_str:<10} | {s_str:<10}")
    print("=" * 60)
    print(f"✨ Inspect the visual outputs in: {output_dir}\n")


def main():
    parser = argparse.ArgumentParser(description="Upscayl Model Benchmark Tool")
    parser.add_argument("--image", "-i", type=str, help="Path to sample image (e.g. raw 2K/1K AI generation)")
    parser.add_argument("--scale", "-s", type=int, default=4, help="Upscale factor (default: 4)")
    args = parser.parse_args()

    models = list_available_models(DEFAULT_MODELS_DIR)
    if not models:
        # Fallback standard models known in Upscayl
        models = [
            "realesrgan-x4plus",
            "remacri",
            "ultramix_balanced",
            "ultrasharp",
            "digital_art"
        ]
        print(f"[*] Detected/Standard models list: {', '.join(models)}")
    else:
        print(f"[*] Found {len(models)} local models: {', '.join(models)}")

    if not args.image:
        print("\n[!] No test image specified via --image.")
        print("    Usage example: python benchmark_upscayl.py --image 'path\\to\\test.png'")
        return

    sample = Path(args.image)
    run_benchmark(sample_image=sample, models=models, scale=args.scale)


if __name__ == "__main__":
    main()
