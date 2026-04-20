#!/usr/bin/env bash
# ============================================================
# AIRPG — Ubuntu/Linux launch script
# Usage: bash run.sh
#        chmod +x run.sh && ./run.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Prerequisites check ──────────────────────────────────────
echo "--- AIRPG System Check ---"

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    echo "Please install Python 3.10+ and venv:"
    echo "  sudo apt update && sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# Check for venv module specifically (common pitfall on Ubuntu)
if ! python3 -m venv --help &>/dev/null; then
    echo "ERROR: python3-venv is missing."
    echo "Please install it with:"
    echo "  sudo apt update && sudo apt install python3-venv"
    exit 1
fi

# Check for common Qt/PySide6 system dependencies on Linux
MISSING_LIBS=()
check_lib() {
    if ! ldconfig -p | grep -q "$1"; then
        MISSING_LIBS+=("$2")
    fi
}

# libxcb-cursor0 is the most frequent missing library for PySide6 on Ubuntu
if command -v ldconfig &>/dev/null; then
    if ! ldconfig -p | grep -q "libxcb-cursor.so.0"; then
        echo "Warning: libxcb-cursor0 might be missing (required for PySide6 GUI)."
    fi
fi

PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PYTHON_VER="${PYTHON_MAJOR}.${PYTHON_MINOR}"

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required (found $PYTHON_VER)."
    exit 1
fi

echo "Using Python $PYTHON_VER"

# ── Virtual environment ──────────────────────────────────────
VENV_DIR=".venv"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── Dependency Installation ──────────────────────────────────
echo "Verifying Python dependencies (this may take a minute on first run)..."
# We removed -q to ensure the user sees progress and doesn't assume a hang.
pip install --upgrade pip
pip install -r requirements.txt

# ── Startup Validation ───────────────────────────────────────
# Run a quick headless check of the environment before launching the GUI
echo "Running environment validation..."
python3 debug/startup_check.py

# ── Launch ───────────────────────────────────────────────────
echo "Starting AIRPG..."
# Use exec to replace the shell process with the python process
exec python3 main.py "$@"
