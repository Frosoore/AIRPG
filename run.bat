@echo off
REM ============================================================
# AIRPG — Windows launch script
REM ============================================================
SETLOCAL

cd /d "%~dp0"

echo --- AIRPG System Check ---

REM Check for python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: python not found.
    echo Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM Check python version
python -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python 3.10+ required.
    pause
    exit /b 1
)

REM Virtual environment
set VENV_DIR=.venv

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Creating virtual environment in %VENV_DIR%...
    if exist "%VENV_DIR%" rd /s /q "%VENV_DIR%"
    python -m venv %VENV_DIR%
)

call "%VENV_DIR%\Scripts\activate.bat"

echo Verifying Python dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Running environment validation...
python debug/startup_check.py

echo Starting AIRPG...
python main.py %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo AIRPG exited with an error.
    pause
)

ENDLOCAL
