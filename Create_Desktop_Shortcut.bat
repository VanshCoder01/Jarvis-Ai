@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Creating your Jarvis desktop app
echo ============================================================
echo.

REM Find pythonw.exe (the no-console version of python)
set PYW=
for /f "delims=" %%i in ('where pythonw 2^>nul') do set PYW=%%i
if not defined PYW (
    for /f "delims=" %%i in ('py -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set PYW=%%i
)
if not defined PYW (
    if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
)
if not defined PYW (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
)

if not defined PYW (
    echo Python not found. Run build_installer.bat first - it installs Python for you.
    pause
    exit /b 1
)
echo [OK] Found: %PYW%

REM Install dependencies if they're missing
echo.
echo Making sure dependencies are installed...
set "PY_CLI=%PYW:pythonw.exe=python.exe%"
"%PY_CLI%" -m pip install -r requirements.txt --quiet
echo [OK] Dependencies ready

REM Build the shortcut with PowerShell
echo.
echo Creating the Desktop shortcut...
powershell -NoProfile -Command ^
  "$s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Jarvis.lnk');" ^
  "$s.TargetPath='%PYW%';" ^
  "$s.Arguments='\"%~dp0main.py\"';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%~dp0jarvis.ico';" ^
  "$s.Description='Jarvis voice assistant';" ^
  "$s.Save()"

if errorlevel 1 (
    echo Couldn't create the shortcut. Send me the error above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   DONE - "Jarvis" is now on your Desktop with the icon.
echo   Double-click it. No console window, opens straight up.
echo.
echo   Want it in the Start Menu too? Right-click the Desktop
echo   icon - Pin to Start.
echo ============================================================
echo.
pause
