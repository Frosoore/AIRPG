@echo off
REM ============================================================
# Axiom AI — Windows test runner
REM ============================================================
SETLOCAL

cd /d "%~dp0"

echo 🧪 Axiom AI Test Suite Runner
echo --------------------------

REM Virtual environment check
set VENV_DIR=.venv

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Virtual environment not found. Please run run.bat first.
    pause
    exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"

echo Verifying dependencies...
python -m pip install -q -r requirements.txt -r requirements-dev.txt

echo Running tests...
python -m pytest -v %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo Some tests failed.
    pause
)

ENDLOCAL
