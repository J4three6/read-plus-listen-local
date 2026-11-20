@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
 echo No se encontro Python Launcher. Instala Python 3.11 o 3.12 para Windows.
 pause
 exit /b 1
)
py -3.12 -m venv .venv
if errorlevel 1 py -3.11 -m venv .venv
if errorlevel 1 goto error
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto error
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo Instalacion completa. Ejecuta iniciar.bat
echo Asegurate de tener ffmpeg y ffprobe en PATH.
pause
exit /b 0
:error
echo Hubo un error durante la instalacion.
pause
exit /b 1
