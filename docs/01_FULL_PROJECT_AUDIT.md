# 01 — Complete Project Audit & Why the Old Structure Needs Restructuring

> **Plain-Language Audit:** This file records everything currently in the codebase, what works, what is broken or mismatched with your real workflow, and what we will restructure so nothing is forgotten during implementation.

---

## 1. Core Mismatches Between Current Code and Your Real Production Rules

| Area | What the Old Code Does | Why That Is Wrong for Your Real Workflow | What the New Architecture Will Do |
|---|---|---|---|
| **1. Metadata Inside Files (`iptc_writer.py`)** | Uses ExifTool to inject keywords directly inside the `.jpg` file binary. | The **same image/video** is uploaded to **both Adobe Stock and Freepik**, and each site requires a different CSV format. Embedding tags inside the file causes conflicts. | **Never embed keywords inside the image/video.** Keep media files 100% clean (strip AI generator tags only) and create separate `Adobe_Stock.csv` and `Freepik.csv` files. |
| **2. Image Upscaling (`upscaler.py`)** | Defaults to `4x` upscaling (`scale=4`). | Source images are already `2048x2048` or `3000x1500`. Scaling 4x makes them huge, pixelated, and artificial-looking, leading to rejections. | **Strictly `2x` upscaling (`scale=2`)** to produce crisp 4K (`4096x4096` / `6000x3000`) using commercial-safe **High Fidelity** models (plus a 3–4 image sample tester). |
| **3. Video Processing & Audio (`app.py`, `video_qc.py`)** | `app.py` completely ignores `.mp4`/`.mov` files, and `video_qc.py` tries to upload full video files to the Gemini API. | Uploading full videos to AI Studio will exhaust all free API keys in seconds! Also, Adobe Stock rejects videos that have audio tracks. | **Smart Storyboard Grid QC:** Extract 6–8 key frames into **1 single composite image** per video so Gemini checks the whole video in **1 cheap API call**, and automatically strip audio (`ffmpeg -an`). |
| **4. Credit Pool Math (`dynamic_controller.py`)** | Divides credits evenly across 30 days (`remaining / 30`) and doesn't track multiple Free/Plus/Pro accounts properly. | If you don't open the PC every day, stretching credits over 30 days leaves unused credits wasted at the end of the month! | **1. All Free 50/day accounts FIRST.**<br>**2. Plus (200/mo) fast burn SECOND.**<br>**3. Pro (1000/mo) over a dynamic 10–20 active-day window** adjusted by acceptance rate. **Hard-block 100-credit Quality video mode.** |
| **5. Fixed Daily Image Quotas (`quota_engine.py`)** | Assumes a fixed daily upload limit (e.g., 50 every day). | Adobe Stock's upload/submit limit is **dynamic**—some days it is completely closed, then it opens suddenly, or stops mid-upload after 20 files. | **Dynamic Rolling Image Buffer:** Predicts capacity from last week's Accepted vs. Rejected count and keeps a ready buffer (+20% extra) waiting for the moment Submit opens. Videos still run **every single day**. |
| **6. Argon Multi-Account History (`antigravity_bridge.py`)** | Switches or calls accounts without saving a structured handoff summary. | Switching accounts loses the entire conversation history with Argon. | **Primary Master Argon Account + Local SQLite Handoff Report:** Keeps 1 primary email for Argon, saves all context locally in SQLite, and automatically sends a complete **Handoff Report** if it ever switches to Account #2. |
| **7. Freepik 150 Gate (`freepik_curator.py`)** | Has a static screen with no button and hardcoded `D:\images\Images to upload`, and doesn't remember which images were already checked across batches. | Freepik's initial 150-image test is manually reviewed and very strict. If you only have 100 good images today, you need it to remember what it already checked when you add more images tomorrow. | **Dedicated Separate "Freepik 150 Gate" Tab:** Uses ultra-strict manual-review rules, stores every checked image hash in SQLite (`approved_for_150` / `rejected_for_150`), skips already-reviewed files on future runs, and builds up to 150/150. |
| **8. Hardcoded Personal Paths (9 Files)** | Hardcodes `d:\Stock Automation`, `D:\images\Images to upload`, and `C:\Users\eleml...` in 9 files. | Breaks on any other computer and leaks your personal folder structure. | **100% Per-User Isolation:** Uses `%LOCALAPPDATA%\StockNovaAI` for each user's private database/keys and a user-selected workspace folder. |

---

## 2. Confirmed Code Bugs to Fix Immediately

1. **Hardcoded Developer Paths in 9 Files:**
   - `desktop_app.py` (L13), `desktop_api.py` (L31, L433), `app.py` (L59), `database.py` (L40), `dynamic_controller.py` (L28), `unified_vault.py` (L97), `web_dashboard.py` (L77, L87), and `config/settings.yaml` (L3, L31).
2. **Invalid AI Studio Model Names:**
   - `settings.yaml` and `desktop_api.py` call `gemini-4-argon`, `gemini-3.8-flash`, and `gemini-3.5-flash-lite` on the Google AI Studio endpoint, breaking the **"Test Key"** button (`desktop_api.py` L285).
3. **Self-Learning Calculation Never Saved:**
   - `dynamic_controller.py` (`_adapt_qc_thresholds`, L346–366) calculates new sharpness and similarity numbers when rejections happen, logs them, and throws them away without saving to SQLite or `settings.yaml`.
4. **Duplicate Exception Handler & Dead Code:**
   - `desktop_api.py` (`test_ftp_connection`, L406–418) has two `except Exception as e:` blocks and unreachable lines after `return`.
5. **SQLite Locking Risk:**
   - `database.py` opens raw SQLite connections without `PRAGMA journal_mode=WAL;`, risking database locks when background threads and UI calls run together.
6. **Three Redundant UI Systems:**
   - `gui.py` (old Tkinter) and `web_dashboard.py` (old port 8585 server) clutter the codebase alongside the real desktop app (`desktop_app.py` + `ui/app.html`). We will remove the redundant UIs and cleanly organize the project structure.
