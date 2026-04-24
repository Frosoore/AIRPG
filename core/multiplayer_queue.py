
import queue
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal, QObject

if TYPE_CHECKING:
    from core.arbitrator import ArbitratorEngine
    from llm_engine.base import LLMMessage

@dataclass
class PlayerAction:
    """Data structure for a queued player action."""
    player_id: str
    text: str
    save_id: str
    turn_id: int
    universe_system_prompt: str
    history: list["LLMMessage"]
    temperature: float = 0.7
    top_p: float = 1.0
    verbosity_level: str = "balanced"

class MultiplayerQueueSignals(QObject):
    """Signals for the ArbitratorWorker to communicate with the UI."""
    token_received = Signal(str, str)  # token, player_id
    turn_complete = Signal(object, str) # ArbitratorResult, player_id
    error_occurred = Signal(str, str) # error_msg, player_id
    status_update = Signal(str)

class ArbitratorWorker(QThread):
    """
    Background worker that processes player actions sequentially from a FIFO queue.
    Ensures that only one turn is being resolved at a time to prevent DB race conditions.
    """
    def __init__(self, arbitrator: "ArbitratorEngine"):
        super().__init__()
        self._arbitrator = arbitrator
        self._queue: queue.Queue[PlayerAction] = queue.Queue()
        self.signals = MultiplayerQueueSignals()
        self._is_running = True

    def enqueue(self, action: PlayerAction):
        """Add a new action to the processing queue."""
        self._queue.put(action)

    def stop(self):
        """Gracefully stop the worker loop."""
        self._is_running = False
        # Push a None to unblock queue.get() if it's waiting
        self._queue.put(None)

    def run(self):
        while self._is_running:
            # This blocks until an action is available
            action = self._queue.get()
            
            if action is None or not self._is_running:
                break

            try:
                self.signals.status_update.emit(f"Resolving action for {action.player_id}...")
                
                # We wrap the signal emission to include the player_id
                def token_callback(token: str):
                    self.signals.token_received.emit(token, action.player_id)

                result = self._arbitrator.process_turn(
                    save_id=action.save_id,
                    turn_id=action.turn_id,
                    user_message=action.text,
                    universe_system_prompt=action.universe_system_prompt,
                    history=action.history,
                    player_entity_id=action.player_id,
                    stream_token_callback=token_callback,
                    temperature=action.temperature,
                    top_p=action.top_p,
                    verbosity_level=action.verbosity_level,
                )
                
                self.signals.turn_complete.emit(result, action.player_id)
                self.signals.status_update.emit("Ready.")
                
            except Exception as exc:
                self.signals.error_occurred.emit(str(exc), action.player_id)
                self.signals.status_update.emit("Error.")
            finally:
                self._queue.task_done()
