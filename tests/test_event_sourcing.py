"""
tests/test_event_sourcing.py

Unit tests for database/event_sourcing.py — verifies event appending,
retrieval, State_Cache rebuilding, and the _apply_event pure function.
"""

from pathlib import Path

import pytest

from database.schema import create_universe_db
from database.event_sourcing import EventSourcer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> tuple[str, EventSourcer]:
    """Provision a fresh universe db and return (db_path, EventSourcer)."""
    db_path = str(tmp_path / "universe.db")
    create_universe_db(db_path)

    # Seed the minimum required rows so FK constraints are satisfied
    import sqlite3
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
        conn.execute(
            "INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?, ?, ?, ?);",
            ("npc1", "npc", "Goblin", 1),
        )
        conn.commit()

    return db_path, EventSourcer(db_path)


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------

class TestAppendEvent:
    def test_returns_incrementing_ids(self, db: tuple) -> None:
        _, es = db
        id1 = es.append_event("save1", 1, "dialogue", "player1", {"text": "Hello"})
        id2 = es.append_event("save1", 1, "dialogue", "player1", {"text": "World"})
        assert id2 > id1

    def test_event_stored_correctly(self, db: tuple) -> None:
        db_path, es = db
        es.append_event("save1", 3, "stat_change", "player1", {"entity_id": "player1", "stat_key": "HP", "delta": -10})
        events = es.get_events("save1")
        assert len(events) == 1
        ev = events[0]
        assert ev["turn_id"] == 3
        assert ev["event_type"] == "stat_change"
        assert ev["payload"]["stat_key"] == "HP"
        assert ev["payload"]["delta"] == -10


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------

class TestGetEvents:
    def test_returns_all_events(self, db: tuple) -> None:
        _, es = db
        for turn in range(1, 6):
            es.append_event("save1", turn, "dialogue", "player1", {"text": f"turn{turn}"})
        events = es.get_events("save1")
        assert len(events) == 5

    def test_up_to_turn_id_filter(self, db: tuple) -> None:
        _, es = db
        for turn in range(1, 11):
            es.append_event("save1", turn, "dialogue", "player1", {"text": f"t{turn}"})
        events = es.get_events("save1", up_to_turn_id=5)
        assert len(events) == 5
        assert all(ev["turn_id"] <= 5 for ev in events)

    def test_returns_empty_for_unknown_save(self, db: tuple) -> None:
        _, es = db
        assert es.get_events("nonexistent_save") == []

    def test_payload_decoded_to_dict(self, db: tuple) -> None:
        _, es = db
        es.append_event("save1", 1, "stat_set", "player1", {"entity_id": "player1", "stat_key": "Name", "value": "Aria"})
        events = es.get_events("save1")
        assert isinstance(events[0]["payload"], dict)


# ---------------------------------------------------------------------------
# _apply_event (pure function)
# ---------------------------------------------------------------------------

