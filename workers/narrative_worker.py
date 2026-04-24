"""
workers/narrative_worker.py

QThread worker for the Arbitrator narrative turn pipeline.

This is the most critical worker in AIRPG.  It runs the complete
ArbitratorEngine.process_turn() off the main thread and communicates progress
back via signals.

Phase 3 behaviour: emits the full narrative_text as a single token_received
signal (functional but not streamed).  Phase 4 will upgrade this to true
per-token streaming via LLMBackend.stream_tokens().

THREADING RULE: ALL LLM calls, ALL SQLite writes, and ALL VectorMemory
embedding that occur during a turn happen here — never on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.arbitrator import ArbitratorEngine, ArbitratorResult
from llm_engine.base import LLMConnectionError, LLMMessage, LLMBackend
from llm_engine.vector_memory import VectorMemory


class NarrativeWorker(QThread):
    """Runs one complete Arbitrator turn off the main thread.

    Signals:
        token_received(str):   Narrative text (full response in Phase 3;
                               per-token in Phase 4).
        turn_complete(object): The ArbitratorResult dataclass instance.
        error_occurred(str):   Human-readable error string.
        status_update(str):    Short message for QStatusBar.
    """

    token_received = Signal(str)
    turn_complete = Signal(object)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(
        self,
        llm: LLMBackend,
        arbitrator: ArbitratorEngine,
        vector_memory: VectorMemory,
        save_id: str,
        turn_id: int,
        action: object, # PlayerAction
        history: list[dict],
        system_prompt: str,
        global_lore: str = "",
        temperature: float = 0.7,
        top_p: float = 1.0,
        verbosity: str = "balanced",
        current_time: int = 0
    ) -> None:
        super().__init__()
        self._llm = llm
        self._arbitrator = arbitrator
        self._vector_memory = vector_memory
        self._save_id = save_id
        self._turn_id = turn_id
        self._action = action
        self._history = history
        self._system_prompt = system_prompt
        self._global_lore = global_lore
        self._temperature = temperature
        self._top_p = top_p
        self._verbosity = verbosity
        self._current_time = current_time

    def run(self) -> None:
        """Execute the Arbitrator turn pipeline.  Never raises."""
        try:
            self.status_update.emit("Generating narrative…")
            
            # Configure arbitrator with injected dependencies
            self._arbitrator.configure(self._llm, self._vector_memory)

            # Map history format if needed (ChatDisplay format -> LLMMessage format)
            llm_history = []
            for h in self._history:
                if h.get("event_type") == "user_input":
                    llm_history.append({"role": "user", "content": h.get("payload", "")})
                elif h.get("event_type") == "narrative_text":
                    payload = h.get("payload", "")
                    text = payload.get("variants")[payload.get("active")] if isinstance(payload, dict) else str(payload)
                    llm_history.append({"role": "assistant", "content": text})

            result: ArbitratorResult = self._arbitrator.process_turn(
                save_id=self._save_id,
                turn_id=self._turn_id,
                user_message=self._action.text,
                universe_system_prompt=self._system_prompt,
                history=llm_history,
                player_entity_id=self._action.player_id,
                stream_token_callback=self.token_received.emit,
                temperature=self._temperature,
                top_p=self._top_p,
                verbosity_level=self._verbosity,
            )

            self.turn_complete.emit(result)
            self.status_update.emit("Ready.")

        except LLMConnectionError as exc:
            self.error_occurred.emit(
                f"LLM unreachable — check your Ollama server or API key.\n\n{exc}"
            )
            self.status_update.emit("LLM connection error.")
        except Exception as exc:
            self.error_occurred.emit(f"Unexpected error during turn: {exc}")
            self.status_update.emit("Error.")
