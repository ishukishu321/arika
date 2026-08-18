@echo off
cd /d "%~dp0"
echo Starting Arika...
py -3 main.py || python main.py
pause
