@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0src\backend\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [OpenLong] Backend virtualenv not found: "%PYTHON_EXE%"
    echo [OpenLong] Please install dependencies first.
    exit /b 1
)

if "%~1"=="" (
    echo [OpenLong] Starting default dev mode...
    "%PYTHON_EXE%" "%~dp0start.py" --reload --frontend
) else (
    echo [OpenLong] Starting with custom args: %*
    "%PYTHON_EXE%" "%~dp0start.py" %*
)
