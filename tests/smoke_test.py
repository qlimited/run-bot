"""Cross-platform smoke test against a fake adb (tests/fake_adb.py); no device or emulator needed.

Run with the project's venv Python:  env/bin/python tests/smoke_test.py  (Windows: env\\Scripts\\python.exe)
"""

import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == "win32"
FAKE_ADB = REPO / "tests" / ("fake_adb.bat" if WINDOWS else "fake_adb")
SERIAL = "127.0.0.1:5555"
OPTIONS = {"fast_start": False, "cookie_relay": False, "random_boost": False,
           "detect_relic": False, "auto_jump": False, "auto_add_friend": False}
# One install layout per entry in adb.EMULATOR_ADB_GLOBS, in the same order.
EMULATOR_LAYOUTS = (
    "Netease/MuMuPlayer-12.0/shell/adb.exe",
    "Netease/MuMu Player 12/nx_main/adb.exe",
    "BlueStacks_nxt/HD-Adb.exe",
    "LDPlayer/LDPlayer9/adb.exe",
    "Nox/bin/nox_adb.exe",
)

TEMPLATE_CHECK = """
import contextlib, io, os, sys
sys.path.insert(0, sys.argv[1])
import cv2, numpy as np
import actions, adb, bot, config, debug, detection

name = config.STAGE_TEMPLATES["MAINMENU"][0]
template = cv2.imread(os.path.join(config.TEMPLATE_DIR, name))
assert template is not None, f"{name} is missing from TEMPLATE_DIR={config.TEMPLATE_DIR}"
screen = np.zeros((720, 1280, 3), np.uint8)
x, y = config.STAGE_REGIONS["MAINMENU"][:2]
screen[y:y + template.shape[0], x:x + template.shape[1]] = template
assert detection.detect_stage(screen, ["MAINMENU"]) == "MAINMENU", "MAINMENU template was not recognised"
assert detection.detect_stage(np.zeros_like(screen)) is None, "a blank screen matched a stage"

existed = os.path.isdir(debug.DEBUG_DIR)
before = set(os.listdir(debug.DEBUG_DIR)) if existed else set()
with contextlib.redirect_stdout(io.StringIO()):
    debug.save_debug_screen(screen)
added = set(os.listdir(debug.DEBUG_DIR)) - before
assert len(added) == 1, f"debug screen not saved under {debug.DEBUG_DIR}"
os.remove(os.path.join(debug.DEBUG_DIR, added.pop()))
if not existed:
    os.rmdir(debug.DEBUG_DIR)
"""


def ok(message):
    print(f"ok: {message}", flush=True)


def base_env():
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env.update(ADB=str(FAKE_ADB), FAKE_ADB_PYTHON=sys.executable)
    return env


def check_emulator_adb(workdir):
    sys.path.insert(0, str(REPO))
    import adb

    root = Path(workdir) / "emulators"
    for layout in EMULATOR_LAYOUTS:
        (root / layout).parent.mkdir(parents=True, exist_ok=True)
        (root / layout).touch()
    found = list(adb._emulator_adb_candidates([root]))
    assert found == [root / layout for layout in EMULATOR_LAYOUTS], f"emulator adb candidates: {found}"
    ok("emulator adb globs match MuMu, BlueStacks, LDPlayer and Nox in order")

    if not WINDOWS:
        return
    env = {k: v for k, v in os.environ.items() if k not in ("ADB", "ANDROID_HOME", "ANDROID_SDK_ROOT")}
    env.update({"LOCALAPPDATA": str(Path(workdir) / "no-sdk"), "PROGRAMFILES": str(root), "PROGRAMFILES(X86)": str(root)})
    env["PATH"] = os.pathsep.join(p for p in env["PATH"].split(os.pathsep) if not shutil.which("adb", path=p))
    result = subprocess.run([sys.executable, str(REPO / "adb.py")], cwd=workdir, env=env,
                            capture_output=True, text=True, timeout=60)
    expected = f"adb: {root / EMULATOR_LAYOUTS[0]}"
    assert result.returncode == 0 and result.stdout.strip() == expected, \
        f"adb.py without an SDK printed {result.stdout!r} {result.stderr!r}, expected {expected!r}"
    ok("adb.py falls back to an emulator's adb when there is no SDK or adb on PATH")


