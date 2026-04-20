"""
workers/db_helpers.py

Synchronous database helper functions for one-time UI bootstrap reads.

These are small, fast, lightweight operations that are acceptable to run
on the main thread during view construction or session initialisation
(e.g. reading 1–2 rows of metadata at session start).

All SQL strings in the project are concentrated in database/ and workers/
modules — never in ui/ files — to satisfy the MVC separation mandate.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


from database.schema import get_connection

def apply_stat_preset(db_path: str, preset_name: str) -> int:
    """Apply a stat preset to a universe database.

    Args:
        db_path: Path to the universe .db file.
        preset_name: Key in STAT_PRESETS.

    Returns:
        Number of stats successfully added.
    """
    from database.presets import STAT_PRESETS, generate_stat_id
    from database.schema import migrate_stat_definitions_table

    if preset_name not in STAT_PRESETS:
        return 0

    migrate_stat_definitions_table(db_path)
    stats_to_add = STAT_PRESETS[preset_name]
    added_count = 0

    with get_connection(db_path) as conn:
        for s in stats_to_add:
            try:
                # Check if a stat with the same name already exists
                existing = conn.execute(
                    "SELECT 1 FROM Stat_Definitions WHERE name = ?;",
                    (s["name"],)
                ).fetchone()
                if existing:
                    continue

                stat_id = generate_stat_id(s["name"])
                conn.execute(
                    "INSERT INTO Stat_Definitions (stat_id, name, description, value_type, parameters) "
                    "VALUES (?, ?, ?, ?, ?);",
                    (stat_id, s["name"], s["description"], s["value_type"], json.dumps(s["parameters"]))
                )
                added_count += 1
            except sqlite3.Error:
                continue
        conn.commit()

    return added_count

def read_universe_card_metadata(db_path: str) -> tuple[str, str, str]:
    """Read display metadata for a universe card widget.

    Args:
        db_path: Path to the universe .db file.

    Returns:
        Tuple of (universe_name, last_updated_str, difficulty_str).
        Returns sensible defaults on any error.
    """
    name = Path(db_path).stem.replace("_", " ").title()
    last_updated = "Never"
    difficulty = "Normal"
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM Universe_Meta WHERE key = 'universe_name';"
            ).fetchone()
            if row:
                name = row["value"]
            row = conn.execute(
                "SELECT player_name, difficulty, last_updated FROM Saves "
                "ORDER BY last_updated DESC LIMIT 1;"
            ).fetchone()
            if row:
                last_updated = str(row["last_updated"])[:10]
                difficulty = str(row["difficulty"])
    except (sqlite3.Error, FileNotFoundError):
        pass
    return name, last_updated, difficulty


def provision_blank_universe(db_path: str, name: str) -> None:
    """Insert default Universe_Meta rows into a freshly provisioned database.

    Args:
        db_path: Path to the universe .db file (already schema-provisioned).
        name:    Human-readable universe name.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES (?, ?);",
            ("universe_name", name),
        )
        conn.execute(
            "INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES (?, ?);",
            ("World_Tension_Level", "0.3"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES (?, ?);",
            ("system_prompt", f"You are the narrator of '{name}'."),
        )
        conn.commit()


def create_new_save(
    db_path: str,
    player_name: str,
    difficulty: str,
    player_persona: str = "",
) -> str:
    """Insert a new save row and return its save_id.

    Args:
        db_path:        Path to the universe .db file.
        player_name:    Player's chosen name.
        difficulty:     "Normal" or "Hardcore".
        player_persona: Optional background / persona text for the player.

    Returns:
        The newly created UUID save_id string.
    """
    from database.schema import (
        migrate_saves_table, 
        migrate_lore_book_table, 
        migrate_inventory_tables
    )

    migrate_saves_table(db_path)
    migrate_lore_book_table(db_path)
    migrate_inventory_tables(db_path)
    save_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO Saves (save_id, player_name, difficulty, last_updated, player_persona) "
            "VALUES (?, ?, ?, ?, ?);",
            (save_id, player_name, difficulty, now, player_persona),
        )
        conn.commit()
    return save_id


