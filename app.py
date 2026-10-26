"""
Lightweight Preview & Live RPC Bridge for AI Studio (Port 3000).
Does NOT modify or replace your native Windows Desktop App (stockpilot/desktop_app.py).
Serves stockpilot/ui/app.html and bridges `/api/pywebview/<method>` directly to `DesktopBridgeAPI`
so every button, SQLite table, and autonomous coordinator works identically in both environments.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

UI_HTML = ROOT_DIR / "stockpilot" / "ui" / "app.html"

from stockpilot.ui.desktop_api import DesktopBridgeAPI

_bridge_api = DesktopBridgeAPI([])


class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            if UI_HTML.exists():
                content = UI_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
        elif self.path == "/api/health":
            payload = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/pywebview/"):
            method_name = self.path.split("/api/pywebview/", 1)[1].strip("/")
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(raw_body) if raw_body else {}
            except Exception:
                payload = {}

            args = payload.get("args", [])
            kwargs = payload.get("kwargs", {})

            fn = getattr(_bridge_api, method_name, None)
            if not callable(fn):
                err = json.dumps({"status": "error", "message": f"Unknown API method: {method_name}"}).encode("utf-8")
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return

            try:
                res = fn(*args, **kwargs)
                out_bytes = res.encode("utf-8") if isinstance(res, str) else json.dumps(res).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(out_bytes)))
                self.end_headers()
                self.wfile.write(out_bytes)
            except Exception as e:
                err = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    os.chdir(str(ROOT_DIR))
    with ThreadedTCPServer(("0.0.0.0", port), PreviewHandler) as httpd:
        print(f"StockNova Preview & RPC Bridge running on http://0.0.0.0:{port}")
        httpd.serve_forever()
