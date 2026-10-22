@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.webui
pause
