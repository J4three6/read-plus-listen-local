@echo off
setlocal
cd /d "%~dp0"
set "SYNC_PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%SYNC_PY%" (
    echo Run instalar.bat first / Ejecuta instalar.bat primero.
    pause
    exit /b 1
)
start "" "%SYNC_PY%" -B "%~dp0app.py"
