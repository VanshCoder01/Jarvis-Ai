@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   JARVIS BUILD - fully automatic
echo   Checks for Python, installs everything needed, builds
echo   Jarvis.exe, and makes an installer if it can.
echo ============================================================
echo.

REM ---------- 1. Find Python ----------
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY ( py --version >nul 2>&1 && set PY=py )

if not defined PY (
    echo Python isn't installed. Trying to install it automatically...
    winget --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo Couldn't auto-install - winget isn't available on this PC.
        echo Install Python 3.12 manually from python.org, TICK
        echo "Add python.exe to PATH" during setup, then re-run this file.
        echo.
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    echo.
    echo Python installed. CLOSE THIS WINDOW and run this file again
    echo so Windows picks up the new PATH.
    echo.
    pause
    exit /b 0
)
echo [OK] Found Python: %PY%

REM ---------- 2. Dependencies ----------
echo.
echo Installing dependencies (this can take a few minutes)...
%PY% -m pip install --upgrade pip >nul 2>&1
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency install failed - scroll up for the real error.
    pause
    exit /b 1
)
%PY% -m pip install pyinstaller
echo [OK] Dependencies ready

REM ---------- 3. Build the exe ----------
echo.
echo Building Jarvis.exe...
%PY% -m PyInstaller --onefile --noconsole --name Jarvis --icon=jarvis.ico ^
    --add-data "index.html;." ^
    --hidden-import=google.genai ^
    --hidden-import=openai ^
    --hidden-import=anthropic ^
    --hidden-import=pyscreeze ^
    --hidden-import=pymsgbox ^
    --hidden-import=pytweening ^
    --hidden-import=pygetwindow ^
    --hidden-import=mouseinfo ^
    --hidden-import=win32timezone ^
    main.py

if not exist "dist\Jarvis.exe" (
    echo.
    echo ============================================================
    echo  BUILD FAILED - retrying WITHOUT --noconsole so you can
    echo  actually see what went wrong when you run it.
    echo ============================================================
    %PY% -m PyInstaller --onefile --name Jarvis --icon=jarvis.ico ^
        --add-data "index.html;." ^
        --hidden-import=google.genai --hidden-import=openai --hidden-import=anthropic ^
        --hidden-import=pyscreeze --hidden-import=pymsgbox --hidden-import=pytweening ^
        --hidden-import=pygetwindow --hidden-import=mouseinfo --hidden-import=win32timezone ^
        main.py
    if not exist "dist\Jarvis.exe" (
        echo Still failed. Scroll up for the actual error and send it over.
        pause
        exit /b 1
    )
    echo Built a debug version - run dist\Jarvis.exe to see the error.
    pause
    exit /b 0
)

echo.
echo [OK] dist\Jarvis.exe is ready - you can run it right now.

REM ---------- 4. Installer (optional) ----------
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if not exist %ISCC% (
    echo.
    echo Inno Setup not found - trying to install it automatically...
    winget --version >nul 2>&1
    if not errorlevel 1 (
        winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements
        set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if not exist !ISCC! set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
    )
)

if exist %ISCC% (
    echo Building the installer...
    %ISCC% jarvis_installer.iss
    echo.
    echo ============================================================
    echo  DONE. installer_output\JarvisSetup.exe
    echo  Double-click it to install Jarvis properly, with a
    echo  Desktop shortcut and an uninstaller.
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo  DONE. dist\Jarvis.exe works on its own - just double-click.
    echo  (No installer built: Inno Setup isn't installed. It's
    echo  optional - only needed for Start Menu/Desktop shortcuts.)
    echo ============================================================
)

echo.
pause
