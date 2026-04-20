"""
workers/chronicler_worker.py

QThread worker for the Chronicler world macro-simulation.

Runs ChroniclerEngine.run() off the main thread so the UI never blocks
during world state updates.

THREADING RULE: All LLM calls and SQLite writes for world simulation
happen here — never on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.chronicler import ChroniclerEngine, ChroniclerResult


class ChroniclerWorker(QThread):
    """Executes a Chronicler world-simulation cycle off the main thread.

    Signals:
        chronicle_complete(object): The ChroniclerResult dataclass instance.
        error_occurred(str):        Human-readable error message.
        status_update(str):         Short message for QStatusBar.

    Args:
        chronicler:  The session's ChroniclerEngine instance.
        save_id:     The active save identifier.
        turn_id:     The current turn number (used for Event_Log entries).
        temperature: Sampling temperature (0.0 to 1.0).
        top_p:       Nucleus sampling parameter (0.0 to 1.0).
    """

    chronicle_complete = Signal(object)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(
        self,
        chronicler: ChroniclerEngine,
        save_id: str,
        turn_id: int,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> None:
        super().__init__()
        self._chronicler = chronicler
        self._save_id = save_id
        self._turn_id = turn_id
        self._temperature = temperature
        self._top_p = top_p

    def run(self) -> None:
        """Execute the Chronicler cycle.  Never raises."""
        try:
            self.status_update.emit("Chronicler: simulating world…")
            result: ChroniclerResult = self._chronicler.run(
                self._save_id, self._turn_id,
                temperature=self._temperature,
                top_p=self._top_p
            )
            self.chronicle_complete.emit(result)
            n = result.events_appended
            msg = f"World updated ({n} change{'s' if n != 1 else ''})."
            self.status_update.emit(msg)
        except Exception as exc:
            # ChroniclerEngine.run() is already hardened; this is a last resort
            self.error_occurred.emit(f"Chronicler unexpected error: {exc}")
            self.status_update.emit("Chronicler error.")
