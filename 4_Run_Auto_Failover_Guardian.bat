@echo off
rem Never run a python.exe that happens to sit in the current folder
set "NoDefaultCurrentDirectoryInExePath=1"
chcp 65001 >nul
title Orca Auto-Failover Guardian (Live Sentinel)
cls
echo Starting Orca Auto-Failover Guardian...
echo Model switch karne se pehle ye aapse Yes/No poochega.
python "%~dp0orca_model_router.py" guard
pause
