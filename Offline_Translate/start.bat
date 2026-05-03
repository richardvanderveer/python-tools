@echo off
:: Offline_Translate — Startscript
:: Alle HuggingFace/transformers netwerktoegang hard geblokkeerd

set "DIR=%~dp0"
set "PY=%DIR%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [FOUT] Venv niet gevonden. Voer setup.bat eerst uit.
    pause & exit /b 1
)

:: ============================================================
:: OFFLINE LOCKDOWN — voorkomt elke netwerkpoging van de
:: transformers / HuggingFace bibliotheek
:: ============================================================
set "TRANSFORMERS_OFFLINE=1"
set "HF_HUB_OFFLINE=1"
set "HF_DATASETS_OFFLINE=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "HF_HUB_DISABLE_PROGRESS_BARS=0"
set "DISABLE_TELEMETRY=1"
set "DO_NOT_TRACK=1"

:: Ollama blijft wel bereikbaar via localhost (geen internet)
:: Postgres blijft bereikbaar via localhost (geen internet)

"%PY%" "%DIR%Offline_Translate.py"

if errorlevel 1 (
    echo.
    echo [FOUT] Applicatie onverwacht gestopt.
    pause
)
