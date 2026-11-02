@echo off
rem Never run a python.exe that happens to sit in the current folder
set "NoDefaultCurrentDirectoryInExePath=1"
chcp 65001 >nul
title Enable Orca Auto-Failover Guardian (Auto-Start with Windows)
cls
echo ==============================================================
echo  🛡️ ENABLE ORCA AUTO-FAILOVER GUARDIAN (AUTO-START)
echo ==============================================================
echo.
echo Ye setup teen kaam karega:
echo  1. orca_model_router.py ki ek local copy %%LOCALAPPDATA%%\OrcaSmartRouter me rakhega
echo  2. Windows Startup folder me ek shortcut banayega, taaki login par guardian chale
echo  3. Guardian ko abhi background me start karega
echo.
echo Kisi model ke tokens khatam hone par Guardian doosre healthy model par
echo switch karne se pehle aapse Yes/No poochega.
echo.
echo Cancel karne ke liye ye window band karein. Aage badhne ke liye koi key dabayein.
pause >nul
python "%~dp0orca_model_router.py" install-autostart
echo.
pause
