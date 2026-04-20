"""
tests/test_modifier_processor.py

Unit tests for database/modifier_processor.py — verifies add_modifier,
apply_modifiers, tick_modifiers expiry, and edge cases.
"""

import sqlite3
from pathlib import Path

import pytest

from database.schema import create_universe_db
from database.event_sourcing import EventSourcer
from database.modifier_processor import ModifierProcessor


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def _setup(tmp_path: Path) -> tuple[str, ModifierProcessor]:
    db_path = str(tmp_path / "universe.db")
    create_universe_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("INSERT INTO Stat_Definitions (stat_id, name, value_type) VALUES ('1', 'HP', 'numeric'), ('2', 'Gold', 'numeric'), ('3', 'Title', 'categorical'), ('4', 'Status', 'categorical'), ('5', 'Strength', 'numeric'), ('6', 'Wealth', 'numeric')")
        conn.execute(            "INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?, ?, ?, ?);",
            ("save1", "Hero", "Normal", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?, ?, ?, ?);",
            ("player1", "player", "Aria", 1),
        )
        conn.execute(
            "INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?, ?, ?, ?);",
            ("npc1", "npc", "Goblin", 1),
        )
        conn.commit()

    # Seed State_Cache so tick_modifiers can scope by save_id
    es = EventSourcer(db_path)
    es.append_event("save1", 0, "entity_create", "player1",
                    {"entity_id": "player1", "entity_type": "player", "name": "Aria"})
    es.append_event("save1", 1, "stat_change", "player1",
                    {"entity_id": "player1", "stat_key": "HP", "delta": 100})
    es.rebuild_state_cache("save1")

    return db_path, ModifierProcessor(db_path)


@pytest.fixture
def ctx(tmp_path: Path) -> tuple[str, ModifierProcessor]:
    return _setup(tmp_path)


# ---------------------------------------------------------------------------
# add_modifier
# ---------------------------------------------------------------------------

class TestAddModifier:
    def test_returns_uuid_string(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mod_id = mp.add_modifier("save1", "player1", "HP", -10.0, 3)
        assert isinstance(mod_id, str)
        assert len(mod_id) == 36  # UUID format

    def test_modifier_persisted_in_db(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mod_id = mp.add_modifier("save1", "player1", "Strength", 5.0, 2)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM Active_Modifiers WHERE modifier_id = ?;", (mod_id,)
            ).fetchone()
        assert row is not None
        assert row[2] == "Strength"  # stat_key
        assert row[3] == 5.0         # delta
        assert row[4] == 2           # minutes_remaining

    def test_zero_turns_raises(self, ctx: tuple) -> None:
        db_path, mp = ctx
        with pytest.raises(ValueError, match="Modifier minutes must be >= 1"):
            mp.add_modifier("save1", "player1", "HP", -5.0, 0)

    def test_negative_turns_raises(self, ctx: tuple) -> None:
        db_path, mp = ctx
        with pytest.raises(ValueError):
            mp.add_modifier("save1", "player1", "HP", -5.0, -3)

    def test_multiple_modifiers_same_stat(self, ctx: tuple) -> None:
        db_path, mp = ctx
        id1 = mp.add_modifier("save1", "player1", "HP", -10.0, 3)
        id2 = mp.add_modifier("save1", "player1", "HP", -5.0, 1)
        assert id1 != id2


# ---------------------------------------------------------------------------
# apply_modifiers
# ---------------------------------------------------------------------------

class TestApplyModifiers:
    def test_single_buff_applied(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "Strength", 10.0, 5)
        result = mp.apply_modifiers("save1", "player1", {"Strength": "20"})
        assert result["Strength"] == "30"

    def test_single_debuff_applied(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "HP", -25.0, 2)
        result = mp.apply_modifiers("save1", "player1", {"HP": "100"})
        assert result["HP"] == "75"

    def test_multiple_modifiers_stacked(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "HP", -10.0, 3)
        mp.add_modifier("save1", "player1", "HP", -15.0, 3)
        result = mp.apply_modifiers("save1", "player1", {"HP": "100"})
        assert result["HP"] == "75"

    def test_no_modifiers_returns_base_stats(self, ctx: tuple) -> None:
        db_path, mp = ctx
        base = {"HP": "100", "Gold": "50"}
        result = mp.apply_modifiers("save1", "player1", base)
        assert result == base

    def test_unaffected_stats_copied_verbatim(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "HP", -10.0, 1)
        result = mp.apply_modifiers("save1", "player1", {"HP": "100", "Name": "Aria"})
        assert result["Name"] == "Aria"

    def test_non_numeric_stat_skipped(self, ctx: tuple) -> None:
        """A modifier targeting a non-numeric stat must leave it unchanged."""
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "Status", 1.0, 1)
        result = mp.apply_modifiers("save1", "player1", {"Status": "alive"})
        assert result["Status"] == "alive"

    def test_base_stats_not_mutated(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "HP", -10.0, 1)
        base = {"HP": "100"}
        mp.apply_modifiers("save1", "player1", base)
        assert base["HP"] == "100"

    def test_float_delta_result(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "Speed", 0.5, 1)
        result = mp.apply_modifiers("save1", "player1", {"Speed": "10"})
        assert result["Speed"] == "10.5"


# ---------------------------------------------------------------------------
# tick_modifiers
# ---------------------------------------------------------------------------

class TestTickModifiers:
    def test_turns_decremented(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mod_id = mp.add_modifier("save1", "player1", "HP", -5.0, 3)
        mp.tick_modifiers("save1")
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT minutes_remaining FROM Active_Modifiers WHERE modifier_id = ?;",
                (mod_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == 2

    def test_modifier_expires_after_n_ticks(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mod_id = mp.add_modifier("save1", "player1", "HP", -5.0, 2)
        mp.tick_modifiers("save1")
        mp.tick_modifiers("save1")
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM Active_Modifiers WHERE modifier_id = ?;", (mod_id,)
            ).fetchone()
        assert row is None

    def test_returns_expired_ids(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mod_id = mp.add_modifier("save1", "player1", "HP", -5.0, 1)
        expired = mp.tick_modifiers("save1")
        assert mod_id in expired

    def test_non_expired_not_in_returned_list(self, ctx: tuple) -> None:
        db_path, mp = ctx
        long_mod = mp.add_modifier("save1", "player1", "HP", -5.0, 5)
        short_mod = mp.add_modifier("save1", "player1", "Mana", -2.0, 1)
        expired = mp.tick_modifiers("save1")
        assert short_mod in expired
        assert long_mod not in expired

    def test_multiple_ticks_partial_expiry(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mod3 = mp.add_modifier("save1", "player1", "HP", -5.0, 3)
        mod1 = mp.add_modifier("save1", "player1", "Mana", -2.0, 1)

        tick1 = mp.tick_modifiers("save1")
        assert mod1 in tick1
        assert mod3 not in tick1

        tick2 = mp.tick_modifiers("save1")
        assert mod3 not in tick2

        tick3 = mp.tick_modifiers("save1")
        assert mod3 in tick3

    def test_no_modifiers_returns_empty_list(self, ctx: tuple) -> None:
        db_path, mp = ctx
        assert mp.tick_modifiers("save1") == []

    def test_expired_modifier_no_longer_applied(self, ctx: tuple) -> None:
        db_path, mp = ctx
        mp.add_modifier("save1", "player1", "HP", -20.0, 1)
        mp.tick_modifiers("save1")  # modifier expires
        result = mp.apply_modifiers("save1", "player1", {"HP": "100"})
        assert result["HP"] == "100"  # no modifier left
