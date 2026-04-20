"""
tests/test_chronicler.py

Unit tests for core/chronicler.py.

LLM backend is fully mocked.  Real universe db used for entity and
Event_Log verification.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.chronicler import ChroniclerEngine, ChroniclerResult
from database.event_sourcing import EventSourcer
from database.schema import create_universe_db
from llm_engine.base import LLMBackend, LLMMessage, LLMResponse


# ---------------------------------------------------------------------------
# Stub LLM backend
# ---------------------------------------------------------------------------

class _StubLLM(LLMBackend):
    def __init__(self, response: LLMResponse) -> None:
        self._response = response

    def complete(self, messages: list[LLMMessage], stream: bool = False, **kwargs) -> LLMResponse:
        self.last_messages = list(messages)
        return self._response

    def stream_tokens(self, messages, **kwargs):
        yield ""

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Universe db with one save, one NPC, one faction."""
    path = str(tmp_path / "universe.db")
    create_universe_db(path)

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("INSERT INTO Stat_Definitions (stat_id, name, value_type) VALUES ('1', 'HP', 'numeric'), ('2', 'Gold', 'numeric'), ('3', 'Title', 'categorical'), ('4', 'Status', 'categorical'), ('5', 'Army_Size', 'numeric'), ('6', 'Wealth', 'numeric')")
        conn.execute(
            "INSERT INTO Saves (save_id, player_name, difficulty, last_updated) "
            "VALUES (?,?,?,?);",
            ("s1", "Hero", "Normal", "2026-01-01T00:00:00"),
        )
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
                     ("player1", "player", "Aria", 1))
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
                     ("king1", "npc", "King Aldric", 1))
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
                     ("guild1", "faction", "Merchants Guild", 1))
        conn.commit()

    es = EventSourcer(path)
    # Seed player stats (should be ignored by Chronicler)
    es.append_event("s1", 0, "entity_create", "player1",
                    {"entity_id": "player1", "entity_type": "player", "name": "Aria"})
    es.append_event("s1", 0, "stat_change", "player1",
                    {"entity_id": "player1", "stat_key": "HP", "delta": 100})
    # Seed NPC stats
    es.append_event("s1", 0, "entity_create", "king1",
                    {"entity_id": "king1", "entity_type": "npc", "name": "King Aldric"})
    es.append_event("s1", 0, "stat_change", "king1",
                    {"entity_id": "king1", "stat_key": "Health", "delta": 100})
    es.append_event("s1", 0, "stat_change", "king1",
                    {"entity_id": "king1", "stat_key": "Army_Size", "delta": 5000})
    # Seed faction stats
    es.append_event("s1", 0, "entity_create", "guild1",
                    {"entity_id": "guild1", "entity_type": "faction", "name": "Merchants Guild"})
    es.append_event("s1", 0, "stat_change", "guild1",
                    {"entity_id": "guild1", "stat_key": "Wealth", "delta": 10000})
    es.rebuild_state_cache("s1")
    return path


def _make_chronicler(
    db_path: str,
    response: LLMResponse,
    trigger_interval: int = 50,
) -> tuple[ChroniclerEngine, _StubLLM]:
    llm = _StubLLM(response)
    es = EventSourcer(db_path)
    engine = ChroniclerEngine(
        llm=llm, event_sourcer=es, db_path=db_path,
        trigger_interval=trigger_interval,
    )
    return engine, llm


# ---------------------------------------------------------------------------
# should_trigger
# ---------------------------------------------------------------------------

class TestShouldTrigger:
    def test_fires_at_exactly_interval(self) -> None:
        engine, _ = _make_chronicler.__wrapped__ if hasattr(_make_chronicler, '__wrapped__') else (_make_chronicler, None)
        # Use directly
        llm = _StubLLM(LLMResponse("", None, "stop"))
        es = MagicMock()
        engine = ChroniclerEngine(llm=llm, event_sourcer=es, db_path="", trigger_interval=50)
        assert engine.should_trigger(50, 0) is True

    def test_does_not_fire_below_interval(self) -> None:
        llm = _StubLLM(LLMResponse("", None, "stop"))
        engine = ChroniclerEngine(llm=llm, event_sourcer=MagicMock(), db_path="", trigger_interval=50)
        assert engine.should_trigger(49, 0) is False

    def test_fires_well_above_interval(self) -> None:
        llm = _StubLLM(LLMResponse("", None, "stop"))
        engine = ChroniclerEngine(llm=llm, event_sourcer=MagicMock(), db_path="", trigger_interval=50)
        assert engine.should_trigger(200, 0) is True

    def test_custom_trigger_interval(self) -> None:
        llm = _StubLLM(LLMResponse("", None, "stop"))
        engine = ChroniclerEngine(llm=llm, event_sourcer=MagicMock(), db_path="", trigger_interval=10)
        assert engine.should_trigger(10, 0) is True
        assert engine.should_trigger(9, 0) is False

    def test_trigger_relative_to_last_chronicle(self) -> None:
        llm = _StubLLM(LLMResponse("", None, "stop"))
        engine = ChroniclerEngine(llm=llm, event_sourcer=MagicMock(), db_path="", trigger_interval=50)
        assert engine.should_trigger(100, 50) is True
        assert engine.should_trigger(99, 50) is False


# ---------------------------------------------------------------------------
# run — valid LLM response
# ---------------------------------------------------------------------------

