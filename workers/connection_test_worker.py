"""
workers/connection_test_worker.py

Lightweight QThread worker for testing LLM backend connectivity.

Used exclusively by the Settings dialog "Test Connection" buttons.
Calls LLMBackend.is_available() off the main thread and emits the result.

THREADING RULE: is_available() may perform a network call — it MUST NOT
run on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from llm_engine.base import LLMBackend


class ConnectionTestWorker(QThread):
    """Tests whether an LLM backend is reachable.

    Signals:
        result_ready(bool, str): (is_available, human-readable message).

    Args:
        llm: The LLMBackend instance to test.
    """

    result_ready = Signal(bool, str)

    def __init__(self, llm: LLMBackend) -> None:
        super().__init__()
        self._llm = llm

    def run(self) -> None:
        """Call is_available() and emit result_ready.  Never raises."""
        try:
            available = self._llm.is_available()
            if available:
                self.result_ready.emit(True, "✓ Connected successfully.")
            else:
                self.result_ready.emit(False, "✗ Backend is unreachable.")
        except Exception as exc:
            self.result_ready.emit(False, f"✗ Error: {exc}")
