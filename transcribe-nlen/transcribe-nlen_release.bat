@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set APPNAAM=Transcribe NL-ENG
set MONOREPO_APP=transcribe-nlen
set REPO=C:\github_cicd\python-tools
set VERFILE=%~dp0010_version_transcribe-nlen.txt
set PYFILE=%~dp0transcribe-nlen.py
set ISSFILE=%~dp0transcribe-nlen.iss
set PATH=%PATH%;C:\Program Files\Git\bin;C:\Program Files\Git\cmd

echo ================================================
echo   Release: %APPNAAM%  (monorepo-app: %MONOREPO_APP%)
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

:: Versie wegschrijven naar txt
echo !NIEUW!> "%VERFILE%"

:: Versie bijwerken in transcribe-nlen.py + transcribe-nlen.iss via PowerShell
echo [1/6] Versie bijwerken in transcribe-nlen.py + transcribe-nlen.iss...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bump_version.ps1" -Version "!NIEUW!" -PyFile "%PYFILE%" -IssFile "%ISSFILE%"
if errorlevel 1 (
    echo FOUT bij bijwerken versienummer!
    pause & exit /b 1
)

:: Lokale exe bouwen vanuit venv (maakt .venv aan indien nog niet aanwezig)
echo.
echo [2/6] Lokale exe bouwen...
if not exist "%~dp0.venv\Scripts\activate.bat" (
    echo Geen .venv gevonden, wordt aangemaakt...
    py -3.14 -m venv "%~dp0.venv" 2>nul || python -m venv "%~dp0.venv"
)
call "%~dp0.venv\Scripts\activate.bat"
pip install -q -r "%~dp0requirements_transcribe-nlen.txt"
pip install -q pyinstaller pillow
python -m PyInstaller transcribe-nlen.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo FOUT bij bouwen exe!
    pause & exit /b 1
)
echo Lokale exe klaar: %~dp0dist\transcribe-nlen.exe

:: Herinnering: ffmpeg/ffprobe worden NIET door PyInstaller meegepakt.
echo.
echo [3/6] Controle ffmpeg...
if not exist "%~dp0dist\ffmpeg.exe" (
    echo LET OP: ffmpeg.exe ontbreekt in dist\ — kopieer ffmpeg.exe en ffprobe.exe
    echo         handmatig naar dist\ voordat je uitdeelt aan collega's.
) else (
    echo ffmpeg.exe gevonden in dist\
)

:: Kopieren naar de python-tools monorepo.
echo.
echo [4/6] Kopieren naar monorepo (%REPO%\%MONOREPO_APP%)...
set REPO_APP=%REPO%\%MONOREPO_APP%
if not exist "%REPO_APP%" mkdir "%REPO_APP%"
copy /Y "%~dp0transcribe-nlen.py"           "%REPO_APP%\transcribe-nlen.py"           >nul
copy /Y "%~dp0transcribe-nlen.ico"          "%REPO_APP%\transcribe-nlen.ico"          >nul
copy /Y "%~dp0splash.png"                   "%REPO_APP%\splash.png"                   >nul
copy /Y "%~dp0transcribe-nlen.iss"          "%REPO_APP%\transcribe-nlen.iss"          >nul
copy /Y "%~dp0transcribe-nlen_release.bat"  "%REPO_APP%\transcribe-nlen_release.bat"  >nul
copy /Y "%~dp0010_version_transcribe-nlen.txt" "%REPO_APP%\010_version_transcribe-nlen.txt" >nul
copy /Y "%~dp0requirements_transcribe-nlen.txt" "%REPO_APP%\requirements.txt"         >nul
copy /Y "%~dp0transcribe-nlen.spec"         "%REPO_APP%\transcribe-nlen.spec"         >nul
echo Klaar.

:: Git commit + push naar de monorepo (alleen de map van deze app aanraken).
echo.
echo [5/6] Pushen naar GitHub...
cd /d "%REPO%"
git restore .github\           >nul 2>&1
git restore transcribe\        >nul 2>&1
git restore audioforge\        >nul 2>&1
git restore ocr\               >nul 2>&1
git restore Offline_Translate\ >nul 2>&1
git add %MONOREPO_APP%/
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%MONOREPO_APP%: !BERICHT!"
    git push
    if errorlevel 1 ( echo FOUT bij git push! & pause & exit /b 1 )
) else (
    echo Geen wijzigingen om te committen.
)

:: Tag aanmaken en pushen -- dit triggert de release-workflow
echo [6/6] Tag aanmaken: %MONOREPO_APP%/v!NIEUW!
git fetch --tags >nul 2>&1
git rev-parse %MONOREPO_APP%/v!NIEUW! >nul 2>&1
if errorlevel 1 (
    git tag %MONOREPO_APP%/v!NIEUW!
    git push origin %MONOREPO_APP%/v!NIEUW!
) else (
    echo Tag %MONOREPO_APP%/v!NIEUW! bestaat al.
    echo Verhoog het versienummer voor een nieuwe release.
)
cd /d "%~dp0"

:installer_stap
:: Installer bouwen (optioneel, lokaal)
echo.
echo Installer bouwen (optioneel, lokaal)...
set ISCC=
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) do (
    if exist %%P set ISCC=%%~P
)
if not exist "%ISSFILE%" (
    echo transcribe-nlen.iss niet gevonden — installer-stap overgeslagen.
    goto klaar
)
if not defined ISCC (
    echo Inno Setup niet gevonden — installer-stap overgeslagen.
    echo Download gratis via https://jrsoftware.org/isdl.php om dit automatisch te
    echo laten bouwen, of open transcribe-nlen.iss handmatig in de Inno Setup IDE.
    goto klaar
)
if not exist "%~dp0dist\ffmpeg.exe" (
    echo LET OP: dist\ffmpeg.exe ontbreekt — installer-stap overgeslagen.
    goto klaar
)
"!ISCC!" "%ISSFILE%"
if errorlevel 1 (
    echo FOUT bij bouwen installer!
) else (
    echo Installer klaar: %~dp0installer_output\TranscribeApp-Setup.exe
)

:klaar
echo.
echo ================================================
echo   Klaar: %APPNAAM% v!NIEUW!
echo   Lokale exe : %~dp0dist\transcribe-nlen.exe
echo   Installer  : %~dp0installer_output\TranscribeApp-Setup.exe (indien gebouwd)
echo   GitHub     : https://github.com/richardvanderveer/python-tools/actions
echo ================================================
echo.
pause
