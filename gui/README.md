# CookieRun Bot GUI

Local browser dashboard for the existing Python bot. No additional GUI package is required.

```bash
cd /path/to/run-bot
python3.9 gui/server.py
```

The dashboard opens at `http://127.0.0.1:8766/`. If a browser does not open automatically, paste that address into your browser. Use `python3.9 gui/server.py --port 8767` to choose another port.

On macOS, you can also double-click `gui/launch.command` to start the GUI.

The **ภาพรวมทุกเครื่อง** section supports multiple ADB devices. Add each device with its own IP/host and port, then select a card to connect ADB, choose its options, and start or stop its bot. Each device runs in a separate Python process, so multiple bots can run at the same time. Status, stage, run time, and live logs follow the selected device. Device profiles are saved in `gui/devices.json`; option choices are remembered per device in this browser. Use the **×** button on any card or **ลบอุปกรณ์** in settings to remove a profile. If its bot is running, the GUI stops that bot before removal. You can remove the last profile and add another later. The original CLI bot in `bot/` can still run independently.

In **จอสด**, select a connected device and press **ดูจอสด** to view ADB screenshots refreshed about once per second. It does not include audio or remote controls. The preview follows the selected device, pauses while the browser tab is hidden, and stops when you press **หยุดดูจอ** or close the tab. Capturing images alongside a running bot adds some ADB traffic.

The device cards provide an overview of every connected device with a small screen image, ADB/Bot status, and latest detected stage. Thumbnails are fetched one device at a time, no more often than every five seconds per device while the overview is visible, and paused when the tab is hidden. **แจ้งเตือน** tracks ADB disconnections, bot errors or unexpected stops, and `ANTI_BOT` detection. Active issues appear as badges; recent events are kept in this browser's local storage and can be cleared. Clicking an issue selects its device. This is an in-app alert center and does not request system notification permission.

If upgrading a running GUI server without stopping its active bot, `python3 gui/screen_sidecar.py` provides a temporary read-only preview endpoint on port 8767. The browser falls back to it only when the older server on port 8766 does not yet provide the screen endpoint. After the main GUI server is restarted with this version, the sidecar is no longer needed.

Use a Python interpreter with `numpy` and `opencv-python` installed. Make sure `adb` is available in your PATH. The device screen must be 1280 × 720. If the dashboard cannot find the bot, initialize the submodule with `git submodule update --init`.
