@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Building JarvisSetup-v1.06.exe
echo   A proper Windows installer wizard - language select,
echo   licence, install location, shortcuts, uninstaller.
echo ============================================================
echo.

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if not exist %ISCC% (
    echo Inno Setup isn't installed. Trying winget...
    winget --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo winget isn't available. Download Inno Setup 6 manually:
        echo   https://jrsoftware.org/isdl.php
        echo Then run this file again.
        pause
        exit /b 1
    )
    winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements
    set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if not exist %ISCC% (
    echo Still can't find ISCC.exe. Install Inno Setup 6 and retry.
    pause
    exit /b 1
)

echo Compiling...
%ISCC% jarvis_installer.iss

if not exist "installer_output\JarvisSetup-v1.06.exe" (
    echo.
    echo Build failed - scroll up for the error.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   DONE:  installer_output\JarvisSetup-v1.06.exe
echo.
echo   That's the single file to upload to GitHub Releases.
echo   Running it gives the full wizard with language select.
echo ============================================================
echo.
pause
