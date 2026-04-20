"""
workers/vector_worker.py

QThread workers for VectorMemory operations triggered by the UI.

THREADING RULE: VectorMemory operations (initialisation, rollback) are
blocking and MUST NOT run on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from llm_engine.vector_memory import VectorMemory


class VectorInitWorker(QThread):
    """Initialises VectorMemory off the main thread.

    Necessary because VectorMemory loads the SentenceTransformers model,
    which is a heavy CPU/IO operation.

    Signals:
        ready(object):       The initialised VectorMemory instance.
        error_occurred(str): Human-readable error message.
        status_update(str):  Progress message (e.g. "Loading AI models...").
    """

    ready = Signal(object)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(self, vector_dir: str) -> None:
        super().__init__()
        self._vector_dir = vector_dir

    def run(self) -> None:
        try:
            from pathlib import Path
            self.status_update.emit("Checking model cache...")
            Path(self._vector_dir).mkdir(parents=True, exist_ok=True)
            self.status_update.emit("Loading AI embedding model (this may take time at first launch)...")
            vm = VectorMemory(persist_dir=self._vector_dir)
            self.status_update.emit("VectorMemory ready.")
            self.ready.emit(vm)
        except Exception as exc:
            self.error_occurred.emit(f"VectorMemory init failed: {exc}")


class VectorWorker(QThread):
    """Executes VectorMemory.rollback() off the main thread.

    Signals:
        rollback_complete(int): Count of deleted chunks.
        error_occurred(str):    Human-readable error message.
        status_update(str):     Short status for QStatusBar.

    Args:
        vector_memory:   The VectorMemory instance shared with the session.
        save_id:         The save whose future chunks are erased.
        target_turn_id:  All chunks with turn_id > this are deleted.
    """

    rollback_complete = Signal(int)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(
        self,
        vector_memory: VectorMemory,
        save_id: str,
        target_turn_id: int,
    ) -> None:
        super().__init__()
        self._vector_memory = vector_memory
        self._save_id = save_id
        self._target_turn_id = target_turn_id

    def run(self) -> None:
        """Execute the rollback.  Never raises."""
        try:
            self.status_update.emit("Erasing future memories...")
            count = self._vector_memory.rollback(self._save_id, self._target_turn_id)
            self.rollback_complete.emit(count)
            self.status_update.emit(f"Memory rolled back ({count} chunks removed).")
        except Exception as exc:
            self.error_occurred.emit(f"VectorMemory rollback failed: {exc}")


class VectorEmbedWorker(QThread):
    """Embeds a single text chunk off the main thread.

    Used when switching variants to update the vector memory for that turn.

    Signals:
        embed_complete(str): The generated document ID.
        error_occurred(str): Human-readable error message.
        status_update(str):  Short status for QStatusBar.
    """

    embed_complete = Signal(str)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(
        self,
        vector_memory: VectorMemory,
        save_id: str,
        turn_id: int,
        text: str,
        chunk_type: str = "narrative",
    ) -> None:
        super().__init__()
        self._vector_memory = vector_memory
        self._save_id = save_id
        self._turn_id = turn_id
        self._text = text
        self._chunk_type = chunk_type

    def run(self) -> None:
        try:
            self.status_update.emit(f"Updating memory for turn {self._turn_id}...")
            doc_id = self._vector_memory.embed_chunk(
                self._save_id, self._turn_id, self._text, self._chunk_type
            )
            self.embed_complete.emit(doc_id)
            self.status_update.emit(f"Turn {self._turn_id} memory updated.")
        except Exception as exc:
            self.error_occurred.emit(f"VectorMemory embed failed: {exc}")

