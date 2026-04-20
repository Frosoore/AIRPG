"""
database/checkpoint.py

Checkpoint and rewind management for AIRPG saves.

The CheckpointManager exposes the rewind primitive (deleting future events
and rebuilding the State_Cache), a save listing helper, and the destructive
Hardcore-mode save deletion.
"""

import os
import shutil
import sqlite3
from pathlib import Path

from database.schema import get_connection
from database.event_sourcing import EventSourcer


class CheckpointManager:
    """Manages save checkpoints, rewinds, and Hardcore deletion for one universe.

    Args:
        db_path: Filesystem path to an existing universe .db file created
                 by database.schema.create_universe_db().
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._event_sourcer = EventSourcer(db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rewind(self, save_id: str, target_turn_id: int) -> dict[str, int]:
        """Revert a save to its state at target_turn_id.

        Steps:
          1. Count how many future events will be deleted (for the summary).
          2. DELETE all Event_Log rows where turn_id > target_turn_id.
          3. Rebuild State_Cache from the surviving events.

        Args:
            save_id:        The save to rewind.
            target_turn_id: The turn to revert to (inclusive).  All events
                            with turn_id strictly greater than this value are
                            permanently removed.

        Returns:
            A summary dict: {"deleted_events": int, "rebuilt_to_turn": int}.

        Raises:
            sqlite3.Error: On any database failure.
        """
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM Event_Log
                WHERE save_id = ? AND turn_id > ?;
                """,
                (save_id, target_turn_id),
            ).fetchone()
            deleted_count: int = row[0]

            conn.execute(
                """
                DELETE FROM Event_Log
                WHERE save_id = ? AND turn_id > ?;
                """,
                (save_id, target_turn_id),
            )
            
            # Clean up snapshots and timeline entries for future turns
            conn.execute(
                "DELETE FROM Snapshots WHERE save_id = ? AND turn_id > ?;",
                (save_id, target_turn_id)
            )
            conn.execute(
                "DELETE FROM Timeline WHERE save_id = ? AND turn_id > ?;",
                (save_id, target_turn_id)
            )
            
            conn.commit()

        self._event_sourcer.rebuild_state_cache(save_id, up_to_turn_id=target_turn_id)

        return {"deleted_events": deleted_count, "rebuilt_to_turn": target_turn_id}

    def list_checkpoints(self, save_id: str) -> list[int]:
        """Return the distinct turn IDs present in Event_Log for a save, ascending.

        This list represents the turns the player could rewind to.  The UI
        can use it to populate a "rewind to turn …" selector.

        Args:
            save_id: The save whose checkpoint turns are requested.

        Returns:
            Sorted list of unique turn_id integers.  Empty list if the save
            has no recorded events.

        Raises:
            sqlite3.Error: On any database failure.
        """
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT turn_id FROM Event_Log
                WHERE save_id = ?
                ORDER BY turn_id ASC;
                """,
                (save_id,),
            ).fetchall()
        return [row[0] for row in rows]

    def delete_save(self, save_id: str, universe_dir: str) -> None:
        """Irrevocably delete a save and its associated universe directory.

        Intended exclusively for Hardcore mode upon player death.  This method:
          1. Removes the save row from the database (cascades to Event_Log, etc).
          2. Attempts to delete the universe_dir from the filesystem.

        Args:
            save_id:      The save to erase from the database.
            universe_dir: Absolute path to the universe directory to delete.

        Raises:
            OSError: If the directory cannot be deleted after multiple retries.
            FileNotFoundError: If universe_dir does not exist.
            sqlite3.Error: On any database failure.
        """
        dir_path = Path(universe_dir)
        if not dir_path.exists():
            # If the dir is missing, we still want to clean up the DB
            pass

        # 1. Remove from database (cascades to Event_Log and State_Cache)
        # We do this FIRST because if the DB delete fails, we shouldn't delete files.
        with get_connection(self._db_path) as conn:
            conn.execute("DELETE FROM Saves WHERE save_id = ?;", (save_id,))
            conn.commit()

        # 2. Irrevocably delete the filesystem directory
        if dir_path.exists():
            import time
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    shutil.rmtree(str(dir_path))
                    break
                except OSError as exc:
                    if attempt == max_retries - 1:
                        raise OSError(
                            f"Failed to delete universe directory after {max_retries} attempts: {exc}. "
                            "Some files may be locked by another process."
                        ) from exc
                    time.sleep(0.5) # Wait for locks to release
