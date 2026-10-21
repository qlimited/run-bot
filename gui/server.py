"""Local multi-device dashboard for the existing CookieRun Classic bot."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


GUI_DIR = Path(__file__).resolve().parent
PROJECT_DIR = GUI_DIR.parent
DATA_FILE = Path(os.environ.get("COOKIERUN_DEVICES_FILE") or GUI_DIR / "devices.json")
sys.path.insert(0, str(PROJECT_DIR))
import config  # noqa: E402
from adb import adb_executable  # noqa: E402


ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/devices.css": ("devices.css", "text/css; charset=utf-8"),
    "/delete.css": ("delete.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$")
STAGE_RE = re.compile(r"Detected Stage: ([A-Z_]+)")
ID_RE = re.compile(r"^[a-f0-9]{32}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_SCREEN_BYTES = 8 * 1024 * 1024


if sys.platform == "win32":
    def spawn_group(args, **kwargs):
        return subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, **kwargs)

    def interrupt_group(process):
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except OSError:
            pass

    def terminate_group(process):
        process.terminate()

    def kill_group(process):
        process.kill()
else:
    def spawn_group(args, **kwargs):
        return subprocess.Popen(args, start_new_session=True, **kwargs)

    def _signal_group(process, sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    def interrupt_group(process):
        _signal_group(process, signal.SIGINT)

    def terminate_group(process):
        _signal_group(process, signal.SIGTERM)

    def kill_group(process):
        _signal_group(process, signal.SIGKILL)


def validate_endpoint(ip_value, port_value):
    ip = str(ip_value or "").strip()
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        if not HOST_RE.fullmatch(ip) or ".." in ip:
            raise ValueError("Enter a valid device IP address or hostname.") from None
    try:
        port = int(port_value)
    except (TypeError, ValueError):
        raise ValueError("ADB port must be a number.") from None
    if not 1 <= port <= 65535:
        raise ValueError("ADB port must be between 1 and 65535.")
    return ip, port


def adb_device_states():
    """Read ADB status without connecting or launching the game."""
    try:
        result = subprocess.run([adb_executable(), "devices"], capture_output=True, text=True, timeout=4, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    states = {}
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            states[parts[0]] = parts[1]
    return states


def capture_screen_png(serial: str) -> bytes:
    try:
        result = subprocess.run(
            [adb_executable(), "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=6, check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from None
    except subprocess.TimeoutExpired:
        raise ValueError("Screen capture timed out. Check the ADB connection.") from None
    if result.returncode or not result.stdout.startswith(PNG_SIGNATURE):
        raise ValueError("Could not capture screen. Check the ADB connection.")
    if len(result.stdout) > MAX_SCREEN_BYTES:
        raise ValueError("Screen image is too large.")
    return result.stdout


class BotController:
    def __init__(self, device_id: str, name: str, ip: str, port: int):
        self.id, self.name, self.ip, self.port = device_id, name, ip, port
        self.serial = f"{ip}:{port}"
        self.lock = threading.RLock()
        self.process: subprocess.Popen[str] | None = None
        self.logs: deque[dict] = deque(maxlen=600)
        self.next_log_id = 1
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.stage: str | None = None
        self.error = False
        self.stopping = False
        self.screen_lock = threading.Lock()

    def _record(self, line: str):
        line = line.rstrip("\r\n")
        if not line:
            return
        with self.lock:
            self.logs.append({"id": self.next_log_id, "text": line})
            self.next_log_id += 1
            match = STAGE_RE.search(line)
            if match:
                self.stage = match.group(1)
            if "An error occurred:" in line:
                self.error = True

    def _read_output(self, process: subprocess.Popen[str]):
        assert process.stdout is not None
        for line in process.stdout:
            with self.lock:
                if self.process is process:
                    self._record(line)
        code = process.wait()
        with self.lock:
            if self.process is process:
                self._record(f"Process finished (exit code {code}).")
                self.finished_at = time.time()
                if code != 0 and not self.stopping:
                    self.error = True
                self.stopping = False

    def snapshot(self, after: int = 0, include_logs: bool = True):
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            status = ("stopping" if self.stopping else "running") if running else ("error" if self.error else "idle")
            state = {
                "id": self.id, "name": self.name, "ip": self.ip, "port": self.port,
                "serial": self.serial, "status": status, "stage": self.stage,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "latest_log_id": self.next_log_id - 1,
            }
            if include_logs:
                state["logs"] = [entry for entry in self.logs if entry["id"] > after]
            return state

    def start(self, options: dict):
        flags = [bool(options.get("fast_start")), bool(options.get("cookie_relay")), bool(options.get("random_boost"))]
        boost_index = options.get("boost_index", 0)
        if flags[2]:
            try:
                boost_index = int(boost_index)
            except (TypeError, ValueError):
                raise ValueError("Choose a boost.") from None
            if not 1 <= boost_index <= 11:
                raise ValueError("Choose a boost.")
        answers = ["y" if value else "n" for value in flags]
        if flags[2]:
            answers.append(str(boost_index))
        answers.append("y" if options.get("detect_relic") else "n")
        for key, *_ in config.TOP_BOOSTS:
            answers.append("y" if options.get(key, True) else "n")
        answers.append("y" if options.get("auto_jump") else "n")
        answers.append("y" if options.get("auto_add_friend") else "n")

        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise ValueError("This device's bot is already running.")
            self.logs.clear()
            self.next_log_id = 1
            self.stage = None
            self.error = False
            self.stopping = False
            self.started_at = time.time()
            self.finished_at = None
            self.process = spawn_group(
                [sys.executable, "-u", str(GUI_DIR / "runner.py"), self.ip, str(self.port)],
                cwd=PROJECT_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", bufsize=1, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self._record(f"Starting bot on {self.serial}...")
            threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()
            assert self.process.stdin is not None
            try:
                self.process.stdin.write("\n".join(answers) + "\n")
                self.process.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                self.process.stdin.close()

    def stop(self):
        with self.lock:
            if self.process is None or self.process.poll() is not None or self.stopping:
                return
            self.stopping = True
            self._record("Stopping bot...")
            process = self.process
        interrupt_group(process)

        def force_stop():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                terminate_group(process)

        threading.Thread(target=force_stop, daemon=True).start()


class DeviceRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self.devices: OrderedDict[str, BotController] = OrderedDict()
        self._adb_cache_at = 0.0
        self._adb_cache = {}
        self._load()

    def _load(self):
        try:
            profiles = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if not isinstance(profiles, list):
                raise ValueError("Invalid device profiles")
        except (OSError, ValueError):
            profiles = None
        if profiles is None:
            ip, port = validate_endpoint(config.DEVICE_IP, config.DEVICE_PORT)
            device_id = uuid.uuid4().hex
            self.devices[device_id] = BotController(device_id, "อุปกรณ์หลัก", ip, port)
            self._save()
            return
        for profile in profiles:
            try:
                device_id = profile["id"]
                if not ID_RE.fullmatch(device_id):
                    continue
                ip, port = validate_endpoint(profile["ip"], profile["port"])
                name = str(profile["name"]).strip()[:40]
                if not name or any(device.serial == f"{ip}:{port}" for device in self.devices.values()):
                    continue
                self.devices[device_id] = BotController(device_id, name, ip, port)
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self):
        profiles = [{"id": d.id, "name": d.name, "ip": d.ip, "port": d.port} for d in self.devices.values()]
        temporary = DATA_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, DATA_FILE)

    def get(self, device_id: str):
        with self.lock:
            device = self.devices.get(device_id)
            if device is None:
                raise ValueError("Device not found.")
            return device

    def add(self, data: dict):
        ip, port = validate_endpoint(data.get("ip"), data.get("port"))
        with self.lock:
            name = str(data.get("name") or "").strip() or f"อุปกรณ์ {len(self.devices) + 1}"
            if len(name) > 40:
                raise ValueError("Device name is too long (max 40 characters).")
            if any(device.serial == f"{ip}:{port}" for device in self.devices.values()):
                raise ValueError("This device is already in the list.")
            device_id = uuid.uuid4().hex
            self.devices[device_id] = BotController(device_id, name, ip, port)
            self._save()
            return device_id

    def remove(self, device_id: str):
        with self.lock:
            device = self.get(device_id)
            device.stop()
            process = device.process
            if process is not None and process.poll() is None:
                try:
                    process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    kill_group(process)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        raise ValueError("Could not stop this device's bot. Try again.") from None
            del self.devices[device_id]
            self._save()
            return next(iter(self.devices), None)

    def _adb_states(self):
        with self.lock:
            if time.monotonic() - self._adb_cache_at > 4:
                self._adb_cache = adb_device_states()
                self._adb_cache_at = time.monotonic()
            return self._adb_cache

    def connect(self, device_id: str):
        device = self.get(device_id)
        try:
            result = subprocess.run([adb_executable(), "connect", device.serial], capture_output=True, text=True, timeout=12, check=False)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from None
        except subprocess.TimeoutExpired:
            raise ValueError("ADB connection timed out.") from None
        with self.lock:
            self._adb_cache_at = 0
        if self._adb_states().get(device.serial) != "device":
            message = (result.stderr or result.stdout).strip() or "ADB connection failed."
            raise ValueError(message)

    def snapshot(self, selected_id: str | None = None, after: int = 0):
        with self.lock:
            if selected_id not in self.devices:
                selected_id = next(iter(self.devices), None)
            adb_states = self._adb_states()
            devices = []
            for device in self.devices.values():
                summary = device.snapshot(include_logs=False)
                summary["adb_state"] = adb_states.get(device.serial, "disconnected")
                devices.append(summary)
            selected = self.devices[selected_id].snapshot(after) if selected_id else None
            if selected is not None:
                selected["adb_state"] = adb_states.get(selected["serial"], "disconnected")
            return {"devices": devices, "selected": selected, "defaults": {"ip": config.DEVICE_IP, "port": config.DEVICE_PORT}}

    def stop_all(self):
        with self.lock:
            processes = []
            for device in self.devices.values():
                device.stop()
                if device.process is not None:
                    processes.append(device.process)
        for process in processes:
            try:
                process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                kill_group(process)


registry = DeviceRegistry()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/devices/screen":
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if (self.headers.get("Host") not in allowed_hosts
                    or self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none")):
                self._json(403, {"error": "Request origin is not allowed."})
                return
            device_id = parse_qs(url.query).get("device", [None])[0]
            try:
                device = registry.get(device_id)
                if not device.screen_lock.acquire(blocking=False):
                    self._json(429, {"error": "Screen capture is busy. Retry shortly."})
                    return
                try:
                    try:
                        self._send(200, capture_screen_png(device.serial), "image/png")
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                finally:
                    device.screen_lock.release()
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            return
        if url.path == "/api/state":
            query = parse_qs(url.query)
            try:
                after = max(0, int(query.get("after", ["0"])[0]))
            except ValueError:
                after = 0
            self._json(200, registry.snapshot(query.get("device", [None])[0], after))
            return
        asset = ASSETS.get(url.path)
        if asset is None:
            self._json(404, {"error": "Not found."})
            return
        name, content_type = asset
        self._send(200, (GUI_DIR / name).read_bytes(), content_type)

    def do_POST(self):
        host = self.headers.get("Host", "")
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in allowed_hosts or (origin and origin not in {f"http://{name}" for name in allowed_hosts}):
            self._json(403, {"error": "Request origin is not allowed."})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(415, {"error": "Send JSON to this endpoint."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 4096:
                self._json(413, {"error": "Invalid request size."})
                return
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Invalid request.")
            selected_id = body.get("device_id")
            if self.path == "/api/devices/add":
                selected_id = registry.add(body)
            elif self.path == "/api/devices/remove":
                preferred_id = body.get("selected_id")
                fallback_id = registry.remove(selected_id)
                selected_id = preferred_id if preferred_id != selected_id else fallback_id
            elif self.path == "/api/devices/connect":
                registry.connect(selected_id)
            elif self.path == "/api/start":
                registry.get(selected_id).start(body)
            elif self.path == "/api/stop":
                registry.get(selected_id).stop()
            else:
                self._json(404, {"error": "Not found."})
                return
            self._json(200, registry.snapshot(selected_id))
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except OSError as exc:
            self._json(500, {"error": str(exc)})


def main():
    parser = argparse.ArgumentParser(description="Local CookieRun bot GUI")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        # Ctrl+Break would otherwise kill the server without stopping the bots it started.
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"CookieRun GUI is ready at {url}", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        registry.stop_all()
        server.server_close()


if __name__ == "__main__":
    main()
