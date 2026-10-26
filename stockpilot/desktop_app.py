"""
StockNova AI — Master Desktop Application Entrypoint.
Spins up a native Windows Edge WebView2 desktop application window
interfacing directly with the local Python engine, SQLite database, and autonomous daily employee.
"""

from __future__ import annotations

import sys
from pathlib import Path
import webview

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stockpilot.ui.desktop_api import DesktopBridgeAPI


def main() -> None:
    window_container: list = []
    api = DesktopBridgeAPI(window_container)

    html_file = PROJECT_ROOT / "stockpilot" / "ui" / "app.html"
    html_url = html_file.resolve().as_uri()

    window = webview.create_window(
        title="StockNova AI — الموظف الذكي لإنتاج وإدارة الاستوك اليومي",
        url=html_url,
        width=1360,
        height=860,
        min_size=(1080, 720),
        js_api=api,
        background_color="#0B0F17",
    )
    window_container.append(window)

    def _on_shown() -> None:
        api.on_app_startup()

    window.events.shown += _on_shown

    # Launch native Edge WebView2 window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
