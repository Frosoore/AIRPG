"""
core/paths.py

Centralised path management for Axiom AI.
Ensures cross-platform compatibility by using OS-specific standard directories.
"""

import os
import sys
from pathlib import Path

def get_app_config_dir() -> Path:
    """Return the standard directory for application configuration files."""
    if sys.platform == "win32":
        # %APPDATA%\AxiomAI
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "AxiomAI"
    # Fallback/Linux/macOS: ~/.config/AxiomAI
    return Path.home() / ".config" / "AxiomAI"

def get_app_cache_dir() -> Path:
    """Return the standard directory for non-essential data (logs, etc)."""
    if sys.platform == "win32":
        # %LOCALAPPDATA%\AxiomAI
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "AxiomAI"
    # Fallback/Linux/macOS: ~/.cache/AxiomAI
    return Path.home() / ".cache" / "AxiomAI"

def get_app_data_dir() -> Path:
    """Return the standard directory for user-created content (universes, saves)."""
    # For AxiomAI, we keep universes in ~/AxiomAI to make them easy to find/backup for users
    return Path.home() / "AxiomAI"

# Shared Constants
CONFIG_DIR = get_app_config_dir()
CACHE_DIR = get_app_cache_dir()
DATA_DIR = get_app_data_dir()

# Specific Files/Subdirs
SETTINGS_FILE = CONFIG_DIR / "settings.json"
GLOBAL_DB_FILE = CONFIG_DIR / "global.db"
LOG_DIR = CACHE_DIR / "logs"
UNIVERSES_DIR = DATA_DIR / "universes"
VECTOR_DIR = DATA_DIR / "vector"