class TestRunValid:
    def test_entity_stat_updated_in_event_log(self, db_path) -> None:
        response = LLMResponse(
            narrative_text="",
            tool_call={"state_changes": [
                {"entity_id": "king1", "stat_key": "Army_Size", "delta": -500.0}
            ]},
            finish_reason="stop",
        )
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)

        assert "king1" in result.updated_entities
        assert result.events_appended == 1

        es = EventSourcer(db_path)
        events = es.get_events("s1")
        chronicle_events = [e for e in events if e["event_type"] == "chronicler_update"]
        assert len(chronicle_events) == 1
        assert chronicle_events[0]["payload"]["stat_key"] == "Army_Size"
        assert chronicle_events[0]["payload"]["delta"] == -500.0

    def test_multiple_entity_updates(self, db_path) -> None:
        response = LLMResponse(
            narrative_text="",
            tool_call={"state_changes": [
                {"entity_id": "king1", "stat_key": "Army_Size", "delta": -200.0},
                {"entity_id": "guild1", "stat_key": "Wealth", "delta": 1000.0},
            ]},
            finish_reason="stop",
        )
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)

        assert result.events_appended == 2
        assert "king1" in result.updated_entities
        assert "guild1" in result.updated_entities

    def test_stat_set_value_persisted(self, db_path) -> None:
        response = LLMResponse(
            narrative_text="",
            tool_call={"state_changes": [
                {"entity_id": "king1", "stat_key": "Status", "value": "Dead"}
            ]},
            finish_reason="stop",
        )
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)

        assert result.events_appended == 1
        es = EventSourcer(db_path)
        events = es.get_events("s1")
        chronicle_events = [e for e in events if e["event_type"] == "chronicler_update"]
        assert chronicle_events[0]["payload"]["value"] == "Dead"

    def test_world_tension_level_passed_to_prompt_builder(self, db_path) -> None:
        """World_Tension_Level from Universe_Meta must appear in system prompt."""
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO Universe_Meta VALUES (?,?);",
                ("World_Tension_Level", "0.9"),
            )
            conn.commit()

        response = LLMResponse("", None, "stop")
        engine, llm = _make_chronicler(db_path, response)
        engine.run("s1", 55)

        system_msgs = [m for m in llm.last_messages if m["role"] == "system"]
        # 0.9 tension should trigger high-tension guidance
        combined = " ".join(m["content"] for m in system_msgs).lower()
        assert "high" in combined or "dramatic" in combined

    def test_default_tension_when_key_absent(self, db_path) -> None:
        response = LLMResponse("", None, "stop")
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)
        assert result.world_tension_used == 0.3  # _DEFAULT_TENSION

    def test_player_entity_excluded_from_snapshot(self, db_path) -> None:
        """The player entity must never appear in off-screen entities."""
        response = LLMResponse("", None, "stop")
        engine, llm = _make_chronicler(db_path, response)
        engine.run("s1", 55)

        user_msg = next((m for m in llm.last_messages if m["role"] == "user"), None)
        assert user_msg is not None
        assert "player1" not in user_msg["content"]
        assert "Aria" not in user_msg["content"]


# ---------------------------------------------------------------------------
# run — malformed / empty LLM response
# ---------------------------------------------------------------------------

class TestRunRobustness:
    def test_no_tool_call_returns_empty_result(self, db_path) -> None:
        response = LLMResponse("some prose but no json", None, "stop")
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)

        assert result.events_appended == 0
        assert result.updated_entities == []

    def test_malformed_state_changes_not_list(self, db_path) -> None:
        response = LLMResponse(
            "",
            {"state_changes": "not a list"},
            "stop",
        )
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)
        assert result.events_appended == 0

    def test_unknown_entity_silently_skipped(self, db_path) -> None:
        response = LLMResponse(
            "",
            {"state_changes": [
                {"entity_id": "ghost_king", "stat_key": "HP", "delta": -10}
            ]},
            "stop",
        )
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)
        assert result.events_appended == 0
        assert result.updated_entities == []

    def test_llm_exception_does_not_raise(self, db_path) -> None:
        """LLM errors must never crash the Chronicler."""
        from llm_engine.base import LLMConnectionError

        class _FailingLLM(LLMBackend):
            def complete(self, messages, stream=False):
                raise LLMConnectionError("server down")
            def stream_tokens(self, messages, **kwargs):
                yield ""
            def is_available(self):
                return False

        es = EventSourcer(db_path)
        engine = ChroniclerEngine(llm=_FailingLLM(), event_sourcer=es, db_path=db_path)
        result = engine.run("s1", 55)
        assert result.events_appended == 0  # no crash, empty result

    def test_change_missing_stat_key_skipped(self, db_path) -> None:
        response = LLMResponse(
            "",
            {"state_changes": [
                {"entity_id": "king1", "delta": -10}  # missing stat_key
            ]},
            "stop",
        )
        engine, _ = _make_chronicler(db_path, response)
        result = engine.run("s1", 55)
        assert result.events_appended == 0


# ---------------------------------------------------------------------------
# force_trigger
# ---------------------------------------------------------------------------

class TestForceTrigger:
    def test_force_trigger_produces_same_result_as_run(self, db_path) -> None:
        response = LLMResponse(
            "",
            {"state_changes": [
                {"entity_id": "king1", "stat_key": "Army_Size", "delta": -100.0}
            ]},
            "stop",
        )
        engine, _ = _make_chronicler(db_path, response)
        result = engine.force_trigger("s1", 55)
        assert result.events_appended == 1
        assert "king1" in result.updated_entities

    def test_force_trigger_regardless_of_interval(self, db_path) -> None:
        """force_trigger must run even when should_trigger would return False."""
        response = LLMResponse("", None, "stop")
        engine, _ = _make_chronicler(db_path, response, trigger_interval=1000)
        # Turn 1 is far below interval=1000
        assert engine.should_trigger(1, 0) is False
        # force_trigger must still run
        result = engine.force_trigger("s1", 1)
        assert isinstance(result, ChroniclerResult)