def load_saves(db_path: str) -> list[dict]:
    """Read all saves for a universe, sorted most-recent first.

    Runs the player_persona migration automatically so older databases
    remain compatible.

    Args:
        db_path: Path to the universe .db file.

    Returns:
        List of save dicts with keys: save_id, player_name, difficulty,
        last_updated, player_persona.
    """
    from database.schema import (
        migrate_saves_table, 
        migrate_lore_book_table, 
        migrate_inventory_tables
    )

    try:
        migrate_saves_table(db_path)
        migrate_lore_book_table(db_path)
        migrate_inventory_tables(db_path)
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT save_id, player_name, difficulty, last_updated, player_persona "
                "FROM Saves ORDER BY last_updated DESC;"
            ).fetchall()
        return [
            {
                "save_id": r["save_id"],
                "player_name": r["player_name"],
                "difficulty": r["difficulty"],
                "last_updated": r["last_updated"],
                "player_persona": r["player_persona"],
            }
            for r in rows
        ]
    except (sqlite3.Error, FileNotFoundError):
        return []


def load_rules_for_session(db_path: str) -> list[dict]:
    """Read all rules from a universe database for session initialisation.

    Args:
        db_path: Path to the universe .db file.

    Returns:
        List of rule dicts in canonical Rules Engine schema.
        Empty list if the database cannot be read.
    """
    try:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT rule_id, priority, conditions, actions, target_entity "
                "FROM Rules;"
            ).fetchall()
        return [
            {
                "rule_id": r["rule_id"],
                "priority": r["priority"],
                "conditions": json.loads(r["conditions"]) if r["conditions"] else {},
                "actions": json.loads(r["actions"]) if r["actions"] else [],
                "target_entity": r["target_entity"],
            }
            for r in rows
        ]
    except (sqlite3.Error, FileNotFoundError):
        return []


def get_max_turn_id(db_path: str, save_id: str) -> int:
    """Read the highest turn_id from Event_Log for a save (session resume).

    Args:
        db_path:  Path to the universe .db file.
        save_id:  The save to query.

    Returns:
        The maximum turn_id, or 0 if no events exist.
    """
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT MAX(turn_id) FROM Event_Log WHERE save_id = ?;",
                (save_id,),
            ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except (sqlite3.Error, FileNotFoundError):
        pass
    return 0


def get_current_time(db_path: str, save_id: str) -> int:
    """Read the highest in_game_time from Timeline for a save.

    Args:
        db_path:  Path to the universe .db file.
        save_id:  The save to query.

    Returns:
        The maximum in_game_time in minutes, or 0 if no timeline exists.
    """
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT MAX(in_game_time) FROM Timeline WHERE save_id = ?",
                (save_id,)
            ).fetchone()
            return row[0] if row and row[0] is not None else 0
    except (sqlite3.Error, FileNotFoundError):
        return 0


def get_time_of_day_context(total_minutes: int) -> str:
    """Convert total minutes into a descriptive Day, Time, and Phase string.

    Args:
        total_minutes: Cumulative in-game minutes.

    Returns:
        Formatted string: "Day X, HH:MM (Phase)"
    """
    days = (total_minutes // 1440) + 1
    hours = (total_minutes % 1440) // 60
    mins = total_minutes % 60

    # Determine Phase
    if 5 <= hours < 8:
        phase = "Dawn"
    elif 8 <= hours < 12:
        phase = "Morning"
    elif 12 <= hours < 17:
        phase = "Afternoon"
    elif 17 <= hours < 21:
        phase = "Dusk"
    else:
        phase = "Night"

    return f"Day {days}, {hours:02d}:{mins:02d} ({phase})"

def get_inventory(db_path: str, save_id: str, entity_id: str) -> list[dict]:
    """Fetch the inventory for a specific entity in a save."""
    inventory = []
    try:
        from database.schema import get_connection
        with get_connection(db_path) as conn:
            rows = conn.execute(
                """
                SELECT i.item_id, d.name, d.description, d.category, d.weight, d.rarity, i.quantity
                FROM Items_Inventory i
                JOIN Item_Definitions d ON i.item_id = d.item_id
                WHERE i.save_id = ? AND i.entity_id = ?;
                """,
                (save_id, entity_id)
            ).fetchall()
            inventory = [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB_HELPERS] Error fetching inventory for {entity_id}: {e}")
    return inventory
