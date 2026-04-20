"""
tests/test_schema.py

Unit tests for database/schema.py — verifies that create_universe_db()
provisions a file with the exact set of required tables and expected columns.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from database.schema import create_universe_db, EXPECTED_TABLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return the set of user-defined table names in the connected database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    ).fetchall()
    return {row[0] for row in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names for the given table."""
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {row[1] for row in rows}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Provide a path inside a temporary directory for a fresh universe db."""
    return str(tmp_path / "test_universe.db")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateUniverseDb:
    def test_creates_file(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        assert Path(tmp_db).exists(), "Database file was not created"

    def test_idempotent(self, tmp_db: str) -> None:
        """Calling create_universe_db twice must not raise."""
        create_universe_db(tmp_db)
        create_universe_db(tmp_db)  # should not raise

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = str(tmp_path / "a" / "b" / "c" / "universe.db")
        create_universe_db(nested)
        assert Path(nested).exists()

    def test_all_tables_present(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            tables = _table_names(conn)
        assert tables == EXPECTED_TABLES, (
            f"Missing tables: {EXPECTED_TABLES - tables} | "
            f"Unexpected tables: {tables - EXPECTED_TABLES}"
        )

    # --- Per-table column checks ---

    def test_universe_meta_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "Universe_Meta")
        assert {"key", "value"}.issubset(cols)

    def test_entities_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "Entities")
        assert {"entity_id", "entity_type", "name", "is_active"}.issubset(cols)

    def test_entity_stats_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "Entity_Stats")
        assert {"entity_id", "stat_key", "stat_value"}.issubset(cols)

    def test_rules_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "Rules")
        assert {"rule_id", "priority", "conditions", "actions", "target_entity"}.issubset(cols)

    def test_active_modifiers_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "Active_Modifiers")
        assert {"modifier_id", "entity_id", "stat_key", "delta", "minutes_remaining"}.issubset(cols)

    def test_saves_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "Saves")
        assert {"save_id", "player_name", "difficulty", "last_updated"}.issubset(cols)

    def test_event_log_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "Event_Log")
        assert {"event_id", "save_id", "turn_id", "event_type", "target_entity", "payload"}.issubset(cols)

    def test_state_cache_columns(self, tmp_db: str) -> None:
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            cols = _column_names(conn, "State_Cache")
        assert {"save_id", "entity_id", "stat_key", "stat_value"}.issubset(cols)

    def test_entity_type_constraint(self, tmp_db: str) -> None:
        """Entities.entity_type must reject values outside the allowed set."""
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO Entities (entity_id, entity_type, name) VALUES (?, ?, ?);",
                    ("e1", "monster", "Goblin"),
                )

    def test_saves_difficulty_constraint(self, tmp_db: str) -> None:
        """Saves.difficulty must reject values outside Normal/Hardcore."""
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?, ?, ?, ?);",
                    ("s1", "Hero", "Easy", "2026-01-01T00:00:00"),
                )

    def test_foreign_keys_enforced(self, tmp_db: str) -> None:
        """Entity_Stats must reject inserts referencing non-existent entity_id."""
        create_universe_db(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            conn.execute("PRAGMA foreign_keys=ON;")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO Entity_Stats VALUES (?, ?, ?);",
                    ("ghost_entity", "HP", "100"),
                )
