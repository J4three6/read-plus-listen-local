@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" server.py
) else (
    echo Prepara el entorno del reproductor con los pasos del README.
    pause
    exit /b 1
)
if errorlevel 1 pause
