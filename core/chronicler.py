"""
core/chronicler.py

The Chronicler Engine — AIRPG's macro-simulation agent.

The Chronicler simulates the independent evolution of the off-screen world
(factions, VIP NPCs, cities) without the player's involvement.  It runs
periodically (every N player turns, or on explicit time-skip events) and
produces JSON tool calls that update entity stats in the database.

Design principles
-----------------
- The Chronicler NEVER raises on malformed LLM responses.  A broken world
  simulation is always preferable to a crashed game session.
- All updates are written to Event_Log with event_type='chronicler_update'
  so they are included in checkpoint replays and can be rewound.
- World_Tension_Level (stored in Universe_Meta) throttles the severity of
  simulated events: low tension → mundane shifts, high tension → cataclysms.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from database.event_sourcing import EventSourcer
from database.schema import get_connection
from llm_engine.base import LLMBackend, LLMMessage
from llm_engine.prompt_builder import build_chronicler_prompt


_DEFAULT_TENSION: float = 0.3
_DEFAULT_TRIGGER_INTERVAL: int = 50

# Entity types tracked by the Chronicler (player is excluded)
_CHRONICLER_ENTITY_TYPES: tuple[str, ...] = ("npc", "faction", "world")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ChroniclerResult:
    """The complete output of one Chronicler world-simulation run.

    Attributes:
        updated_entities:   entity_ids whose stats were changed.
        events_appended:    Count of new Event_Log entries written.
        world_tension_used: The World_Tension_Level active during this run.
        world_news:         A list of major off-screen event descriptions.
    """
    updated_entities: list[str] = field(default_factory=list)
    events_appended: int = 0
    world_tension_used: float = _DEFAULT_TENSION
    world_news: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ChroniclerEngine
# ---------------------------------------------------------------------------

class ChroniclerEngine:
    """Simulates the off-screen world by calling the LLM periodically.

    Args:
        llm:              The LLM backend used for world simulation calls.
        event_sourcer:    Handles Event_Log writes and State_Cache reads.
        db_path:          Path to the universe .db for entity and meta queries.
        trigger_interval: Number of player turns between automatic Chronicler
                          runs.  Defaults to 50.
    """

    def __init__(
        self,
        llm: LLMBackend,
        event_sourcer: EventSourcer,
        db_path: str,
        trigger_interval: int = _DEFAULT_TRIGGER_INTERVAL,
    ) -> None:
        self._llm = llm
        self._event_sourcer = event_sourcer
        self._db_path = db_path
        self._trigger_interval = trigger_interval

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_trigger(
        self,
        current_time: int,
        last_chronicle_time: int,
    ) -> bool:
        """Return True if the Chronicler should run now based on in-game time.

        Pure function — no I/O.

        Args:
            current_time:        The current cumulative in-game minutes.
            last_chronicle_time: The time in minutes at which the Chronicler last ran.

        Returns:
            True when (current_time - last_chronicle_time) >= trigger_interval.
        """
        return (current_time - last_chronicle_time) >= self._trigger_interval

    def run(
        self,
        save_id: str,
        turn_id: int,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> ChroniclerResult:
        """Execute one Chronicler world-simulation cycle.

        Steps:
          1. Read World_Tension_Level from Universe_Meta.
          2. Fetch all active off-screen entities and their current stats.
          3. Build the Chronicler prompt.
          4. Call the LLM (non-streaming; expects only a JSON tool call).
          5. Parse the resulting state_changes.
          6. Validate each change (entity must exist and be active).
          7. Persist valid changes via EventSourcer.
          8. Return ChroniclerResult.

        On any malformed LLM response the method logs a warning internally
        and returns an empty ChroniclerResult — it never raises.

        Args:
            save_id:     The save that owns the entities being simulated.
            turn_id:     The current turn number (used for Event_Log turn_id).
            temperature: Sampling temperature (0.0 to 1.0).
            top_p:       Nucleus sampling parameter (0.0 to 1.0).

        Returns:
            ChroniclerResult summarising what changed.
        """
        # Step 1 — World tension
        tension = self._fetch_world_tension()

        # Step 2 — Off-screen entities
        off_screen = self._fetch_off_screen_entities(save_id)
        if not off_screen:
            return ChroniclerResult(world_tension_used=tension)

        # Step 3 — Build prompt
        messages = build_chronicler_prompt(off_screen, tension)

        # Step 4 — Call LLM
        try:
            llm_response = self._llm.complete(
                messages, temperature=temperature, top_p=top_p
            )
        except Exception:
            # Connection / parse errors must not crash world simulation
            return ChroniclerResult(world_tension_used=tension)

        # Step 5 — Parse state_changes
        if llm_response.tool_call is None:
            return ChroniclerResult(world_tension_used=tension)

        try:
            state_changes: list[dict[str, Any]] = (
                llm_response.tool_call.get("state_changes", [])
            )
            world_news: list[str] = (
                llm_response.tool_call.get("world_news", [])
            )
        except (AttributeError, TypeError):
            return ChroniclerResult(world_tension_used=tension)

        if not isinstance(state_changes, list):
            state_changes = []
        if not isinstance(world_news, list):
            world_news = []

        # Step 6 + 7 — Validate and persist state changes
        valid_entity_ids = {e["entity_id"] for e in off_screen}
        updated_entities: list[str] = []
        events_appended: int = 0

        for change in state_changes:
            # ... (state change logic) ...
            if not isinstance(change, dict):
                continue

            entity_id: str = str(change.get("entity_id", ""))
            stat_key: str = str(change.get("stat_key", ""))
            delta = change.get("delta")
            value = change.get("value")

            if not entity_id or entity_id not in valid_entity_ids:
                continue  # silently skip unknown entities
            if not stat_key:
                continue

            if delta is not None:
                payload: dict[str, Any] = {
                    "entity_id": entity_id,
                    "stat_key": stat_key,
                    "delta": float(delta),
                }
                event_type = "stat_change"
            elif value is not None:
                payload = {
                    "entity_id": entity_id,
                    "stat_key": stat_key,
                    "value": str(value),
                }
                event_type = "stat_set"
            else:
                continue  # no delta or value — skip

            try:
                self._event_sourcer.append_event(
                    save_id, turn_id, "chronicler_update", entity_id, payload
                )
                events_appended += 1
                if entity_id not in updated_entities:
                    updated_entities.append(entity_id)
            except Exception:
                # A single event write failure must not abort the whole run
                continue

        # Step 7.5 — Persist World News to Timeline
        from workers.db_helpers import get_current_time
        current_minute = get_current_time(self._db_path, save_id)
        
        for news_item in world_news:
            try:
                with get_connection(self._db_path) as conn:
                    conn.execute(
                        "INSERT INTO Timeline (save_id, turn_id, in_game_time, description) VALUES (?, ?, ?, ?);",
                        (save_id, turn_id, current_minute, f"[WORLD NEWS] {news_item}")
                    )
                    conn.commit()
            except Exception as e:
                print(f"[CHRONICLER] Error persisting world news: {e}")

        return ChroniclerResult(
            updated_entities=updated_entities,
            events_appended=events_appended,
            world_tension_used=tension,
            world_news=world_news
        )

    def force_trigger(self, save_id: str, turn_id: int) -> ChroniclerResult:
        """Explicitly trigger a Chronicler run regardless of turn threshold.

        Intended for time-skip actions (sleeping, fast travel) where the
        player has explicitly advanced time.  Semantically equivalent to run()
        but named distinctly for call-site clarity.

        Args:
            save_id:  The active save.
            turn_id:  The current turn number.

        Returns:
            ChroniclerResult from the simulation run.
        """
        return self.run(save_id, turn_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_world_tension(self) -> float:
        """Read World_Tension_Level from Universe_Meta.

        Returns:
            Float in [0.0, 1.0].  Defaults to _DEFAULT_TENSION if the key
            is absent or the stored value cannot be parsed as a float.
        """
        try:
            with get_connection(self._db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM Universe_Meta WHERE key = 'World_Tension_Level';",
                ).fetchone()
            if row is None:
                return _DEFAULT_TENSION
            return float(row[0])
        except Exception:
            return _DEFAULT_TENSION

    def _fetch_off_screen_entities(self, save_id: str) -> list[dict[str, Any]]:
        """Fetch all active non-player entities and their current stats.

        Args:
            save_id: The active save — used to look up State_Cache stats.

        Returns:
            List of entity snapshot dicts:
            {"entity_id", "name", "entity_type", "stats": {stat_key: stat_value}}.
        """
        placeholders = ",".join("?" * len(_CHRONICLER_ENTITY_TYPES))
        try:
            with get_connection(self._db_path) as conn:
                rows = conn.execute(
                    f"""
                    SELECT entity_id, name, entity_type FROM Entities
                    WHERE entity_type IN ({placeholders}) AND is_active = 1;
                    """,
                    _CHRONICLER_ENTITY_TYPES,
                ).fetchall()
        except Exception:
            return []

        snapshots: list[dict[str, Any]] = []
        for row in rows:
            entity_id, name, entity_type = row[0], row[1], row[2]
            stats = self._event_sourcer.get_current_stats(save_id, entity_id)
            snapshots.append({
                "entity_id": entity_id,
                "name": name,
                "entity_type": entity_type,
                "stats": stats,
            })
        return snapshots
