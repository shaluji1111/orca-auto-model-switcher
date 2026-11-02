@echo off
rem Never run a python.exe that happens to sit in the current folder
set "NoDefaultCurrentDirectoryInExePath=1"
chcp 65001 >nul
title Orca - Smart Best Model Recommender
cls
echo ======================================================================
echo  🎯 ORCA SMART MODEL SELECTOR ^& RECOMMENDER
echo ======================================================================
echo.
rem Python asks for the task and the Y/N itself, so quotes and symbols in the task are safe
python "%~dp0orca_model_router.py" best --interactive
echo.
pause
