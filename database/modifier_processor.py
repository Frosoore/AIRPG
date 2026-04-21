"""
database/modifier_processor.py

Active Modifiers management for AIRPG.

Modifiers are temporary stat adjustments (buffs, debuffs, curses, blessings)
that automatically expire after a set amount of in-game time (minutes).
This module provides:

  - apply_modifiers: overlay active modifiers on top of a base stat snapshot
    for real-time display (read-only, no DB mutation).
  - tick_modifiers: decrement all modifier durations by elapsed minutes and
    purge expired ones from the database.
  - add_modifier: insert a new modifier row and return its ID.

Modifiers live in the Active_Modifiers table, which is keyed on
(modifier_id, entity_id, stat_key).  Every modifier carries a signed float
delta and a minutes_remaining countdown.  When minutes_remaining reaches 0
the modifier is considered expired and will be deleted on the next tick.
"""

import sqlite3
import uuid

from database.schema import get_connection


class ModifierProcessor:
    """Manages temporary stat modifiers for entities in a universe database.

    Args:
        db_path: Filesystem path to an existing universe .db file created
                 by database.schema.create_universe_db().
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_modifiers(
        self,
        save_id: str,
        entity_id: str,
        base_stats: dict[str, str],
    ) -> dict[str, str]:
        """Overlay active modifiers on a base stat snapshot.

        Reads all active modifiers for the entity and adds their deltas to
        the corresponding numeric stats.  Non-numeric stats are left unchanged.
        This method is read-only: it does not write to the database.

        Args:
            save_id:    The active save (used to scope modifier lookup via
                        entity_id — modifiers are stored per entity, not per save,
                        but the entity must belong to this save's universe).
            entity_id:  The entity whose modifiers are applied.
            base_stats: The entity's current base stat snapshot from State_Cache
                        (stat_key -> string value).

        Returns:
            New dict with modifier deltas applied.  Keys not affected by any
            modifier are copied verbatim from base_stats.

        Raises:
            sqlite3.Error: On any database failure.
        """
        modifiers = self._fetch_modifiers(entity_id)
        result: dict[str, str] = dict(base_stats)

        for mod in modifiers:
            stat_key: str = mod["stat_key"]
            delta: float = mod["delta"]
            current_raw = result.get(stat_key, "0")
            try:
                current = float(current_raw)
            except ValueError:
                # Non-numeric stat — skip this modifier
                continue
            new_val = current + delta
            from core.localization import fmt_num
            result[stat_key] = fmt_num(new_val)

        return result

    def tick_modifiers(self, save_id: str, elapsed_minutes: int = 1) -> list[str]:
        """Decrement minutes_remaining for all modifiers of this save's entities.

        For every active modifier associated with any entity in the database:
          1. Decrements minutes_remaining by elapsed_minutes.
          2. Deletes the modifier if minutes_remaining reaches 0 after decrement.

        The save_id parameter scopes the tick to entities relevant to the given
        save by joining through the State_Cache (entities that have cache entries
        for this save).  If no scoping information exists, all entity modifiers
        in Active_Modifiers are ticked.

        Args:
            save_id:         The save whose modifier timers are advanced.
            elapsed_minutes: Number of minutes that passed in-game.

        Returns:
            List of modifier_id strings that were deleted (expired) this tick.

        Raises:
            sqlite3.Error: On any database failure.
        """
        with get_connection(self._db_path) as conn:
            # Decrement all modifiers for entities belonging to this save
            conn.execute(
                """
                UPDATE Active_Modifiers
                SET minutes_remaining = minutes_remaining - ?
                WHERE entity_id IN (
                    SELECT DISTINCT entity_id FROM State_Cache WHERE save_id = ?
                );
                """,
                (elapsed_minutes, save_id),
            )

            # Collect expired modifier IDs before deletion
            expired_rows = conn.execute(
                """
                SELECT modifier_id FROM Active_Modifiers
                WHERE minutes_remaining <= 0
                  AND entity_id IN (
                      SELECT DISTINCT entity_id FROM State_Cache WHERE save_id = ?
                  );
                """,
                (save_id,),
            ).fetchall()
            expired_ids: list[str] = [row[0] for row in expired_rows]

            # Delete expired modifiers
            if expired_ids:
                placeholders = ",".join("?" * len(expired_ids))
                conn.execute(
                    f"DELETE FROM Active_Modifiers WHERE modifier_id IN ({placeholders});",
                    expired_ids,
                )

            conn.commit()

        return expired_ids

    def add_modifier(
        self,
        save_id: str,
        entity_id: str,
        stat_key: str,
        delta: float,
        minutes: int,
    ) -> str:
        """Insert a new modifier and return its generated modifier_id.

        Args:
            save_id:   The save this modifier is associated with.
            entity_id: The entity the modifier affects.
            stat_key:  The stat key the delta is applied to.
            delta:     Signed float adjustment (positive = buff, negative = debuff).
            minutes:   Number of in-game minutes the modifier lasts (must be >= 1).

        Returns:
            The newly generated modifier_id (UUID string).

        Raises:
            ValueError: If minutes < 1.
            sqlite3.Error: On any database failure.
        """
        if minutes < 1:
            raise ValueError(f"Modifier minutes must be >= 1, got {minutes}.")

        modifier_id = str(uuid.uuid4())
        with get_connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO Active_Modifiers
                    (modifier_id, entity_id, stat_key, delta, minutes_remaining)
                VALUES (?, ?, ?, ?, ?);
                """,
                (modifier_id, entity_id, stat_key, delta, minutes),
            )
            conn.commit()

        return modifier_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_modifiers(self, entity_id: str) -> list[dict[str, object]]:
        """Fetch all active modifiers for an entity from the database.

        Args:
            entity_id: The entity whose modifiers are retrieved.

        Returns:
            List of dicts with keys: modifier_id, entity_id, stat_key, delta,
            minutes_remaining.
        """
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT modifier_id, entity_id, stat_key, delta, minutes_remaining
                FROM Active_Modifiers
                WHERE entity_id = ?;
                """,
                (entity_id,),
            ).fetchall()
        return [
            {
                "modifier_id": row[0],
                "entity_id": row[1],
                "stat_key": row[2],
                "delta": row[3],
                "minutes_remaining": row[4],
            }
            for row in rows
        ]
