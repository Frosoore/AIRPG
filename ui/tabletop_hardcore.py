"""
ui/tabletop_hardcore.py

Hardcore mode mixin for TabletopView.

Provides the Player_Death detection and safe deletion sequence as a
mixin class so tabletop_view.py stays under 500 lines.

THREADING RULE: _start_hardcore_deletion() runs entirely on the main thread
to destroy Python objects before HardcoreWorker starts.  HardcoreWorker
then performs all I/O off the main thread.
"""

from __future__ import annotations

import gc
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QMessageBox

from workers.db_helpers import load_saves
from workers.hardcore_worker import HardcoreWorker


class HardcoreMixin:
    """Mixin that adds Hardcore mode logic to TabletopView.

    Requires the host class to have:
        _db_path, _save_id, _narrative_worker, _chronicler_worker,
        _db_worker, _vector_worker, _arbitrator, _chronicler, _llm,
        _vector_memory, _chat, _main_window, _hardcore_worker
    """

    def _check_for_player_death(self, result: object) -> None:
        """Check triggered rules for Player_Death and handle Hardcore mode.

        Args:
            result: ArbitratorResult from the completed turn.
        """
        triggered = getattr(result, "triggered_rules", [])
        death_triggered = any(
            action.get("type") == "trigger_event"
            and "player_death" in str(action.get("event", "")).lower()
            for action in triggered
        )
        if not death_triggered:
            return

        saves = load_saves(self._db_path)
        save_info = next(
            (s for s in saves if s["save_id"] == self._save_id), None
        )
        if not save_info or save_info.get("difficulty") != "Hardcore":
            return  # Normal mode - no automatic deletion

        # Hardcore death confirmed
        self._chat.set_send_enabled(False)
        reply = QMessageBox.critical(
            self,
            "You Died",
            "<b>You have fallen.</b><br><br>"
            "This is <b>Hardcore mode</b>. Your save will now be "
            "<b>permanently and irrevocably deleted</b>.<br><br>"
            "There is no coming back.",
            QMessageBox.Ok,
        )
        if reply == QMessageBox.Ok:
            self._start_hardcore_deletion()

    def _start_hardcore_deletion(self) -> None:
        """Safely release all connections and start HardcoreWorker.

        CRITICAL SEQUENCE (must run on the main thread):
          1. Stop all running workers (quit + wait).
          2. Set all backend references to None - allows Python GC to close
             sqlite3.Connection objects held by EventSourcer/ModifierProcessor.
          3. Call gc.collect() to force immediate finalisation of those objects,
             releasing OS-level SQLite file locks.
          4. Instantiate HardcoreWorker with paths only (no live objects) and
             start it on a background thread.
        """
        self._main_window.on_status_update("Releasing connections...")

        # Step 1: Stop all running workers
        for worker in [
            self._narrative_worker,
            self._chronicler_worker,
            self._db_worker,
            self._vector_worker,
        ]:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(3000)

        # Step 2: Destroy backend object references
        self._arbitrator = None
        self._chronicler = None
        self._llm = None
        self._vector_memory = None

        # Step 3: Force GC - finalises EventSourcer/ModifierProcessor and
        # their internal sqlite3.Connection objects, releasing file handles
        gc.collect()

        # Step 4: Start HardcoreWorker (paths only - no live Python objects)
        vector_persist_dir = str(
            Path.home() / "AIRPG" / "vector" / self._save_id
        )
        self._hardcore_worker = HardcoreWorker(
            db_path=self._db_path,
            save_id=self._save_id,
            universe_dir=str(Path(self._db_path).parent),
            vector_persist_dir=vector_persist_dir,
        )
        self._hardcore_worker.deletion_complete.connect(
            self._on_hardcore_deletion_complete
        )
        self._hardcore_worker.deletion_failed.connect(
            self._on_hardcore_deletion_failed
        )
        self._hardcore_worker.status_update.connect(
            self._main_window.on_status_update
        )
        self._hardcore_worker.start()

    @Slot()
    def _on_hardcore_deletion_complete(self) -> None:
        """Navigate to Hub after successful deletion."""
        QMessageBox.information(
            self,
            "Save Deleted",
            "Your Hardcore save has been <b>permanently erased</b>.<br><br>"
            "There is no coming back.",
        )
        self._main_window.show_hub()

    @Slot(str)
    def _on_hardcore_deletion_failed(self, reason: str) -> None:
        """Show deletion failure and re-enable navigation."""
        QMessageBox.critical(
            self,
            "Deletion Failed",
            f"<b>Could not delete the Hardcore save:</b><br><br>{reason}",
        )
        self._main_window.on_status_update(
            "Hardcore deletion failed - see error."
        )
