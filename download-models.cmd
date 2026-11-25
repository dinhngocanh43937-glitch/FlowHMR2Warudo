@echo off
cd /d "%~dp0"
python scripts\download_models.py
if errorlevel 1 (pause & exit /b 1)
pause
