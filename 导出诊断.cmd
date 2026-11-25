@echo off
cd /d "%~dp0"
python -I "%~dp0portable_entry.py" portable_diagnostics.py
pause
