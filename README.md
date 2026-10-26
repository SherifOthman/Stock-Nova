# StockNova AI — Autonomous Stock Photography & Video AI Studio

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg)](https://microsoft.com)
[![UI WebView2](https://img.shields.io/badge/UI-Microsoft%20Edge%20WebView2-008272.svg)](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
[![Tailwind CSS](https://img.shields.io/badge/Styling-Tailwind%20CSS-38B2AC.svg)](https://tailwindcss.com/)
[![License MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An executive-grade autonomous pipeline and native Windows desktop dashboard engineered for end-to-end stock media generation, two-stage quality control, 2x AI upscaling, anti-similarity batch distribution, and multi-platform publishing (Adobe Stock & Freepik).

---

## ⚡ Key Highlights

- **Native WebView2 Executive Dashboard:** Zero-browser-tab native desktop app with pure English typography, instant **Light Mode / Dark Mode** toggle, and flicker-free real-time telemetry.
- **Two-Stage Intelligent Quality Control:**
  - **Stage 1 (Pre-Upscale):** Fast RAM compression and AI visual sanity check (rejects hallucinations, warped artifacts, and deformities).
  - **Stage 2 (Post-Upscale):** 100% full-resolution crop analysis checking OpenCV Laplacian sharpness and digital noise thresholds.
- **Strict 2x AI Upscale Standard:** Locked to 2x magnification (~17 Megapixels, $4096 \times 4096$ or $5500 \times 3000$) using Upscayl CLI, guaranteeing optimal commercial 4K quality without excessive file bloat.
- **Anti-Similarity Batch Distribution (pHash):** Distributes visually related images into separate submission batches via perceptual hashing (pHash distance $> 12$) to eliminate commercial duplicate rejections.
- **Multi-Platform Metadata & CSV Studio:**
  - **Adobe Stock:** Comma-separated (`,`), 5 standard columns (`Filename,Title,Keywords,Category,Releases`), and official **numeric category IDs (1 to 21)**.
  - **Freepik Contributor:** Semicolon-separated (`;`), 5 AI columns (`File name;Title;Keywords;Prompt;Model`), automatic `_ai_generated` tag injection, and strict photo-only filtering.
- **Commercial Downloads & Sales Tracking:** Ingests contributor CSV reports to track best sellers, royalties, and buyer demand trends.
- **Live Ops Center:** Real-time upload speed, active file tracking, and animated progress monitoring.

---

## 📁 Repository Structure

```text
Stock-Nova/
├── config/
│   ├── settings.yaml              # Core pipeline and platform configurations
│   ├── accounts_config.json       # Account rotation and pool allocations
│   └── creative_strategy.json     # Dynamic self-evolving strategy learnings
├── stockpilot/
│   ├── app.py                     # Master pipeline orchestrator
│   ├── core/                      # Config, database, quota, and status monitor
│   ├── metadata/                  # Category classifier, SEO, IPTC, and CSV exporter
│   ├── platforms/                 # Adobe Stock (FTP) and Freepik onboarding gates
│   ├── quality/                   # Stage 1 QC, Stage 2 QC, and 2x Upscaler
│   ├── strategy/                  # Argon 4 Copilot, trend researcher, prompt engine
│   └── ui/                        # WebView2 desktop bridge and app.html
├── tools/
│   ├── benchmark_upscayl.py       # Performance testing utility
│   ├── exiftool.exe               # Standalone ExifTool wrapper
│   └── exiftool_files/            # ExifTool dependencies
├── workspace/                     # Clean pipeline folder stages (.gitkeep)
│   ├── 0_Raw_Downloads/
│   ├── 1_QC1_Approved/
│   ├── 2_Upscaled/
│   ├── 2_QC2_Approved/
│   ├── 3_Batched_Ready/
│   ├── 4_Uploaded_Awaiting_Submit/
│   └── exports/
├── run.bat                        # 1-Click launcher for native desktop app
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites
1. **Windows 10 or 11 (64-bit)**
2. **Python 3.11+** installed and added to `PATH`
3. **Microsoft Edge WebView2 Runtime** (pre-installed on Windows 10/11)
4. **Upscayl CLI** installed at `C:\Program Files\Upscayl\resources\bin\upscayl-bin.exe`

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/SherifOthman/Stock-Nova.git
   cd Stock-Nova
   ```

2. Install Python dependencies:
   ```bash
   pip install pywebview pyyaml opencv-python pillow imagehash google-genai
   ```

3. Launch the Studio:
   - Double-click `run.bat`, or execute:
   ```bash
   python -m stockpilot.ui.desktop_api
   ```

---

## 🛠️ Configuration

Update `config/settings.yaml` with your credentials and paths:
```yaml
project:
  name: "StockNova AI"
  version: "2.0.0"

paths:
  workspace_root: "d:\\Stock Automation\\workspace"
  database: "d:\\Stock Automation\\data\\google_dots.db"
  exiftool: "d:\\Stock Automation\\tools\\exiftool.exe"

upscayl:
  default_scale: 2 # Fixed 2x standard (Optimal 4K / ~17 MP)

gemini:
  strategic_model: "gemini-4-argon"
  agent_orchestrator: "gemini-3.8-flash"
  qc_fast_model: "gemini-3.5-flash-lite"
```

---

## 📊 Platform Metadata Specifications

| Specification | Adobe Stock Contributor | Freepik Contributor |
| :--- | :--- | :--- |
| **Delimiter** | Comma (`,`) | Semicolon (`;`) |
| **Header Row** | `Filename,Title,Keywords,Category,Releases` | `File name;Title;Keywords;Prompt;Model` |
| **Category Format** | **Numeric ID (1 to 21)** strictly | Dynamic keyword taxonomy & asset type |
| **AI Tagging** | Standard IPTC metadata | Mandatory `_ai_generated` in keywords |
| **Supported Media** | Images and Videos | Photos Only (Videos filtered) |

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).
