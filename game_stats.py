"""Capture and store the XP and coins shown on the game's Result screen."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import cv2

from adb import device_capture_screen


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("COOKIERUN_STATS_FILE") or ROOT / "gui" / "game_stats.sqlite3")
VISION_SCRIPT = ROOT / "tools" / "read_result.swift"


def parse_result_text(observations):
    """Take only the two number fields on the 1280 x 720 Result panel."""
    result = {}
    for item in observations:
        x, y = item["x"], item["y"]
        if not 0.79 <= x <= 0.91:
            continue
        field = "coins" if 0.52 <= y <= 0.61 else "xp" if 0.63 <= y <= 0.72 else None
        if field is None:
            continue
        value = re.fullmatch(r"[0-9][0-9, .]*", item["text"].strip())
        if value:
            result[field] = int(re.sub(r"\D", "", value.group()))
    return result if "coins" in result and "xp" in result else None


def read_result_screen(image):
    if sys.platform != "darwin":
        return None
    with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
        cv2.imwrite(image_file.name, image)
        completed = subprocess.run(
            ["swift", str(VISION_SCRIPT), image_file.name],
            capture_output=True, text=True, timeout=15, check=False,
        )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Result OCR failed")
    return parse_result_text(json.loads(completed.stdout))


def capture_result(ip, port, timeout=15):
    """Wait for the reward counters to stop animating before accepting values."""
    if sys.platform != "darwin":
        return None
    deadline = time.monotonic() + timeout
    # The first numbers appear quickly, but the coin bonus keeps counting after XP settles.
    time.sleep(3)
    previous = None
    stable_since = None
    while time.monotonic() < deadline:
        image = device_capture_screen(ip, port)
        reading = read_result_screen(image)
        now = time.monotonic()
        if reading and reading == previous:
            if stable_since is not None and now - stable_since >= 2:
                return reading
        else:
            stable_since = now if reading else None
        previous = reading
        time.sleep(0.5)
    return None


def _connect(db_path=DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5)
    connection.execute("""CREATE TABLE IF NOT EXISTS game_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_serial TEXT NOT NULL,
        finished_at INTEGER NOT NULL,
        xp INTEGER NOT NULL CHECK (xp >= 0),
        coins INTEGER NOT NULL CHECK (coins >= 0)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS results_device_idx ON game_results(device_serial, id DESC)")
    return connection


def save_result(serial, xp, coins, db_path=DB_PATH):
    if xp < 0 or coins < 0:
        raise ValueError("Result values cannot be negative")
    with closing(_connect(db_path)) as connection, connection:
        connection.execute(
            "INSERT INTO game_results(device_serial, finished_at, xp, coins) VALUES (?, ?, ?, ?)",
            (serial, int(time.time()), xp, coins),
        )


def get_results(serial, limit=20, db_path=DB_PATH):
    with closing(_connect(db_path)) as connection:
        count, xp_total, coins_total = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(xp), 0), COALESCE(SUM(coins), 0) "
            "FROM game_results WHERE device_serial = ?", (serial,),
        ).fetchone()
        rows = connection.execute(
            "SELECT id, finished_at, xp, coins FROM game_results "
            "WHERE device_serial = ? ORDER BY id DESC LIMIT ?", (serial, limit),
        ).fetchall()
    return {"count": count, "xp_total": xp_total, "coins_total": coins_total,
            "recent": [dict(zip(("id", "finished_at", "xp", "coins"), row)) for row in rows]}
