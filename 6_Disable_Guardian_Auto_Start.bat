@echo off
rem Never run a python.exe that happens to sit in the current folder
set "NoDefaultCurrentDirectoryInExePath=1"
chcp 65001 >nul
title Disable Orca Auto-Failover Guardian Auto-Start
cls
rem Removes the Startup shortcut (old and new name) and stops only guardian processes, not every pythonw.exe
python "%~dp0orca_model_router.py" uninstall-autostart
echo.
pause
