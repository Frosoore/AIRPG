"""
tests/test_checkpoint.py

Unit tests for database/checkpoint.py — verifies rewind correctness,
checkpoint listing, and Hardcore save deletion.
"""

import sqlite3
from pathlib import Path

import pytest

from database.schema import create_universe_db
from database.event_sourcing import EventSourcer
from database.checkpoint import CheckpointManager


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def _setup_db(tmp_path: Path) -> tuple[str, EventSourcer, CheckpointManager]:
    db_path = str(tmp_path / "universe.db")
    create_universe_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute(
            "INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?, ?, ?, ?);",
            ("save1", "Hero", "Normal", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?, ?, ?, ?);",
            ("player1", "player", "Aria", 1),
        )
        conn.commit()

    es = EventSourcer(db_path)
    cm = CheckpointManager(db_path)
    return db_path, es, cm


def _append_hp_events(es: EventSourcer, save_id: str, turns: int, delta: float = 10) -> None:
    """Append one stat_change event per turn (HP +=delta)."""
    for turn in range(1, turns + 1):
        es.append_event(
            save_id, turn, "stat_change", "player1",
            {"entity_id": "player1", "stat_key": "HP", "delta": delta},
        )


@pytest.fixture
def ctx(tmp_path: Path) -> tuple[str, EventSourcer, CheckpointManager]:
    return _setup_db(tmp_path)


# ---------------------------------------------------------------------------
# rewind
# ---------------------------------------------------------------------------

class TestRewind:
    def test_events_after_target_deleted(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        _append_hp_events(es, "save1", turns=10)

        cm.rewind("save1", target_turn_id=5)

        remaining = es.get_events("save1")
        assert all(ev["turn_id"] <= 5 for ev in remaining), (
            "Events with turn_id > 5 must be deleted"
        )

    def test_events_at_target_preserved(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        _append_hp_events(es, "save1", turns=10)

        cm.rewind("save1", target_turn_id=5)

        remaining = es.get_events("save1")
        assert len(remaining) == 5

    def test_state_cache_reflects_rewound_state(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        # Each turn adds 10 HP → after turn 5 HP=50, after turn 10 HP=100
        _append_hp_events(es, "save1", turns=10, delta=10)
        # Build the cache fully first
        es.rebuild_state_cache("save1")

        cm.rewind("save1", target_turn_id=5)

        stats = es.get_current_stats("save1", "player1")
        assert stats.get("HP") == "50"

    def test_summary_dict_structure(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        _append_hp_events(es, "save1", turns=10)

        result = cm.rewind("save1", target_turn_id=3)

        assert result["deleted_events"] == 7
        assert result["rebuilt_to_turn"] == 3

    def test_rewind_to_zero_clears_cache(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        _append_hp_events(es, "save1", turns=5)

        cm.rewind("save1", target_turn_id=0)

        assert es.get_events("save1") == []
        stats = es.get_current_stats("save1", "player1")
        assert stats == {}

    def test_rewind_beyond_last_turn_is_noop(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        _append_hp_events(es, "save1", turns=5)

        result = cm.rewind("save1", target_turn_id=100)

        assert result["deleted_events"] == 0
        assert len(es.get_events("save1")) == 5


# ---------------------------------------------------------------------------
# list_checkpoints
# ---------------------------------------------------------------------------

class TestListCheckpoints:
    def test_returns_sorted_unique_turns(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        for turn in [3, 1, 2, 3, 1]:  # duplicates intentional
            es.append_event("save1", turn, "dialogue", "player1", {"text": "hi"})

        checkpoints = cm.list_checkpoints("save1")
        assert checkpoints == [1, 2, 3]

    def test_empty_for_no_events(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        assert cm.list_checkpoints("save1") == []

    def test_empty_for_unknown_save(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        assert cm.list_checkpoints("ghost_save") == []

    def test_list_after_rewind_reflects_deletion(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        _append_hp_events(es, "save1", turns=10)

        cm.rewind("save1", target_turn_id=5)
        checkpoints = cm.list_checkpoints("save1")

        assert max(checkpoints) == 5
        assert 6 not in checkpoints


# ---------------------------------------------------------------------------
# delete_save (Hardcore mode)
# ---------------------------------------------------------------------------

class TestDeleteSave:
    def test_deletes_directory(self, ctx: tuple, tmp_path: Path) -> None:
        db_path, es, cm = ctx
        universe_dir = tmp_path / "my_universe"
        universe_dir.mkdir()
        (universe_dir / "some_file.txt").write_text("data")

        cm.delete_save("save1", str(universe_dir))

        assert not universe_dir.exists()

    def test_removes_save_from_db(self, ctx: tuple, tmp_path: Path) -> None:
        db_path, es, cm = ctx
        universe_dir = tmp_path / "my_universe"
        universe_dir.mkdir()

        cm.delete_save("save1", str(universe_dir))

        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT * FROM Saves WHERE save_id = 'save1';").fetchone()
        assert row is None

    def test_succeeds_even_if_dir_not_found(self, ctx: tuple) -> None:
        db_path, es, cm = ctx
        # Should not raise FileNotFoundError, but should still delete from DB
        cm.delete_save("save1", "/nonexistent/path/universe")
        
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT * FROM Saves WHERE save_id = 'save1';").fetchone()
        assert row is None