def check_cli(workdir):
    result = subprocess.run([sys.executable, "-c", TEMPLATE_CHECK, str(REPO)], cwd=workdir, env=base_env())
    assert result.returncode == 0, "template and debug-screen check failed (traceback above)"
    ok("modules import, templates load and debug screens save from an unrelated cwd")

    # stdin at EOF ends the bot at its first prompt; stdout is a pipe, the case where Windows
    # falls back to a legacy code page.
    result = subprocess.run([sys.executable, str(REPO / "main.py")], cwd=workdir, env=base_env(),
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    output = result.stdout.decode("utf-8")
    assert result.returncode == 0, f"main.py exited {result.returncode}\n{output}\n{result.stderr.decode(errors='replace')}"
    for expected in ("🚀 CookieRun Classic Bot Started", f"🔌 Connected to {SERIAL}", "Bot Options"):
        assert expected in output, f"main.py output lacks {expected!r}\n{output}"
    ok("main.py connects through $ADB and prints emoji to a pipe")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Gui:
    def __init__(self, workdir):
        self.port = free_port()
        devices_file = Path(workdir) / "devices.json"
        devices_file.write_text("[]", encoding="utf-8")
        env = base_env()
        env["COOKIERUN_DEVICES_FILE"] = str(devices_file)
        self.log_path = Path(workdir) / "server.log"
        self.log = open(self.log_path, "wb")
        group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS
                 else {"start_new_session": True})
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(REPO / "gui" / "server.py"), "--port", str(self.port), "--no-browser"],
            cwd=workdir, env=env, stdout=self.log, stderr=subprocess.STDOUT, **group)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {}
        if body is not None:
            headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"}
        try:
            conn.request(method, path, None if body is None else json.dumps(body), headers)
            response = conn.getresponse()
            return response.status, response.getheader("Content-Type", ""), response.read()
        finally:
            conn.close()

    def post(self, path, body):
        status, _, data = self.request("POST", path, body)
        assert status == 200, f"POST {path} -> {status}: {data!r}"
        return json.loads(data)

    def state(self, device_id):
        status, _, data = self.request("GET", f"/api/state?device={device_id}&after=0")
        assert status == 200, f"GET /api/state -> {status}"
        return json.loads(data)["selected"]

    def wait_ready(self, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert self.process.poll() is None, f"server exited with {self.process.returncode}"
            try:
                return json.loads(self.request("GET", "/api/state")[2])
            except OSError:
                time.sleep(0.25)
        raise AssertionError("server did not answer in time")

    def shutdown(self):
        if self.process.poll() is None:
            if WINDOWS:
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.log.close()
        return self.process.returncode


def wait_for(gui, device_id, predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while True:
        state = gui.state(device_id)
        if predicate(state):
            return state
        if time.monotonic() > deadline:
            logs = "\n".join(entry["text"] for entry in state["logs"])
            raise AssertionError(f"timed out waiting for {what}; status={state['status']}\n{logs}")
        time.sleep(0.25)


def log_text(state):
    return "\n".join(entry["text"] for entry in state["logs"])


def check_gui(workdir):
    gui = Gui(workdir)
    try:
        assert gui.wait_ready()["devices"] == [], "server did not use the isolated devices file"
        ok(f"server listening on port {gui.port}")

        device_id = gui.post("/api/devices/add", {"name": "smoke", "ip": "127.0.0.1", "port": 5555})["selected"]["id"]
        state = gui.post("/api/devices/connect", {"device_id": device_id})["selected"]
        assert state["adb_state"] == "device", f"adb_state is {state['adb_state']}"
        ok("device added and connected through $ADB")

        status, content_type, body = gui.request("GET", f"/api/devices/screen?device={device_id}")
        assert status == 200 and content_type == "image/png" and body.startswith(b"\x89PNG"), f"screen -> {status}"
        ok("live screen endpoint returns a PNG")

        gui.post("/api/start", {"device_id": device_id, **OPTIONS})
        state = wait_for(gui, device_id, lambda s: "---------------------" in log_text(s), 60, "the options banner")
        logs = log_text(state)
        for expected in (f"📱 Connecting to device at {SERIAL}", f"🔌 Connected to {SERIAL}", "⚙️ --- Bot Options ---"):
            assert expected in logs, f"bot log lacks {expected!r}\n{logs}"
        running_since = time.monotonic()
        while time.monotonic() - running_since < 5:
            state = gui.state(device_id)
            assert state["status"] == "running", f"bot left running: {state['status']}\n{log_text(state)}"
            assert "An error occurred" not in log_text(state), log_text(state)
            time.sleep(0.5)
        ok("bot runs its capture loop for 5 s without errors")

        stop_requested = time.monotonic()
        gui.post("/api/stop", {"device_id": device_id})
        state = wait_for(gui, device_id, lambda s: "Process finished" in log_text(s), 8, "the bot process to exit")
        elapsed = time.monotonic() - stop_requested
        logs = log_text(state)
        assert state["status"] == "idle", f"status after stop is {state['status']}\n{logs}"
        assert "🛑 Bot stopped by user." in logs and "Process finished (exit code 0)." in logs, logs
        ok(f"bot stopped gracefully in {elapsed:.1f} s")
    except BaseException:
        gui.shutdown()
        print(gui.log_path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
        raise
    code = gui.shutdown()
    assert code == 0, f"server exited with {code}\n{gui.log_path.read_text(errors='replace')}"
    ok("server shut down cleanly")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    print(f"python {sys.version.split()[0]} on {sys.platform}", flush=True)
    with tempfile.TemporaryDirectory() as workdir:
        check_emulator_adb(workdir)
        check_cli(workdir)
        check_gui(workdir)
    print("smoke test passed")


if __name__ == "__main__":
    main()
