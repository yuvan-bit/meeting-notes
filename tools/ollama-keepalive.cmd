@echo off
tasklist /FI "IMAGENAME eq ollama app.exe" 2>NUL | find /I "ollama app.exe" >NUL
if not errorlevel 1 exit /b 0
start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
exit /b 0
