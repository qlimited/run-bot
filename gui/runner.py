"""Start the bot submodule with the GUI's device selection."""

import runpy
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
BOT_DIR = PROJECT_DIR / "bot"
sys.path.insert(0, str(BOT_DIR))

import config  # noqa: E402


config.DEVICE_IP = sys.argv[1]
config.DEVICE_PORT = int(sys.argv[2])
runpy.run_path(str(BOT_DIR / "main.py"), run_name="__main__")
