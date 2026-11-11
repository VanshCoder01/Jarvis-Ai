@echo off
cd /d "%~dp0"

set "PY_EXE=python"
where python >nul 2>&1
if %ERRORLEVEL% equ 0 goto :RUN

if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    goto :RUN
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :RUN
)
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=py"
    goto :RUN
)

:RUN
"%PY_EXE%" main.py
echo.
echo Jarvis stopped. Press any key to close this window.
pause >nul
