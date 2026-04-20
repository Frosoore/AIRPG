"""
core/logger.py

Centralised logging for AIRPG.
Provides a unified logger that writes to both console and a persistent file.
"""

import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

_LOG_DIR = Path.home() / ".cache" / "AIRPG"
_LOG_FILE = _LOG_DIR / "airpg.log"

def setup_logger(name: str = "AIRPG") -> logging.Logger:
    """Initialize and return the global AIRPG logger."""
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if already setup
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.DEBUG)
    
    # 1. Console Handler (INFO level)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter("%(levelname)s: %(message)s")
    console.setFormatter(console_fmt)
    logger.addHandler(console)
    
    # 2. File Handler (DEBUG level, Rotating)
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_FILE, maxBytes=1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
        )
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)
    except OSError:
        # Fallback if file logging is impossible
        print(f"Warning: Could not initialize file logging at {_LOG_FILE}", file=sys.stderr)
        
    return logger

# Singleton instance for easy access
logger = setup_logger()
