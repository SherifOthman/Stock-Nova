# 04 — Clean Project Restructuring & Multi-User Isolation Plan

> **Goal:** Restructure the codebase cleanly so it is fast, modular, easy to maintain, and **100% isolated per user** so when you package it into a setup installer (`StockNova_AI_Setup.exe`), every user gets a fresh database and private workspace with zero personal files or paths from your computer.

---

## 1. Clean Module Architecture (After Restructuring)

We will clean up redundant files (like the old Tkinter `gui.py`, old `web_dashboard.py`, and binary tagger `iptc_writer.py`) and organize `stockpilot/` into clear, well-connected modules:

```
stockpilot/
├── desktop_app.py                  # Native Windows WebView2 launcher (Main Entry Point on PC)
├── app.py                          # Unified Pipeline Engine (Videos + Images + 2x Upscale + CSV)
├── core/
│   ├── config.py                   # Per-user path resolver (%LOCALAPPDATA%\StockNovaAI) + dynamic settings
│   ├── database.py                 # SQLite WAL database (assets, credit_pools, daily_shifts, freepik_150_ledger, learning)
│   ├── security.py                 # Windows DPAPI encryption for API keys, accounts & tokens
│   ├── agent_coordinator.py        # NEW: Self-Driving Daily Employee state machine & auto-pilot loop
│   ├── credit_pool_manager.py      # NEW: Free 50/day -> Plus 200 -> Pro 1000 (10-20 day dynamic pace)
│   ├── dynamic_controller.py       # Rolling weekly image buffer predictor & adaptive QC thresholds (saved to DB!)
│   ├── browser_account_resolver.py # Detects browser profiles & Free/Plus/Pro account tiers
│   └── logger.py                   # Clean per-user activity logger
├── strategy/
│   ├── antigravity_bridge.py       # Primary Argon Account priority + automatic failover with SQLite Handoff Report
│   ├── memory_context.py           # Local SQLite memory snapshot so Argon never loses history across accounts
│   ├── trend_researcher.py         # Niche planner combining market demand + your Accepted/Rejected portfolio stats
│   └── prompt_generator.py         # Generates Video Prompts (1st) and Image Prompts (2nd) using learned rules
├── quality/
│   ├── api_key_rotator.py          # Automatic rotation across Google AI Studio API keys
│   ├── stage1_qc.py                # Fast local OpenCV image check (resolution, blur, exposure)
│   ├── stage2_qc.py                # Calibrated 3-tier AI Vision image check (Approved / Borderline / Rejected)
│   ├── video_qc.py                 # Local motion/FPS check + 8-Frame Single-Image Storyboard Grid for Gemini Vision
│   ├── upscaler.py                 # Strictly 2x (scale=2) High-Fidelity commercial-safe upscaler + sample tester
│   └── model_license_validator.py  # Blocks non-commercial upscale models & 100-credit Quality video modes
├── metadata/
│   ├── seo_generator.py            # Generates English Titles, 49 Keywords & Category IDs via AI Studio keys
│   ├── category_classifier.py      # Maps assets to official Adobe Stock & Freepik categories
│   └── batch_exporter.py           # Generates clean separate Adobe_Stock.csv & Freepik.csv (NO file binary injection!)
├── platforms/
│   ├── adobe_stock.py              # Passive upload-window status + Accepted vs. Not Accepted portfolio analyzer
│   ├── freepik.py                  # Freepik status & portfolio tracking
│   └── freepik_curator.py          # Stateful Freepik 150 Gate curator (remembers checked hashes in SQLite)
├── batching/
│   └── similarity_engine.py        # pHash duplicate & near-duplicate spacing across batches
├── utils/
│   ├── video_processor.py          # FFmpeg mandatory audio stripping (-an) & clean MP4 formatting
│   ├── image_utils.py              # Strips AI generator EXIF tags while keeping image binary clean
│   └── filename_cleaner.py         # Clean commercial filenames
├── reporting/
│   └── telegram_notifier.py        # Daily summary report (only includes Submit link if Submit is safely open)
└── ui/
    ├── desktop_api.py              # Clean Python-to-UI bridge exposing all 5 pages & Auto-Pilot controls
    └── app.html                    # Redesigned 5-page UI (Dark & Light themes fixed, Driver.js spotlight, thumbnails)
```

---

## 2. How Per-User Data Isolation Works (Zero Personal Data Leakage)

1. **No Hardcoded `D:\Stock Automation` or `C:\Users\eleml` Anywhere:**
   - `config.py` resolves all user data dynamically using the current Windows user's environment:
     - **Private App Data Folder:** `%LOCALAPPDATA%\StockNovaAI\`
       - Holds `stocknova.db`, `user_settings.yaml`, `accounts_vault.json`, and `logs/`.
     - **Default Media Workspace:** `%USERPROFILE%\Documents\StockNova Workspace\` (or any custom folder the user picks in Settings).
2. **Fresh Database on Any New Machine:**
   - When you package the app or copy it to another computer, `stocknova.db` is created fresh and empty on that computer, so the other user has their own accounts, their own API keys, their own images, and their own AI learning history.
