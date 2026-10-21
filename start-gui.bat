@echo off
setlocal
cd /d "%~dp0"
if not exist env\Scripts\python.exe (
  echo env\ is missing. Run setup.bat first.
  exit /b 1
)
env\Scripts\python.exe gui\server.py %*
