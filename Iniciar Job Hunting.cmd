@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\job-hunting.exe" (
    call "Instalar Job Hunting.cmd"
    if errorlevel 1 exit /b 1
)
start "Job Hunting" ".venv\Scripts\pythonw.exe" -m autojob gui
