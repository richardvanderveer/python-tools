@echo off
:: Offline_Translate — Eerste installatie
set "DIR=%~dp0"

echo ============================================
echo  Offline_Translate — Installatie
echo ============================================
echo.

python --version 2>nul || (echo [FOUT] Python niet gevonden. & pause & exit /b 1)

if not exist "%DIR%.venv" (
    echo Venv aanmaken...
    python -m venv "%DIR%.venv"
)

echo Pakketten installeren...
call "%DIR%.venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r "%DIR%requirements.txt"

echo.
echo Installatie gereed!
echo.
echo Volgende stap — modellen downloaden:
echo   .venv\Scripts\python download_models.py --talen nl en
echo   .venv\Scripts\python download_models.py --alles
echo.
pause
