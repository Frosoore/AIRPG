"""
database/backup_manager.py

Utility for automated Axiom AI database backups before destructive operations.
"""

import shutil
from datetime import datetime
from pathlib import Path
from core.logger import logger

def create_auto_backup(db_path: str, reason: str) -> str | None:
    """Create a timestamped backup of the universe database.

    Copies the .db file to an 'auto_backups' subdirectory within the
    same directory as the database.

    Args:
        db_path: Absolute path to the .db file.
        reason:  Short string identifying why the backup was triggered
                 (e.g., 'rewind', 'hardcore_death').

    Returns:
        The path to the created backup file, or None if it failed.
    """
    try:
        source_path = Path(db_path)
        if not source_path.exists():
            logger.error(f"Backup failed: Source database not found at {db_path}")
            return None

        # Create auto_backups dir next to the DB
        backup_dir = source_path.parent / "auto_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename: 20231027_153000_rewind_myuniverse.db
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_name = source_path.name
        backup_filename = f"{timestamp}_{reason}_{db_name}"
        backup_path = backup_dir / backup_filename

        # Copy the main DB file
        shutil.copy2(source_path, backup_path)
        
        # Also try to copy WAL/SHM if they exist (though WAL should be checkpointed usually)
        for suffix in ["-wal", "-shm"]:
            aux_file = source_path.with_name(source_path.name + suffix)
            if aux_file.exists():
                shutil.copy2(aux_file, backup_path.with_name(backup_filename + suffix))

        logger.info(f"Automated backup created: {backup_path} (Reason: {reason})")
        return str(backup_path)

    except Exception as e:
        logger.error(f"Failed to create automated backup for {db_path}: {e}")
        return None
