"""
database/event_sourcing.py

Core Event Sourcing implementation for AIRPG.

Every state change in the game is recorded as an immutable event in
Event_Log.  The State_Cache is a performance materialisation derived by
replaying those events.  This module is the authoritative bridge between
the two.

Supported event_type values (non-exhaustive; the engine is extensible):
    - 'entity_create'  payload: {"entity_id": str, "entity_type": str, "name": str}
    - 'stat_change'    payload: {"entity_id": str, "stat_key": str, "delta": float}
                                OR {"entity_id": str, "stat_key": str, "value": str}
    - 'stat_set'       payload: {"entity_id": str, "stat_key": str, "value": str}
    - 'dialogue'       payload: {"speaker": str, "text": str}   (no cache mutation)
    - 'combat_roll'    payload: {"entity_id": str, ...}         (no cache mutation)
"""

import json
import sqlite3
from typing import Any

from database.schema import get_connection


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row into a plain dict."""
    return dict(zip(row.keys(), tuple(row)))


# ---------------------------------------------------------------------------
# EventSourcer
# ---------------------------------------------------------------------------

class EventSourcer:
    """Manages event appending, querying, and State_Cache reconstruction
    for a single AIRPG universe database.

    Args:
        db_path: Filesystem path to an existing universe .db file created
                 by database.schema.create_universe_db().
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_event(
        self,
        save_id: str,
        turn_id: int,
        event_type: str,
        target_entity: str,
        payload: dict[str, Any],
    ) -> int:
        """Insert a new event into Event_Log and return its auto-generated event_id.
        """
        payload_json = json.dumps(payload)
        with get_connection(self._db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO Event_Log (save_id, turn_id, event_type, target_entity, payload)
                VALUES (?, ?, ?, ?, ?);
                """,
                (save_id, turn_id, event_type, target_entity, payload_json),
            )
            event_id = cursor.lastrowid
            conn.commit()

        return event_id  # type: ignore[return-value]

    def get_events(
        self,
        save_id: str,
        start_turn_id: int = 0,
        up_to_turn_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch events for a save, ordered chronologically.

        Args:
            save_id:        The save whose events are requested.
            start_turn_id:  Only events with turn_id > this value are returned.
            up_to_turn_id:  If provided, only events with turn_id <= this value
                            are returned.  None means all future events.
        """
        with get_connection(self._db_path) as conn:
            query = "SELECT * FROM Event_Log WHERE save_id = ? AND turn_id > ?"
            params: list[Any] = [save_id, start_turn_id]

            if up_to_turn_id is not None:
                query += " AND turn_id <= ?"
                params.append(up_to_turn_id)

            query += " ORDER BY event_id ASC;"
            rows = conn.execute(query, params).fetchall()

        events: list[dict[str, Any]] = []
        for row in rows:
            event = _row_to_dict(row)
            event["payload"] = json.loads(event["payload"])
            events.append(event)
        return events

    def rebuild_state_cache(
        self,
        save_id: str,
        up_to_turn_id: int | None = None,
        force_full: bool = False,
    ) -> None:
        """Flush and rebuild State_Cache for a save by replaying Event_Log.

        Args:
            save_id:        The save whose cache is being rebuilt.
            up_to_turn_id:  If provided, only events up to this turn are
                            replayed.  None means the full history.
            force_full:     If True, ignores all snapshots and replays the
                            entire history from turn 0.  Use this to fix
                            cache corruption.

        Optimized to start from the nearest previous snapshot if one exists,
        unless force_full=True.
        """
        target_turn = up_to_turn_id if up_to_turn_id is not None else 9999999
        
        # 1. Load nearest snapshot
        cache: dict[str, dict[str, str]] = {}
        start_turn = -1 # Start from turn 0 if no snapshot
        
        if not force_full:
            with get_connection(self._db_path) as conn:
                row = conn.execute(
                    """
                    SELECT turn_id, state_json FROM Snapshots
                    WHERE save_id = ? AND turn_id <= ?
                    ORDER BY turn_id DESC LIMIT 1;
                    """,
                    (save_id, target_turn),
                ).fetchone()
                
                if row:
                    start_turn = row["turn_id"]
                    cache = json.loads(row["state_json"])

        # 2. Replay events from after the snapshot (or turn 0 if force_full)
        events = self.get_events(save_id, start_turn_id=start_turn, up_to_turn_id=up_to_turn_id)
        for event in events:
            cache = self._apply_event(event, cache)

        # 3. Atomic bulk update of State_Cache
        with get_connection(self._db_path) as conn:
            conn.execute("DELETE FROM State_Cache WHERE save_id = ?;", (save_id,))
            
            insert_data = []
            for entity_id, stats in cache.items():
                for stat_key, stat_value in stats.items():
                    insert_data.append((save_id, entity_id, stat_key, stat_value))
            
            if insert_data:
                conn.executemany(
                    """
                    INSERT INTO State_Cache (save_id, entity_id, stat_key, stat_value)
                    VALUES (?, ?, ?, ?);
                    """,
                    insert_data,
                )
            conn.commit()

    def validate_integrity(self, save_id: str) -> tuple[bool, dict[str, Any]]:
        """Verify that the current State_Cache matches a fresh replay of history.

        This is a diagnostic tool to detect corruption in the materialised cache.
        It does NOT use snapshots.

        Returns:
            Tuple of (passed: bool, mismatches: dict).
            mismatches is {entity_id: {stat_key: (cached_val, actual_val)}}.
        """
        # 1. Get current cache from DB
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT entity_id, stat_key, stat_value FROM State_Cache WHERE save_id = ?;",
                (save_id,),
            ).fetchall()
        db_cache: dict[str, dict[str, str]] = {}
        for r in rows:
            db_cache.setdefault(r["entity_id"], {})[r["stat_key"]] = r["stat_value"]

        # 2. Freshly replay all events
        events = self.get_events(save_id)
        replayed_cache: dict[str, dict[str, str]] = {}
        for event in events:
            replayed_cache = self._apply_event(event, replayed_cache)

        # 3. Compare
        mismatches: dict[str, Any] = {}
        all_entity_ids = set(db_cache.keys()) | set(replayed_cache.keys())

        for eid in all_entity_ids:
            db_stats = db_cache.get(eid, {})
            re_stats = replayed_cache.get(eid, {})
            
            all_stat_keys = set(db_stats.keys()) | set(re_stats.keys())
            for sk in all_stat_keys:
                dv = db_stats.get(sk)
                rv = re_stats.get(sk)
                if dv != rv:
                    mismatches.setdefault(eid, {})[sk] = (dv, rv)

        return (len(mismatches) == 0, mismatches)

    def take_snapshot(self, save_id: str, turn_id: int) -> None:
        """Capture the current materialised state and store it in Snapshots.
        
        This is an expensive operation (JSON-serialising the full state) and
        should be called sparingly.
        """
        # We must rebuild up to turn_id to ensure the snapshot is accurate
        # entity_id -> {stat_key: stat_value}
        cache: dict[str, dict[str, str]] = {}
        events = self.get_events(save_id, up_to_turn_id=turn_id)
        for event in events:
            cache = self._apply_event(event, cache)
            
        state_json = json.dumps(cache)
        
        with get_connection(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO Snapshots (save_id, turn_id, state_json) VALUES (?, ?, ?);",
                (save_id, turn_id, state_json),
            )
            conn.commit()

    def get_current_stats(
        self,
        save_id: str,
        entity_id: str,
    ) -> dict[str, str]:
        """Read the current materialised stats for one entity from State_Cache.

        Args:
            save_id:   The active save identifier.
            entity_id: The entity whose stats are requested.

        Returns:
            Dict mapping stat_key -> stat_value strings.  Empty dict if the
            entity has no cached stats or does not exist.

        Raises:
            sqlite3.Error: On any database failure.
        """
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT stat_key, stat_value FROM State_Cache
                WHERE save_id = ? AND entity_id = ?;
                """,
                (save_id, entity_id),
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_event(
        event: dict[str, Any],
        cache: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """Apply a single event to an in-memory stats cache and return the result.

        This is a pure function: it does not mutate the database.  A new
        copy of the cache is returned when modifications are made.

        Handled event types:
            entity_create — registers the entity in the cache with no stats.
            stat_change   — adjusts a numeric stat by delta, or sets a string
                            value when a 'value' key is present instead of 'delta'.
            stat_set      — unconditionally sets a stat to a string value.

        All other event types (e.g. 'dialogue', 'combat_roll') are ignored
        because they carry no cache-relevant state.

        Args:
            event: A single event dict (as returned by get_events).
            cache: The current in-memory stats dict (entity_id -> stats).

        Returns:
            Updated cache dict (may be the same object if no mutation needed).
        """
        event_type: str = event["event_type"]
        payload: dict[str, Any] = event["payload"]

        if event_type == "entity_create":
            entity_id: str = payload["entity_id"]
            if entity_id not in cache:
                cache[entity_id] = {}

        elif event_type in ("stat_change", "stat_set"):
            entity_id = payload.get("entity_id", event.get("target_entity", ""))
            stat_key: str = payload["stat_key"]

            if entity_id not in cache:
                cache[entity_id] = {}

            if event_type == "stat_set" or "value" in payload:
                # Unconditional string assignment
                cache[entity_id][stat_key] = str(payload["value"])
            else:
                # Numeric delta
                delta: float = float(payload["delta"])
                current_raw = cache[entity_id].get(stat_key, "0")
                try:
                    current = float(current_raw)
                except ValueError:
                    current = 0.0
                new_val = current + delta
                # Preserve integer display when the result is whole
                if new_val == int(new_val):
                    cache[entity_id][stat_key] = str(int(new_val))
                else:
                    cache[entity_id][stat_key] = str(new_val)

        # All other event types (dialogue, combat_roll, …) produce no cache change
        return cache
