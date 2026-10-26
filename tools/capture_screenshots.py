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
        "description": "Live Executive Dashboard (Dark Mode)",
        "transform": lambda h: h
    },
    {
        "name": "02_dashboard_light.png",
        "description": "Live Executive Dashboard (Light Mode)",
        "transform": lambda h: h.replace('<html lang="en" class="dark">', '<html lang="en" class="light"><script>localStorage.setItem("stocknova_theme", "light");</script>')
    },
    {
        "name": "03_onboarding_guide_tour.png",
        "description": "Interactive Step-by-Step Onboarding Tour",
        "transform": lambda h: h.replace('id="modal-onboarding" class="fixed inset-0 bg-black/75 backdrop-blur-md hidden', 'id="modal-onboarding" class="fixed inset-0 bg-black/75 backdrop-blur-md flex')
    },
    {
        "name": "04_asset_vault.png",
        "description": "Central Asset Vault Tab",
        "transform": lambda h: h.replace('id="tab-dashboard" class="space-y-6"', 'id="tab-dashboard" class="hidden space-y-6"')
                                 .replace('id="tab-vault" class="hidden space-y-4"', 'id="tab-vault" class="space-y-4"')
                                 .replace('id="nav-dashboard" class="tab-active', 'id="nav-dashboard" class="theme-text-sub')
                                 .replace('id="nav-vault" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl theme-text-sub', 'id="nav-vault" class="tab-active w-full flex items-center gap-3 px-3 py-2.5 rounded-xl')
    },
    {
        "name": "05_csv_export_studio.png",
        "description": "Multi-Platform CSV & Metadata Studio Tab",
        "transform": lambda h: h.replace('id="tab-dashboard" class="space-y-6"', 'id="tab-dashboard" class="hidden space-y-6"')
                                 .replace('id="tab-export" class="hidden space-y-5"', 'id="tab-export" class="space-y-5"')
                                 .replace('id="nav-dashboard" class="tab-active', 'id="nav-dashboard" class="theme-text-sub')
                                 .replace('id="nav-export" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl theme-text-sub', 'id="nav-export" class="tab-active w-full flex items-center gap-3 px-3 py-2.5 rounded-xl')
    },
    {
        "name": "06_freepik_150_gate.png",
        "description": "Freepik 150 Golden Asset Gate Tab",
        "transform": lambda h: h.replace('id="tab-dashboard" class="space-y-6"', 'id="tab-dashboard" class="hidden space-y-6"')
                                 .replace('id="tab-freepik" class="hidden space-y-4"', 'id="tab-freepik" class="space-y-4"')
                                 .replace('id="nav-dashboard" class="tab-active', 'id="nav-dashboard" class="theme-text-sub')
                                 .replace('id="nav-freepik" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl theme-text-sub', 'id="nav-freepik" class="tab-active w-full flex items-center gap-3 px-3 py-2.5 rounded-xl')
    },
    {
        "name": "07_accounts_and_api_keys.png",
        "description": "Google Accounts & API Keys Manager Tab",
        "transform": lambda h: h.replace('id="tab-dashboard" class="space-y-6"', 'id="tab-dashboard" class="hidden space-y-6"')
                                 .replace('id="tab-accounts" class="hidden space-y-5"', 'id="tab-accounts" class="space-y-5"')
                                 .replace('id="nav-dashboard" class="tab-active', 'id="nav-dashboard" class="theme-text-sub')
                                 .replace('id="nav-accounts" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl theme-text-sub', 'id="nav-accounts" class="tab-active w-full flex items-center gap-3 px-3 py-2.5 rounded-xl')
    },
    {
        "name": "08_ai_models_guide.png",
        "description": "AI Models Architecture & Quota Efficiency Tab",
        "transform": lambda h: h.replace('id="tab-dashboard" class="space-y-6"', 'id="tab-dashboard" class="hidden space-y-6"')
                                 .replace('id="tab-harmony" class="hidden space-y-4"', 'id="tab-harmony" class="space-y-4"')
                                 .replace('id="nav-dashboard" class="tab-active', 'id="nav-dashboard" class="theme-text-sub')
                                 .replace('id="nav-harmony" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl theme-text-sub', 'id="nav-harmony" class="tab-active w-full flex items-center gap-3 px-3 py-2.5 rounded-xl')
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
