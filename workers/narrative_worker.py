"""
workers/narrative_worker.py

QThread worker for the Arbitrator narrative turn pipeline.

This is the most critical worker in Axiom AI.  It runs the complete
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
    hero_decision_received = Signal(str)
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
        current_time: int = 0,
        mode: str = "Normal",
        entities: list[dict] | None = None
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
        self._mode = mode
        self._entities = entities or []

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

            # --- HERO IA DECISION (Companion Mode) ---
            hero_action = None
            hero_id = None
            if self._mode == "Companion":
                self.status_update.emit("Consulting Hero IA…")
                
                # Fetch hero_id from metadata or fallback to discovery
                hero_id = self._get_hero_id_from_metadata()
                hero_ent = self._find_hero_entity(hero_id)
                
                if hero_ent:
                    hero_id = hero_ent["entity_id"]
                    hero_action = self._get_hero_decision(hero_ent, llm_history)
                    self.hero_decision_received.emit(hero_action)
                    self.status_update.emit(f"Hero decides: {hero_action[:30]}…")

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
                hero_action=hero_action,
                hero_entity_id=hero_id,
                mode=self._mode,
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

    def _get_hero_id_from_metadata(self) -> str | None:
        """Fetch the hero ID configured in universe metadata."""
        from workers.db_helpers import get_connection
        try:
            with get_connection(self._arbitrator._db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM Universe_Meta WHERE key = 'companion_hero_id';"
                ).fetchone()
                return row[0] if row and row[0] else None
        except Exception:
            return None

    def _find_hero_entity(self, target_id: str | None = None) -> dict | None:
        """Locate the main Hero entity in the universe."""
        if target_id:
            for e in self._entities:
                if e["entity_id"] == target_id:
                    return e

        # Fallback to discovery
        # 1. Look for explicit ID 'hero'
        for e in self._entities:
            if e["entity_id"].lower() == "hero":
                return e
        # 2. Look for name containing 'Hero'
        for e in self._entities:
            if "hero" in e.get("name", "").lower():
                return e
        # 3. Fallback to first NPC if any
        for e in self._entities:
            if e.get("entity_type") == "npc":
                return e
        return None

    def _get_hero_decision(self, hero_ent: dict, history: list) -> str:
        """Call a local LLM to decide the Hero's action."""
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_hero_decision_prompt, format_entity_stats_block
        
        cfg = load_config()
        # Explicitly use local model for Hero if premium is selected globally
        hero_llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
        
        hero_stats = format_entity_stats_block([hero_ent])
        prompt = build_hero_decision_prompt(
            hero_name=hero_ent.get("name", "Hero"),
            hero_persona=hero_ent.get("description", ""),
            hero_stats=hero_stats,
            history=history,
            user_message=self._action.text
        )
        
        resp = hero_llm.complete(prompt, max_tokens=100)
        return resp.narrative_text.strip()
