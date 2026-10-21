"""Start the existing CLI bot with the GUI's device selection."""

import runpy
import signal
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import config  # noqa: E402


config.DEVICE_IP = sys.argv[1]
config.DEVICE_PORT = int(sys.argv[2])
# The GUI stops the bot with an interrupt, and the bot only exits cleanly on KeyboardInterrupt.
# A GUI launched in the background hands SIGINT down as ignored; on Windows the interrupt is
# CTRL_BREAK because Ctrl+C cannot reach a new process group.
signal.signal(signal.SIGINT, signal.default_int_handler)
if sys.platform == "win32":
    signal.signal(signal.SIGBREAK, signal.default_int_handler)
runpy.run_path(str(PROJECT_DIR / "main.py"), run_name="__main__")
