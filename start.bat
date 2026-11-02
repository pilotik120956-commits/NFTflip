@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NFTflip

echo ============================================
echo   NFTflip - Telegram gift arbitrage bot
echo ============================================
echo.

set "PYTHON_EXE="
rem Prefer a real interpreter over the Microsoft Store alias.
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" set "PYTHON_EXE=%%D\python.exe"
)
if not defined PYTHON_EXE (
    for /d %%D in ("C:\Program Files\Python3*") do (
        if exist "%%D\python.exe" set "PYTHON_EXE=%%D\python.exe"
    )
)
if not defined PYTHON_EXE (
    where py >nul 2>nul && set "PYTHON_EXE=py -3"
)

if not defined PYTHON_EXE (
    echo Python 3.11+ was not found.
    where winget >nul 2>nul
    if errorlevel 1 (
        echo Please install Python 3.11+ from https://www.python.org/downloads/
        echo and run start.bat again.
        pause
        exit /b 1
    )
    echo Installing Python 3.12 with winget...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    set "PYTHON_EXE=py -3"
    for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
        if exist "%%D\python.exe" set "PYTHON_EXE=%%D\python.exe"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON_EXE% -m venv .venv
    if errorlevel 1 (
        echo Could not create .venv. Check that Python 3.11+ is installed.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\.deps-ok" (
    echo Installing dependencies. The first run can take a few minutes...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Dependency installation failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo ok> ".venv\.deps-ok"
)

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo.
    echo A new .env file was created.
    echo Paste your BOT_TOKEN from @BotFather into it, save, and run start.bat again.
    start notepad ".env"
    pause
    exit /b 1
)

python run.py %*

echo.
echo The bot has stopped.
pause
