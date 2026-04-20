"""
workers/narrative_worker.py

QThread worker for the Arbitrator narrative turn pipeline.

This is the most critical worker in AIRPG.  It runs the complete
Arbitrator.process_turn() off the main thread and communicates progress
back via signals.

Phase 3 behaviour: emits the full narrative_text as a single token_received
signal (functional but not streamed).  Phase 4 will upgrade this to true
per-token streaming via LLMBackend.stream_tokens().

THREADING RULE: ALL LLM calls, ALL SQLite writes, and ALL VectorMemory
embedding that occur during a turn happen here — never on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.arbitrator import Arbitrator, ArbitratorResult
from llm_engine.base import LLMConnectionError, LLMMessage


class NarrativeWorker(QThread):
    """Runs one complete Arbitrator turn off the main thread.

    Signals:
        token_received(str):   Narrative text (full response in Phase 3;
                               per-token in Phase 4).
        turn_complete(object): The ArbitratorResult dataclass instance.
        error_occurred(str):   Human-readable error string.
        status_update(str):    Short message for QStatusBar.

    Args:
        arbitrator:              The session's Arbitrator instance.
        save_id:                 The active save identifier.
        turn_id:                 The current turn number.
        user_message:            The player's raw input text.
        universe_system_prompt:  The universe's system prompt string.
        history:                 Prior conversation as list[LLMMessage].
        player_entity_id:        The ID of the player sending the message.
        temperature:             Sampling temperature (0.0 to 1.0).
        top_p:                   Nucleus sampling parameter (0.0 to 1.0).
    """

    token_received = Signal(str)
    turn_complete = Signal(object)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(
        self,
        arbitrator: Arbitrator,
        save_id: str,
        turn_id: int,
        user_message: str,
        universe_system_prompt: str,
        history: list[LLMMessage],
        player_entity_id: str = "player",
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> None:
        super().__init__()
        self._arbitrator = arbitrator
        self._save_id = save_id
        self._turn_id = turn_id
        self._user_message = user_message
        self._universe_system_prompt = universe_system_prompt
        self._history = list(history)  # Defensive copy
        self._player_entity_id = player_entity_id
        self._temperature = temperature
        self._top_p = top_p

    def run(self) -> None:
        """Execute the Arbitrator turn pipeline.  Never raises."""
        try:
            self.status_update.emit("Generating narrative…")

            result: ArbitratorResult = self._arbitrator.process_turn(
                save_id=self._save_id,
                turn_id=self._turn_id,
                user_message=self._user_message,
                universe_system_prompt=self._universe_system_prompt,
                history=self._history,
                player_entity_id=self._player_entity_id,
                # Phase 4: real per-token streaming via Signal/Slot
                # token_received.emit is thread-safe: Qt queues the call
                # onto the main thread's event loop automatically
                stream_token_callback=self.token_received.emit,
                temperature=self._temperature,
                top_p=self._top_p,
            )
            # Tokens were already emitted per-token above — do NOT emit again

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
