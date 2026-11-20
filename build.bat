@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "PAUSE=pause"
if defined CI set "PAUSE=ver >nul"

echo ============================================================
echo   JARVIS BUILD
echo   1. installs the build tools   2. builds dist\Jarvis\Jarvis.exe
echo   3. compiles installer_output\JarvisSetup-^<version^>.exe
echo ============================================================
echo.

REM ---------- Python ----------
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if not defined PY (
    echo Python 3.10+ is needed to BUILD Jarvis ^(the finished installer does not need it^).
    echo Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    %PAUSE% & exit /b 1
)

REM ---------- version from config.py ----------
for /f "delims=" %%v in ('%PY% -c "import config; print(config.VERSION)"') do set "VER=%%v"
if not defined VER ( echo Couldn't read VERSION from config.py & %PAUSE% & exit /b 1 )
echo [..] Building Jarvis %VER%

REM ---------- isolated build environment ----------
if not exist ".build-venv\Scripts\python.exe" (
    echo [..] Creating build environment
    %PY% -m venv .build-venv || ( echo venv creation failed & %PAUSE% & exit /b 1 )
)
set "VPY=.build-venv\Scripts\python.exe"
%VPY% -m pip install --quiet --upgrade pip
%VPY% -m pip install --quiet -r requirements.txt pyinstaller || ( echo Dependency install failed & %PAUSE% & exit /b 1 )
echo [OK] Build tools ready

REM ---------- tests first: never package a broken build ----------
%VPY% -m unittest discover -s tests -q || ( echo Tests failed - not building. & %PAUSE% & exit /b 1 )
echo [OK] Tests pass

REM ---------- exe ----------
%VPY% installer\make_version_info.py %VER% || ( %PAUSE% & exit /b 1 )
if exist dist\Jarvis rmdir /s /q dist\Jarvis
%VPY% -m PyInstaller installer\jarvis.spec --noconfirm --clean --log-level WARN --distpath dist --workpath build
if not exist "dist\Jarvis\Jarvis.exe" ( echo PyInstaller build failed - scroll up. & %PAUSE% & exit /b 1 )
echo [OK] dist\Jarvis\Jarvis.exe

REM ---------- installer ----------
set "ISCC="
for %%p in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
    if not defined ISCC if exist %%p set "ISCC=%%~p"
)
if not defined ISCC (
    echo [..] Inno Setup not found - installing it with winget
    winget install -e --id JRSoftware.InnoSetup --scope user --silent --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    echo Inno Setup 6 is needed for the installer: https://jrsoftware.org/isdl.php
    echo dist\Jarvis\Jarvis.exe works on its own in the meantime.
    %PAUSE% & exit /b 1
)
"%ISCC%" /Qp /DAppVersion=%VER% installer\jarvis.iss || ( echo Installer compile failed & %PAUSE% & exit /b 1 )

echo.
echo ============================================================
echo   Done:  installer_output\JarvisSetup-%VER%.exe
echo ============================================================
%PAUSE%
