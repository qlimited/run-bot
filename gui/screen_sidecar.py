"""Read-only screen endpoint while an older GUI server keeps a bot running."""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from server import DATA_FILE, ID_RE, capture_screen_png, validate_endpoint


capture_locks: dict[str, threading.Lock] = {}
locks_guard = threading.Lock()


class ScreenHandler(BaseHTTPRequestHandler):
    gui_port = 8766

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, message: str):
        self._send(code, json.dumps({"error": message}).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        allowed_origins = {f"http://127.0.0.1:{self.gui_port}", f"http://localhost:{self.gui_port}"}
        if (host not in allowed_hosts or origin not in allowed_origins
                or self.headers.get("Sec-Fetch-Site") not in (None, "same-site", "same-origin")):
            self.send_error(403)
            return
        url = urlsplit(self.path)
        if url.path != "/api/devices/screen":
            self._error(404, "Not found.")
            return
        device_id = parse_qs(url.query).get("device", [None])[0]
        if not isinstance(device_id, str) or not ID_RE.fullmatch(device_id):
            self._error(400, "Device not found.")
            return
        try:
            profiles = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            profile = next((item for item in profiles if item.get("id") == device_id), None)
            if profile is None:
                raise ValueError("Device not found.")
            ip, port = validate_endpoint(profile["ip"], profile["port"])
            with locks_guard:
                lock = capture_locks.setdefault(device_id, threading.Lock())
            if not lock.acquire(blocking=False):
                self._error(429, "Screen capture is busy. Retry shortly.")
                return
            try:
                image = capture_screen_png(f"{ip}:{port}")
            finally:
                lock.release()
            try:
                self._send(200, image, "image/png")
            except (BrokenPipeError, ConnectionResetError):
                pass
        except (OSError, TypeError, KeyError, ValueError) as exc:
            self._error(400, str(exc))


def main():
    parser = argparse.ArgumentParser(description="Temporary read-only CookieRun screen service")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--gui-port", type=int, default=8766)
    args = parser.parse_args()
    ScreenHandler.gui_port = args.gui_port
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ScreenHandler)
    print(f"Screen preview is ready at http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
