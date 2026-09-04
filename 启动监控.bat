@echo off
cd /d %~dp0
.venv\Scripts\python.exe -X utf8 -u main.py run
pause
