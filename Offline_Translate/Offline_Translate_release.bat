@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set APPNAAM=Offline_Translate
set REPO=C:\github_cicd\python-tools
set VERFILE=%~dp0010_version_offline_translate.txt
set PYFILE=%~dp0Offline_Translate.py
set PATH=%PATH%;C:\Program Files\Git\bin;C:\Program Files\Git\cmd

echo ================================================
echo   Release: %APPNAAM%
echo ================================================
echo.

:: Lees huidig versienummer
set /p HUIDIG=<"%VERFILE%"
echo Huidig versienummer: v!HUIDIG!
echo.
set /p NIEUW="Nieuw versienummer (Enter = !HUIDIG! behouden): "
if "!NIEUW!"=="" set NIEUW=!HUIDIG!

set /p BERICHT="Commit bericht: "
if "!BERICHT!"=="" set BERICHT=update v!NIEUW!
echo.

:: Versie wegschrijven naar txt
echo !NIEUW!> "%VERFILE%"

:: Versie bijwerken in Offline_Translate.py via PowerShell
echo [1/5] Versie bijwerken in Offline_Translate.py...
powershell -Command "(Get-Content '%PYFILE%') -replace '(__version__\s*=\s*)[''\""][\d.]+[''\""]', ('$1\"%NIEUW%\"') | Set-Content '%PYFILE%'"
echo Versie bijgewerkt naar !NIEUW!

:: Lokale exe bouwen vanuit venv
echo.
echo [2/5] Lokale exe bouwen (vanuit venv)...
call "%~dp0.venv\Scripts\activate.bat"
pip install -q pyinstaller pillow langdetect
python -m PyInstaller Offline_Translate.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo FOUT bij bouwen exe!
    pause & exit /b 1
)
echo Lokale exe klaar: %~dp0dist\Offline_Translate.exe

:: Kopieer naar monorepo
echo.
echo [3/5] Kopieren naar monorepo...
set REPO_APP=%REPO%\Offline_Translate
if not exist "%REPO_APP%" mkdir "%REPO_APP%"
copy /Y "%~dp0Offline_Translate.py"               "%REPO_APP%\Offline_Translate.py"               >nul
copy /Y "%~dp0Offline_Translate.spec"             "%REPO_APP%\Offline_Translate.spec"             >nul
copy /Y "%~dp0offlinetranslate.ico"               "%REPO_APP%\offlinetranslate.ico"               >nul
copy /Y "%~dp0requirements.txt"                   "%REPO_APP%\requirements.txt"                   >nul
copy /Y "%~dp0010_version_offline_translate.txt"  "%REPO_APP%\010_version_offline_translate.txt"  >nul
copy /Y "%~dp0Offline_Translate_release.bat"      "%REPO_APP%\Offline_Translate_release.bat"      >nul
copy /Y "%~dp0setup.bat"                          "%REPO_APP%\setup.bat"                          >nul
copy /Y "%~dp0start.bat"                          "%REPO_APP%\start.bat"                          >nul
copy /Y "%~dp0download_models.py"                 "%REPO_APP%\download_models.py"                 >nul
echo Klaar.

:: Git push
echo [4/5] Pushen naar GitHub...
cd /d "%REPO%"
git restore .github\    >nul 2>&1
git restore transcribe\ >nul 2>&1
git restore audioforge\ >nul 2>&1
git restore ocr\        >nul 2>&1
git add Offline_Translate/
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Offline_Translate: !BERICHT!"
    git push
    if errorlevel 1 ( echo FOUT bij git push! & pause & exit /b 1 )
) else (
    echo Geen wijzigingen om te committen.
)

:: Tag aanmaken en pushen
echo [5/5] Tag aanmaken: Offline_Translate/v!NIEUW!
git fetch --tags >nul 2>&1
git rev-parse Offline_Translate/v!NIEUW! >nul 2>&1
if errorlevel 1 (
    git tag Offline_Translate/v!NIEUW!
    git push origin Offline_Translate/v!NIEUW!
) else (
    echo Tag Offline_Translate/v!NIEUW! bestaat al.
    echo Verhoog het versienummer voor een nieuwe release.
)

echo.
echo ================================================
echo   Klaar: %APPNAAM% v!NIEUW!
echo   Lokale exe : %~dp0dist\Offline_Translate.exe
echo   GitHub     : https://github.com/richardvanderveer/python-tools/actions
echo ================================================
echo.
pause
