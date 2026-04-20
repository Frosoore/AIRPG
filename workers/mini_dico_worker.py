"""
workers/mini_dico_worker.py

QThread worker for the Mini-Dico (Lore Reference) encyclopedic queries.

Completely independent of NarrativeWorker — no shared context with the
main narrative (no entity stats, no chat history).

THREADING RULE: Both the VectorMemory query and the LLM call happen here,
never on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from llm_engine.base import LLMBackend, LLMConnectionError
from llm_engine.prompt_builder import build_mini_dico_prompt
from llm_engine.vector_memory import VectorMemory


class MiniDicoWorker(QThread):
    """Handles a single Mini-Dico lore lookup off the main thread.

    The worker:
      1. Queries VectorMemory for relevant lore chunks (save-scoped).
      2. Builds the Mini-Dico prompt (encyclopedic persona, no narrative context).
      3. Calls the LLM and emits the response.

    Signals:
        token_received(str):     Response text (full in Phase 3; streamed in Phase 4).
        response_complete(str):  Full lore answer text.
        error_occurred(str):     Human-readable error message.

    Args:
        llm:               The LLM backend (shared instance; read-only config).
        vector_memory:     The session's VectorMemory instance.
        question:          The player's lore question.
        universe_save_id:  Save ID used to scope the lore chunk query.
        temperature:       Sampling temperature (0.0 to 1.0).
        top_p:             Nucleus sampling parameter (0.0 to 1.0).
    """

    token_received = Signal(str)
    response_complete = Signal(str)
    error_occurred = Signal(str)

    def __init__(
        self,
        llm: LLMBackend,
        vector_memory: VectorMemory,
        question: str,
        universe_save_id: str,
        lore_book: list[dict] | None = None,
        global_lore: str | None = None,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> None:
        super().__init__()
        self._llm = llm
        self._vector_memory = vector_memory
        self._question = question
        self._universe_save_id = universe_save_id
        self._lore_book: list[dict] = lore_book or []
        self._global_lore = global_lore
        self._temperature = temperature
        self._top_p = top_p

    def run(self) -> None:
        """Execute the Mini-Dico query pipeline.  Never raises."""
        try:
            # Step 1 — RAG retrieval (lore chunks only)
            rag_results = self._vector_memory.query(
                self._universe_save_id,
                self._question,
                k=5,
            )
            lore_chunks = [r["text"] for r in rag_results]

            # Step 2 — Build encyclopedic prompt (zero narrative context)
            messages = build_mini_dico_prompt(
                self._question,
                lore_chunks,
                lore_book=self._lore_book,
                global_lore=self._global_lore,
            )

            # Step 3 — Call LLM
            response = self._llm.complete(
                messages, temperature=self._temperature, top_p=self._top_p
            )
            answer = response.narrative_text or "(No answer generated.)"

            # Phase 3: emit full text; Phase 4 upgrades to streaming
            self.token_received.emit(answer)
            self.response_complete.emit(answer)

        except LLMConnectionError as exc:
            self.error_occurred.emit(
                f"LLM unreachable for lore query — check your connection.\n\n{exc}"
            )
        except Exception as exc:
            self.error_occurred.emit(f"Mini-Dico error: {exc}")
