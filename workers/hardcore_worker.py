"""
workers/hardcore_worker.py

Hardcore mode deletion worker for Axiom AI.

Executes the safe, deterministic file-lock release and irrevocable deletion
sequence for Hardcore saves after a Player_Death event.

Critical design constraint
---------------------------
This worker receives ONLY filesystem paths — NOT live Python objects.
All SQLite connections and ChromaDB handles must be destroyed BEFORE this
worker starts (done in TabletopView._start_hardcore_deletion()).  The
main thread calls gc.collect() to finalize connection objects, then starts
this worker.  This eliminates all race conditions between object lifetime
and file deletion.

Deletion sequence
-----------------
1. Flush and truncate WAL files so SQLite releases sidecar file locks.
2. Delete the save row and its Event_Log / State_Cache entries.
3. Probe for remaining OS-level file locks with retries.
4. Delete the VectorMemory (ChromaDB) directory for this save.
5. If the .db file has no other saves: delete the .db file itself.
6. Emit deletion_complete or deletion_failed.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal


_MAX_LOCK_RETRIES: int = 3
_LOCK_RETRY_DELAY: float = 0.2  # seconds between retries


class HardcoreWorker(QThread):
    """Performs the irreversible Hardcore save deletion off the main thread.

    Signals:
        deletion_complete():     Emitted on successful deletion.
        deletion_failed(str):    Emitted with a human-readable reason on failure.
        status_update(str):      Short status for QStatusBar.

    Args:
        db_path:           Path to the universe .db file.
        save_id:           The save to delete.
        universe_dir:      Directory containing the .db file.
        vector_persist_dir: ChromaDB directory for this save.
    """

    deletion_complete = Signal()
    deletion_failed = Signal(str)
    status_update = Signal(str)

    def __init__(
        self,
        db_path: str,
        save_id: str,
        universe_dir: str,
        vector_persist_dir: str,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._save_id = save_id
        self._universe_dir = universe_dir
        self._vector_persist_dir = vector_persist_dir

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full deletion sequence.  Never raises."""
        try:
            self._execute()
        except Exception as exc:
            self.deletion_failed.emit(
                f"Unexpected error during Hardcore deletion: {exc}"
            )

    # ------------------------------------------------------------------
    # Internal sequence
    # ------------------------------------------------------------------

    def _execute(self) -> None:
        """The deterministic deletion sequence."""
        self.status_update.emit("Sealing fate…")

        # Fail-safe: Create an auto-backup before permanent deletion
        from database.backup_manager import create_auto_backup
        create_auto_backup(self._db_path, "hardcore_death")

        # Step 1 — Flush and truncate WAL files
        # This converts the database from WAL mode back to rollback journal,
        # checkpointing all WAL data and deleting the .db-wal and .db-shm
        # sidecar files.  After this call, no WAL file locks remain.
        try:
            self._flush_wal(self._db_path)
        except sqlite3.Error as exc:
            # WAL flush failure is non-fatal if sidecar files don't exist
            self.status_update.emit(f"WAL flush warning (non-fatal): {exc}")

        # Step 2 — Delete the save and its events from the database
        self.status_update.emit("Erasing save data…")
        try:
            self._delete_save_rows(self._db_path, self._save_id)
        except sqlite3.Error as exc:
            self.deletion_failed.emit(
                f"Could not delete save from database: {exc}"
            )
            return

        # Step 3 — Probe for remaining file locks with retries
        self.status_update.emit("Releasing file locks…")
        locked_files = self._find_locked_files(self._db_path)
        if locked_files:
            self.deletion_failed.emit(
                f"Cannot delete save: files are still locked by another process.\n"
                f"Locked: {', '.join(locked_files)}\n\n"
                "Close any programs accessing these files, then restart Axiom AI."
            )
            return

        # Step 4 — Delete VectorMemory directory for this save
        self.status_update.emit("Erasing memories…")
        vdir = Path(self._vector_persist_dir)
        if vdir.exists():
            shutil.rmtree(str(vdir), ignore_errors=True)

        # Step 5 — Delete the .db file if no other saves remain
        try:
            remaining = self._count_remaining_saves(self._db_path)
        except sqlite3.Error:
            remaining = 1  # Assume others exist if we can't check

        if remaining == 0:
            # Last save gone — delete the universe .db file entirely
            db = Path(self._db_path)
            if db.exists():
                try:
                    db.unlink()
                except OSError as exc:
                    self.deletion_failed.emit(
                        f"Could not delete universe file: {exc}"
                    )
                    return

        self.deletion_complete.emit()
        self.status_update.emit("Save permanently deleted.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flush_wal(db_path: str) -> None:
        """Checkpoint and truncate the WAL, then switch to rollback journal.

        This ensures the .db-wal and .db-shm sidecar files are removed and
        all file locks associated with WAL mode are released.

        Args:
            db_path: Path to the universe .db file.

        Raises:
            sqlite3.Error: On connection or pragma failure.
        """
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.execute("PRAGMA journal_mode=DELETE;")

    @staticmethod
    def _delete_save_rows(db_path: str, save_id: str) -> None:
        """Remove the save row and all its associated events from the database.

        Args:
            db_path:  Path to the universe .db file.
            save_id:  The save to delete.

        Raises:
            sqlite3.Error: On any database failure.
        """
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            conn.execute("PRAGMA foreign_keys=ON;")
            # Step A: Delete modifiers BEFORE clearing the cache subquery source
            conn.execute(
                "DELETE FROM Active_Modifiers WHERE entity_id IN ("
                "  SELECT DISTINCT entity_id FROM State_Cache WHERE save_id = ?"
                ");",
                (save_id,),
            )
            # Step B: Delete events and cache
            conn.execute(
                "DELETE FROM Event_Log WHERE save_id = ?;", (save_id,)
            )
            conn.execute(
                "DELETE FROM State_Cache WHERE save_id = ?;", (save_id,)
            )
            # Step C: Delete the save itself
            conn.execute(
                "DELETE FROM Saves WHERE save_id = ?;", (save_id,)
            )
            conn.commit()

    def _find_locked_files(self, db_path: str) -> list[str]:
        """Probe for locked files associated with the database.

        Attempts an exclusive open on the .db and any WAL/SHM sidecars.
        Retries up to _MAX_LOCK_RETRIES times with _LOCK_RETRY_DELAY seconds
        between attempts.

        Args:
            db_path: Path to the universe .db file.

        Returns:
            List of file paths that are still locked.  Empty = all clear.
        """
        candidates = [db_path]
        for suffix in (".db-wal", ".db-shm"):
            sidecar = db_path + suffix if not db_path.endswith(".db") else db_path[:-3] + suffix
            if Path(sidecar).exists():
                candidates.append(sidecar)

        for attempt in range(_MAX_LOCK_RETRIES):
            locked = [p for p in candidates if not self._probe_lock(p)]
            if not locked:
                return []
            if attempt < _MAX_LOCK_RETRIES - 1:
                time.sleep(_LOCK_RETRY_DELAY)

        return locked

    @staticmethod
    def _probe_lock(path: str) -> bool:
        """Attempt to open a file exclusively.

        Args:
            path: File path to probe.

        Returns:
            True if the file can be opened exclusively (no lock).
            False if the file is locked by another process.
        """
        if not Path(path).exists():
            return True  # File gone = no lock
        try:
            fd = os.open(path, os.O_RDWR | os.O_EXCL)
            os.close(fd)
            return True
        except OSError:
            return False

    @staticmethod
    def _count_remaining_saves(db_path: str) -> int:
        """Count how many saves still exist in the database.

        Args:
            db_path: Path to the universe .db file.

        Returns:
            Number of remaining save rows.
        """
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            row = conn.execute("SELECT COUNT(*) FROM Saves;").fetchone()
        return int(row[0]) if row else 0
