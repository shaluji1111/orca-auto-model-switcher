@echo off
rem Never run a python.exe that happens to sit in the current folder
set "NoDefaultCurrentDirectoryInExePath=1"
chcp 65001 >nul
title Orca - Live Model ^& Token Health
cls
python "%~dp0orca_model_router.py" status
echo.
pause
