@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\pythonw.exe" (
  echo Virtual environment not found.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m app.client
exit /b 0
