@echo off
rem Never run a python.exe that happens to sit in the current folder
set "NoDefaultCurrentDirectoryInExePath=1"
set "HERE=%~dp0"
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Orca - Fast Model Switcher
cls
echo ======================================================================
echo  🔄 ORCA FAST MODEL SWITCHER
echo ======================================================================
echo.
echo Kaunsa Model activate karna chahte hain?
echo.
echo  [1] OpenAI Codex - GPT-6.1 Sol (Workhorse Coding ^& API)
echo  [2] OpenAI Codex - GPT-6 Astra (Frontier High Reasoning)
echo  [3] Anthropic Claude - Sonnet 5.5 (Fast Routine Coding)
echo  [4] Anthropic Claude - Opus 5.5 (Deep Architecture ^& Hard Tasks)
echo  [5] Anthropic Claude - Haiku 5.5 (Ultra-fast ^& Lightweight)
echo  [6] Google Antigravity - Gemini 3.8 Flash (1M+ Huge Context / Repo Audit)
echo  [7] SpaceXAI Grok - Grok 4.7 (Live Web ^& Market Trends)
echo  [0] Cancel
echo.
set "choice="
set /p "choice=Number chunein (0-7): "

rem Delayed expansion (!var!) keeps quotes or symbols typed at the prompt from breaking the script
set "agent="
if "!choice!"=="1" (set "agent=codex" & set "model=gpt-6.1-sol" & set "label=Codex GPT-6.1 Sol")
if "!choice!"=="2" (set "agent=codex" & set "model=gpt-6-astra" & set "label=Codex GPT-6 Astra")
if "!choice!"=="3" (set "agent=claude" & set "model=sonnet" & set "label=Claude Sonnet 5.5")
if "!choice!"=="4" (set "agent=claude" & set "model=opus" & set "label=Claude Opus 5.5")
if "!choice!"=="5" (set "agent=claude" & set "model=haiku" & set "label=Claude Haiku 5.5")
if "!choice!"=="6" (set "agent=antigravity" & set "model=gemini-3.8-flash" & set "label=Antigravity Gemini 3.8 Flash")
if "!choice!"=="7" (set "agent=grok" & set "model=grok-4.7" & set "label=Grok 4.7")

if "!choice!"=="0" (
    echo Cancelled.
    exit /b 0
)
if not defined agent (
    echo.
    echo Galat choice. Kripya 0 se 7 ke beech ka number chunein.
    pause
    exit /b 1
)

echo.
echo !label! activate ho raha hai...
python "!HERE!orca_model_router.py" switch !agent! --model !model!
if errorlevel 1 (
    echo.
    echo ❌ Switch nahi ho paya. Upar diya error dekhein.
) else (
    echo.
    echo ✅ Done. Orca IDE me active tab switch ho chuka hai.
)
pause
