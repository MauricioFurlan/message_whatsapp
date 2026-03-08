@echo off
cd /d %~dp0
set WDM_SSL_VERIFY=0
".\venv\Scripts\python.exe" ".\main.py"
pause