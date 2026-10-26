"""
StockNova AI — Automated Screen Capture Utility.
Generates full-resolution screenshots for all application views and onboarding guides.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(r"d:\Stock Automation")
SCREENSHOTS_DIR = ROOT / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

ARTIFACT_DIR = Path(r"C:\Users\eleml\.gemini\antigravity\brain\3936ec08-dafd-45cd-951c-816303a69147")

CHROME_BIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TEMP_USER_DATA = r"C:\Users\eleml\AppData\Local\Temp\chrome_screen_profile"
APP_HTML_PATH = ROOT / "stockpilot" / "ui" / "app.html"

original_html = APP_HTML_PATH.read_text(encoding="utf-8")

views = [
    {
        "name": "01_dashboard_dark.png",
        "description": "Executive Dashboard (Dark Mode - Free Points Default & Live Ops)",
        "transform": lambda h: h
    },
    {
        "name": "02_dashboard_light.png",
        "description": "Executive Dashboard (Crisp Daylight Light Mode)",
        "transform": lambda h: h.replace('class="dark"', 'class="light"')
                                 .replace('localStorage.getItem(\'stocknova_theme\') || \'dark\'', '\'light\'')
    },
    {
        "name": "03_quick_setup_wizard.png",
        "description": "Interactive First-Run Setup & Ingestion Wizard",
        "transform": lambda h: h.replace('id="modal-quick-setup"', 'id="modal-quick-setup" class="sc-modal-overlay open"')
    },
    {
        "name": "04_asset_vault.png",
        "description": "Asset Vault & Review Queue (2x 4K Status & Visual Grid)",
        "transform": lambda h: h.replace('id="tab-dashboard" class="tab-content active"', 'id="tab-dashboard" class="tab-content"')
                                 .replace('id="tab-vault" class="tab-content"', 'id="tab-vault" class="tab-content active"')
                                 .replace('class="nav-tab-btn active" data-tab="dashboard"', 'class="nav-tab-btn" data-tab="dashboard"')
                                 .replace('class="nav-tab-btn" data-tab="vault"', 'class="nav-tab-btn active" data-tab="vault"')
                                 .replace('Executive Dashboard', 'Asset Vault & Review Queue')
    },
    {
        "name": "05_csv_export_studio.png",
        "description": "CSV Studio (Adobe Stock Categories 1-21 & Freepik AI CSV)",
        "transform": lambda h: h.replace('id="tab-dashboard" class="tab-content active"', 'id="tab-dashboard" class="tab-content"')
                                 .replace('id="tab-export" class="tab-content"', 'id="tab-export" class="tab-content active"')
                                 .replace('class="nav-tab-btn active" data-tab="dashboard"', 'class="nav-tab-btn" data-tab="dashboard"')
                                 .replace('class="nav-tab-btn" data-tab="export"', 'class="nav-tab-btn active" data-tab="export"')
                                 .replace('Executive Dashboard', 'CSV Export Studio')
    },
    {
        "name": "06_freepik_150_gate.png",
        "description": "Freepik 150 Golden Asset Gate (Strict QC & Stateful Ledger)",
        "transform": lambda h: h.replace('id="tab-dashboard" class="tab-content active"', 'id="tab-dashboard" class="tab-content"')
                                 .replace('id="tab-freepik" class="tab-content"', 'id="tab-freepik" class="tab-content active"')
                                 .replace('class="nav-tab-btn active" data-tab="dashboard"', 'class="nav-tab-btn" data-tab="dashboard"')
                                 .replace('class="nav-tab-btn" data-tab="freepik"', 'class="nav-tab-btn active" data-tab="freepik"')
                                 .replace('Executive Dashboard', 'Freepik 150 Golden Gate')
    },
    {
        "name": "07_accounts_and_vault.png",
        "description": "Accounts, Shared Pools & Hardware-Bound Security Vault",
        "transform": lambda h: h.replace('id="tab-dashboard" class="tab-content active"', 'id="tab-dashboard" class="tab-content"')
                                 .replace('id="tab-settings" class="tab-content"', 'id="tab-settings" class="tab-content active"')
                                 .replace('class="nav-tab-btn active" data-tab="dashboard"', 'class="nav-tab-btn" data-tab="dashboard"')
                                 .replace('class="nav-tab-btn" data-tab="settings"', 'class="nav-tab-btn active" data-tab="settings"')
                                 .replace('Executive Dashboard', 'Settings & Security Vault')
    },
    {
        "name": "08_page_guide_dashboard.png",
        "description": "Spotlight Interactive Page Guide on Dashboard",
        "transform": lambda h: h.replace('class="page-guide-banner" id="guide-dashboard"', 'class="page-guide-banner visible" id="guide-dashboard"')
    }
]

temp_dir = Path(r"C:\Users\eleml\AppData\Local\Temp\stocknova_capture")
temp_dir.mkdir(parents=True, exist_ok=True)

for v in views:
    temp_html = temp_dir / f"view_{v['name']}.html"
    temp_png = temp_dir / v["name"]
    final_png = SCREENSHOTS_DIR / v["name"]

    modified = v["transform"](original_html)
    temp_html.write_text(modified, encoding="utf-8")

    html_url = f"file:///{str(temp_html).replace(chr(92), '/')}"

    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"Start-Process -FilePath '{CHROME_BIN}' -ArgumentList '--headless=new', '--user-data-dir={TEMP_USER_DATA}', '--window-size=1400,900', '--screenshot={str(temp_png)}', '{html_url}' -Wait"
    ]
    subprocess.run(cmd, check=True)

    if temp_png.exists():
        shutil.copy2(temp_png, final_png)
        if ARTIFACT_DIR.exists():
            shutil.copy2(temp_png, ARTIFACT_DIR / v["name"])
        size_kb = final_png.stat().st_size / 1024
        print(f"[+] Captured {v['name']} ({size_kb:.1f} KB) — {v['description']}")
        temp_png.unlink()
    else:
        print(f"[-] Failed to capture {v['name']}")

    if temp_html.exists():
        temp_html.unlink()

print("[*] All screenshots generated and saved to screenshots/ and brain artifacts!")
