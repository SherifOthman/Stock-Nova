# 05 — Detailed Step-by-Step Implementation Roadmap

> **Execution Blueprint:** Follow these steps in exact order so every part of the restructured architecture works together seamlessly.

---

## Phase 1: Core Restructuring, Per-User Isolation & Database Upgrade
1. **Clean Up & Remove Hardcoded Paths (`config.py`, `database.py`, `unified_vault.py`, `desktop_app.py`, `desktop_api.py`, `app.py`):**
   - Remove all 9 hardcoded `d:\Stock Automation`, `D:\images\Images to upload`, and `C:\Users\eleml` paths.
   - Point user database, vault, and settings to `%LOCALAPPDATA%\StockNovaAI\` and workspace folders to the user's selected workspace path.
2. **Upgrade SQLite Database Schema (`stockpilot/core/database.py`):**
   - Enable `PRAGMA journal_mode=WAL;` for safe multi-thread access.
   - Add / upgrade tables:
     - `gemini_accounts`: Stores multiple Gemini/Argon accounts, tier (`free_50`, `plus_200`, `pro_1000`), `is_primary_argon`, `daily_free_used`, `remaining_credits`, `billing_cycle_start`.
     - `agent_memory_snapshots`: Stores local Argon handoff context so switching from Account #1 to Account #2 never loses chat history.
     - `video_model_stats`: Tracks each eligible video model's QC pass rate and platform acceptance rate (while banning `100-credit Quality` mode).
     - `daily_shifts`: Tracks today's auto-pilot progress (`videos_completed`, `images_completed`, `current_stage`, `status`).
     - `freepik_150_ledger`: Stores `file_hash`, `filename`, `status` (`approved_150` / `rejected_150`), `score`, and `reason` so the Freepik 150 Gate never re-checks already-inspected images.
     - `platform_history`: Stores weekly/daily Accepted vs. Not Accepted counts and rejection reasons from Adobe Stock and Freepik.
3. **Fix Google AI Studio Model Names & Key Rotator (`api_key_rotator.py`, `desktop_api.py`, `settings.yaml`):**
   - Replace invalid model names (`gemini-4-argon`, `gemini-3.5-flash-lite`) on the AI Studio API endpoint with official `gemini-2.5-flash` and `gemini-2.5-pro`.
   - Fix `test_api_key()` and `test_ftp_connection()`.

---

## Phase 2: Smart Quality Control, Storyboard Video QC, 2x Upscale & Clean CSVs
1. **Smart Low-Token Video QC (`stockpilot/quality/video_qc.py` & `utils/video_processor.py`):**
   - Build the **8-Frame Storyboard Contact Sheet Generator**: extracts 8 key frames from a video and stitches them into a single 4x2 grid image so Google AI Studio inspects the whole video in **1 single image API call**.
   - Enforce mandatory audio stripping (`ffmpeg -an`) on every video (`بدون صوت نهائياً`) because Adobe Stock rejects video audio tracks.
2. **Calibrated 3-Tier Image & Video QC (`stage1_qc.py` & `stage2_qc.py`):**
   - Classify files into `Approved (80+)`, `Borderline / Needs Quick Look (60–79)`, and `Rejected (<60)` so good files are never thrown away by mistake and bad files never slip through.
3. **Strictly `2x` Upscaling + Commercial License Guard (`upscaler.py` & `model_license_validator.py`):**
   - Lock upscaling scale to **`2x` (`scale=2`)** so `2048×2048` / `3000×1500` images become crisp 4K without pixelation.
   - Default to commercial-safe **High Fidelity** weights and add a 3-image sample comparison helper.
4. **Disable File Binary Keyword Injection & Use Separate Platform CSVs (`batch_exporter.py` & `app.py`):**
   - Stop injecting IPTC tags into image/video binaries (`iptc_writer.py` disabled in pipeline; only strip AI generator EXIF metadata so files are clean).
   - Generate separate `Adobe_Stock_Batch.csv` and `Freepik_Batch.csv` files so the exact same media files can be uploaded to both platforms cleanly.

---

## Phase 3: Credit Pool Engine, Dynamic Buffer, Portfolio Analyzer & Daily Auto-Pilot
1. **Credit Pool Engine (`stockpilot/core/credit_pool_manager.py` & `dynamic_controller.py`):**
   - Implement strict consumption order:
     1. **All Free 50/day accounts FIRST**
     2. **Plus 200/month accounts SECOND (fast burn)**
     3. **Pro 1000/month accounts THIRD over a dynamic 10–20 active-day window** (adjusted dynamically by acceptance rate so credits never go unused by month-end).
   - Hard-block any 100-credit `Quality` video mode.
2. **Master Argon Failover & Handoff Report (`antigravity_bridge.py` & `memory_context.py`):**
   - Always use Primary Argon Account #1 first; if it hits a limit, switch to Account #2 and prepend the SQLite Handoff Report automatically.
3. **Dynamic Rolling Image Buffer & Dual-Platform Tracking (`dynamic_controller.py`, `adobe_stock.py`, `freepik.py`):**
   - Run **Videos every single day**.
   - For **Images**, calculate predicted weekly capacity from recent Accepted vs. Rejected stats and maintain a ready buffer (+25% surplus) waiting for Adobe Stock / Freepik upload windows to open.
   - Track `adobe_status` and `freepik_status` independently on every file.
   - Add the **Accepted vs. Not Accepted Portfolio Analyzer** to learn from real rejections and approvals.
4. **Stateful Freepik 150 Gate Curator (`freepik_curator.py`):**
   - Scan candidate folder using strict manual-review rules, record every inspected image hash in `freepik_150_ledger`, skip already-reviewed images on future runs, and build incrementally up to 150/150.
5. **Safe Telegram Report (`telegram_notifier.py`):**
   - Send daily completion summary; include the direct Submit link **only** if Submit is safely confirmed open.

---

## Phase 4: Professional 5-Page UI Redesign (Dark & Light Themes Fixed)
1. **Redesign `stockpilot/ui/app.html` & `desktop_api.py`:**
   - Implement the new CSS Variable color system so both **Dark Mode** and **Light Mode** have crisp contrast and readable buttons.
   - Build the **5 Clean Pages**:
     1. **Home (Daily Employee & Live Credit Pools: Free 50 / Plus 200 / Pro 1000)**
     2. **Review Queue (Visual Image/Video Thumbnails + Borderline Filter + Separate Adobe/Freepik CSV Export)**
     3. **Freepik 150 Gate (Dedicated Tab with Incremental Scan Button & 150 Progress Tracker)**
     4. **Portfolio Intelligence (Accepted vs. Rejected Analysis & Video Model Winner Table)**
     5. **Settings & Accounts (Multi-Account Argon/Gemini Manager, AI Studio Keys, Adobe/Freepik Toggle, 2x Upscaler, Telegram)**
   - Replace the broken blurred tour with the **3-Step First-Run Setup** + optional **Driver.js Spotlight Tour**.
2. **Clean Up Legacy Files & Installer Script:**
   - Remove redundant `gui.py` and `web_dashboard.py` and prepare `build_installer.bat`.
