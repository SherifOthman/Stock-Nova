"""
StockNova AI — Master Desktop Application Entrypoint.
Spins up a native Windows Edge WebView2 desktop application window
interfacing directly with the local Python engine, SQLite database, and pipeline services.
"""

from __future__ import annotations

import sys
from pathlib import Path
import webview

PROJECT_ROOT = Path(r"d:\Stock Automation")
sys.path.insert(0, str(PROJECT_ROOT))

from stockpilot.ui.desktop_api import DesktopBridgeAPI


def main() -> None:
    window_container = []
    api = DesktopBridgeAPI(window_container)

    html_file = PROJECT_ROOT / "stockpilot" / "ui" / "app.html"
    html_url = html_file.resolve().as_uri()

    window = webview.create_window(
        title="StockNova AI — Autonomous Stock Photography & Video Studio",
        url=html_url,
        width=1200,
        height=800,
        min_size=(1020, 680),
        js_api=api,
        background_color="#0c0f14"
    )
    window_container.append(window)

    # Launch native Edge WebView2 window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
