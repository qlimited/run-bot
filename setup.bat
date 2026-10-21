@echo off
setlocal
cd /d "%~dp0"

set "PYTHON="
for %%P in (python "py -3") do (
  if not defined PYTHON (
    %%~P -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set "PYTHON=%%~P"
  )
)
if not defined PYTHON (
  echo Python 3.12 or newer is required. Install it from https://www.python.org/downloads/ and run setup.bat again.
  exit /b 1
)

if not exist env\Scripts\python.exe (
  echo Creating env\ ...
  %PYTHON% -m venv env || exit /b 1
)
rem Older installs used opencv-python; it shares the cv2 package with the headless build, so both cannot coexist.
env\Scripts\python.exe -m pip uninstall --disable-pip-version-check -y -q opencv-python >nul 2>&1
env\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt || exit /b 1
env\Scripts\python.exe -c "import cv2, numpy" || exit /b 1

env\Scripts\python.exe adb.py
echo Setup complete. Start the dashboard with start-gui.bat or the CLI bot with start-bot.bat