class TestApplyEvent:
    def test_entity_create(self) -> None:
        cache: dict = {}
        event = {"event_type": "entity_create", "target_entity": "p1",
                 "payload": {"entity_id": "p1", "entity_type": "player", "name": "Hero"}}
        result = EventSourcer._apply_event(event, cache)
        assert "p1" in result

    def test_stat_change_delta(self) -> None:
        cache = {"p1": {"HP": "100"}}
        event = {"event_type": "stat_change", "target_entity": "p1",
                 "payload": {"entity_id": "p1", "stat_key": "HP", "delta": -30}}
        result = EventSourcer._apply_event(event, cache)
        assert result["p1"]["HP"] == "70"

    def test_stat_change_delta_from_zero(self) -> None:
        cache: dict = {}
        event = {"event_type": "stat_change", "target_entity": "p1",
                 "payload": {"entity_id": "p1", "stat_key": "Gold", "delta": 50}}
        result = EventSourcer._apply_event(event, cache)
        assert result["p1"]["Gold"] == "50"

    def test_stat_set_string_value(self) -> None:
        cache = {"p1": {"Status": "alive"}}
        event = {"event_type": "stat_set", "target_entity": "p1",
                 "payload": {"entity_id": "p1", "stat_key": "Status", "value": "dead"}}
        result = EventSourcer._apply_event(event, cache)
        assert result["p1"]["Status"] == "dead"

    def test_stat_change_with_value_key(self) -> None:
        """stat_change with a 'value' key (not 'delta') acts like stat_set."""
        cache: dict = {}
        event = {"event_type": "stat_change", "target_entity": "p1",
                 "payload": {"entity_id": "p1", "stat_key": "Alignment", "value": "Chaotic"}}
        result = EventSourcer._apply_event(event, cache)
        assert result["p1"]["Alignment"] == "Chaotic"

    def test_dialogue_event_ignored(self) -> None:
        cache = {"p1": {"HP": "50"}}
        event = {"event_type": "dialogue", "target_entity": "p1",
                 "payload": {"speaker": "p1", "text": "Hello"}}
        result = EventSourcer._apply_event(event, cache)
        assert result == {"p1": {"HP": "50"}}

    def test_integer_display_preserved(self) -> None:
        """Whole-number results must be stored without decimal point."""
        cache = {"p1": {"Gold": "10"}}
        event = {"event_type": "stat_change", "target_entity": "p1",
                 "payload": {"entity_id": "p1", "stat_key": "Gold", "delta": 5}}
        result = EventSourcer._apply_event(event, cache)
        assert result["p1"]["Gold"] == "15"
        assert "." not in result["p1"]["Gold"]

    def test_float_delta_preserved(self) -> None:
        cache = {"p1": {"Mana": "10"}}
        event = {"event_type": "stat_change", "target_entity": "p1",
                 "payload": {"entity_id": "p1", "stat_key": "Mana", "delta": 0.5}}
        result = EventSourcer._apply_event(event, cache)
        assert result["p1"]["Mana"] == "10.5"


# ---------------------------------------------------------------------------
# rebuild_state_cache + get_current_stats
# ---------------------------------------------------------------------------

class TestRebuildStateCache:
    def _seed_entity(self, es: EventSourcer, save_id: str, entity_id: str,
                     entity_type: str, name: str) -> None:
        es.append_event(save_id, 0, "entity_create", entity_id,
                        {"entity_id": entity_id, "entity_type": entity_type, "name": name})

    def test_full_replay(self, db: tuple) -> None:
        _, es = db
        self._seed_entity(es, "save1", "player1", "player", "Aria")
        es.append_event("save1", 1, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "HP", "delta": 100})
        es.append_event("save1", 2, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "HP", "delta": -20})
        es.append_event("save1", 3, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "Gold", "delta": 50})

        es.rebuild_state_cache("save1")
        stats = es.get_current_stats("save1", "player1")
        assert stats["HP"] == "80"
        assert stats["Gold"] == "50"

    def test_partial_replay_up_to_turn(self, db: tuple) -> None:
        _, es = db
        self._seed_entity(es, "save1", "player1", "player", "Aria")
        es.append_event("save1", 1, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "HP", "delta": 100})
        es.append_event("save1", 2, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "HP", "delta": -20})
        es.append_event("save1", 3, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "HP", "delta": -30})

        es.rebuild_state_cache("save1", up_to_turn_id=2)
        stats = es.get_current_stats("save1", "player1")
        assert stats["HP"] == "80"  # only turns 0-2 applied

    def test_multiple_entities(self, db: tuple) -> None:
        _, es = db
        self._seed_entity(es, "save1", "player1", "player", "Aria")
        self._seed_entity(es, "save1", "npc1", "npc", "Goblin")
        es.append_event("save1", 1, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "HP", "delta": 100})
        es.append_event("save1", 1, "stat_change", "npc1",
                        {"entity_id": "npc1", "stat_key": "HP", "delta": 30})

        es.rebuild_state_cache("save1")
        assert es.get_current_stats("save1", "player1")["HP"] == "100"
        assert es.get_current_stats("save1", "npc1")["HP"] == "30"

    def test_rebuild_is_idempotent(self, db: tuple) -> None:
        _, es = db
        self._seed_entity(es, "save1", "player1", "player", "Aria")
        es.append_event("save1", 1, "stat_change", "player1",
                        {"entity_id": "player1", "stat_key": "HP", "delta": 75})

        es.rebuild_state_cache("save1")
        es.rebuild_state_cache("save1")
        stats = es.get_current_stats("save1", "player1")
        assert stats["HP"] == "75"

    def test_get_current_stats_empty_for_unknown_entity(self, db: tuple) -> None:
        _, es = db
        es.rebuild_state_cache("save1")
        assert es.get_current_stats("save1", "ghost") == {}
