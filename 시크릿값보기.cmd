@echo off
chcp 65001 > nul
cd /d "%~dp0"
python show_secrets.py
echo.
pause
