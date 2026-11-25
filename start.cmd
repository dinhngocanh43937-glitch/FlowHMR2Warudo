@echo off
cd /d "%~dp0"
python -I "%~dp0portable_entry.py" client/native_app.py
