@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Building JarvisInstaller.exe
echo   This is the file you upload to GitHub Releases / share.
echo   Anyone who runs it gets Jarvis installed automatically.
echo ============================================================
echo.

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Building...
pyinstaller --onefile --noconsole --name JarvisInstaller --icon=jarvis.ico JarvisInstaller.py

if not exist "dist\JarvisInstaller.exe" (
    echo.
    echo Build failed - scroll up for the error.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   dist\JarvisInstaller.exe is ready.
echo.
echo   IMPORTANT: it downloads whatever is on your GitHub 'main'
echo   branch. Push your current files first, or people will
echo   install an old version.
echo ============================================================
echo.
pause
