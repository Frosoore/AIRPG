#!/usr/bin/env bash
# ============================================================
# AIRPG — Test Runner (Zero-config fallback)
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🧪 AIRPG Test Suite Runner"
echo "--------------------------"

# Try VENV first
USE_USER_PIP=false
if python3 -m venv .venv 2>/dev/null; then
    echo "Using virtual environment (.venv)..."
    # shellcheck source=/dev/null
    source .venv/bin/activate
    PIP_CMD="pip"
else
    echo "Warning: python3-venv not found. Falling back to system python with --user..."
    USE_USER_PIP=true
    PIP_CMD="pip3"
fi

# Install requirements
echo "Verifying dependencies..."
if [ "$USE_USER_PIP" = true ]; then
    $PIP_CMD install -q --user -r requirements.txt -r requirements-dev.txt 2>/dev/null || true
else
    $PIP_CMD install -q --upgrade pip
    $PIP_CMD install -q -r requirements.txt -r requirements-dev.txt
fi

# Determine if we can run GUI tests (Qt)
PYTEST_CMD="python3 -m pytest"
if command -v xvfb-run &>/dev/null; then
    RUNNER="xvfb-run $PYTEST_CMD"
else
    RUNNER="$PYTEST_CMD"
fi

echo "Running tests..."
# Pass all arguments to pytest (e.g., ./test.sh tests/test_llm_base.py)
$RUNNER -v "$@"
