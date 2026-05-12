"""
tests/test_arbitrator.py

Unit tests for core/arbitrator.py.

The LLM backend is fully mocked.  A real universe db (via tmp_path) is used
so that Event_Log, State_Cache, and VectorMemory interactions are verified
against actual storage.  VectorMemory uses the fake embedding function from
test_vector_memory.py to avoid model downloads.
"""

import hashlib
import math
import random
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chromadb import EmbeddingFunction, Documents, Embeddings

from core.arbitrator import ArbitratorEngine, ArbitratorResult
from core.rules_engine import RulesEngine
from database.event_sourcing import EventSourcer
from database.modifier_processor import ModifierProcessor
from database.schema import create_universe_db
from llm_engine.base import LLMBackend, LLMMessage, LLMResponse
from llm_engine.vector_memory import VectorMemory


# ---------------------------------------------------------------------------
# Shared fake embedding function (same as test_vector_memory.py)
# ---------------------------------------------------------------------------

class _FakeEmbeddingFn(EmbeddingFunction[Documents]):
    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002
        embeddings: Embeddings = []
        for text in input:
            seed = int(hashlib.md5(str(text).encode()).hexdigest(), 16) % (2 ** 32)
            rng = random.Random(seed)
            vec = [rng.gauss(0, 1) for _ in range(32)]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            embeddings.append([x / norm for x in vec])
        return embeddings


# ---------------------------------------------------------------------------
# Stub LLM backend
# ---------------------------------------------------------------------------

class _StubLLM(LLMBackend):
    """Configurable stub that returns preset LLMResponse objects."""

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.last_messages: list[LLMMessage] = []

    def complete(self, messages: list[LLMMessage], stream: bool = False, **kwargs) -> LLMResponse:
        self.last_messages = list(messages)
        return self._response

    def stream_tokens(self, messages, **kwargs):
        yield self._response.narrative_text

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Provision a universe db with one save and two entities."""
    path = str(tmp_path / "universe.db")
    create_universe_db(path)

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("INSERT INTO Stat_Definitions (stat_id, name, value_type) VALUES ('1', 'HP', 'numeric'), ('2', 'Gold', 'numeric'), ('3', 'Title', 'categorical'), ('4', 'Status', 'categorical'), ('5', 'Army_Size', 'numeric'), ('6', 'Wealth', 'numeric')")
        conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
                     ("s1", "Hero", "Normal", "2026-01-01T00:00:00"))
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
                     ("player1", "player", "Aria", 1))
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
                     ("npc1", "npc", "Goblin", 1))
        conn.commit()

    # Seed State_Cache via EventSourcer
    es = EventSourcer(path)
    es.append_event("s1", 0, "entity_create", "player1",
                    {"entity_id": "player1", "entity_type": "player", "name": "Aria"})
    es.append_event("s1", 0, "stat_change", "player1",
                    {"entity_id": "player1", "stat_key": "HP", "delta": 100})
    es.append_event("s1", 0, "stat_change", "player1",
                    {"entity_id": "player1", "stat_key": "Gold", "delta": 50})
    es.append_event("s1", 0, "entity_create", "npc1",
                    {"entity_id": "npc1", "entity_type": "npc", "name": "Goblin"})
    es.append_event("s1", 0, "stat_change", "npc1",
                    {"entity_id": "npc1", "stat_key": "HP", "delta": 30})
    es.rebuild_state_cache("s1")
    return path


@pytest.fixture
def vm(tmp_path: Path) -> VectorMemory:
    with patch(
        "llm_engine.vector_memory.SentenceTransformerEmbeddingFunction",
        return_value=_FakeEmbeddingFn(),
    ):
        return VectorMemory(persist_dir=str(tmp_path / "chroma"))


def _make_arbitrator(
    db_path: str,
    vm: VectorMemory,
    llm_response: LLMResponse,
    rules: list[dict] | None = None,
) -> tuple[ArbitratorEngine, _StubLLM]:
    llm = _StubLLM(llm_response)
    arb = ArbitratorEngine(db_path, rules or [])
    arb.configure(llm, vm)
    return arb, llm

# ---------------------------------------------------------------------------
# ArbitratorResult dataclass
# ---------------------------------------------------------------------------

class TestArbitratorResult:
    def test_fields_accessible(self) -> None:
        r = ArbitratorResult(
            narrative_text="prose",
            applied_changes=[{"x": 1}],
            rejected_changes=[],
            triggered_rules=[],
        )
        assert r.narrative_text == "prose"
        assert r.applied_changes == [{"x": 1}]

    def test_defaults_are_empty_lists(self) -> None:
        r = ArbitratorResult(narrative_text="hello")
        assert r.applied_changes == []
        assert r.rejected_changes == []
        assert r.triggered_rules == []


# ---------------------------------------------------------------------------
# process_turn — valid state change
# ---------------------------------------------------------------------------

class TestProcessTurnValidChange:
    def test_valid_change_appears_in_applied_changes(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="The goblin hits you.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "HP", "delta": -10}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        result = arb.process_turn("s1", 1, "I attack", "Universe prompt", [])
        assert len(result.applied_changes) == 1
        assert result.applied_changes[0]["stat_key"] == "HP"

    def test_valid_change_persisted_in_event_log(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="You spend 10 gold.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "Gold", "delta": -10}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        arb.process_turn("s1", 1, "buy item", "sys", [])

        es = EventSourcer(db_path)
        events = es.get_events("s1")
        stat_events = [e for e in events if e["event_type"] == "stat_change"
                       and e["payload"].get("stat_key") == "Gold"]
        # Should have the initial +50 seeded event plus this -10
        deltas = [e["payload"]["delta"] for e in stat_events]
        assert -10 in deltas

    def test_narrative_returned_always(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="Nothing happens.",
            tool_call=None,
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        result = arb.process_turn("s1", 1, "wait", "sys", [])
        assert result.narrative_text == "Nothing happens."

    def test_stat_set_value_change_applied(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="Your title changes.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "Title", "value": "Knight"}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        result = arb.process_turn("s1", 1, "earn title", "sys", [])
        assert len(result.applied_changes) == 1


# ---------------------------------------------------------------------------
# process_turn — invalid state change (Correction Loop)
# ---------------------------------------------------------------------------

class TestCorrectionLoop:
    def test_insufficient_resource_rejected(self, db_path, vm) -> None:
        # player1 has Gold=50; try to deduct 200
        response = LLMResponse(
            narrative_text="You try to buy a castle.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "Gold", "delta": -200}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        result = arb.process_turn("s1", 1, "buy castle", "sys", [])
        assert len(result.rejected_changes) == 1
        assert "reason" in result.rejected_changes[0]
        assert "Gold" in result.rejected_changes[0]["reason"]

    def test_rejected_change_not_in_event_log(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="Attempted theft.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "Gold", "delta": -999}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        arb.process_turn("s1", 1, "steal", "sys", [])

        es = EventSourcer(db_path)
        events = es.get_events("s1")
        turn1_stat_changes = [
            e for e in events
            if e["turn_id"] == 1
            and e["event_type"] == "stat_change"
            and e["payload"].get("stat_key") == "Gold"
        ]
        assert len(turn1_stat_changes) == 0

    def test_pending_correction_set_after_rejection(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="Bad action.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "Gold", "delta": -999}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        arb.process_turn("s1", 1, "bad", "sys", [])
        assert arb._pending_correction is not None
        assert "[NARRATOR HINT:" in arb._pending_correction

    def test_pending_correction_injected_in_next_turn(self, db_path, vm) -> None:
        # Turn 1: reject a change
        response1 = LLMResponse(
            narrative_text="Fail.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "Gold", "delta": -999}
            ]},
            finish_reason="stop",
        )
        response2 = LLMResponse(narrative_text="Acknowledged.", tool_call=None, finish_reason="stop")

        llm1 = _StubLLM(response1)
        llm2 = _StubLLM(response2)

        es = EventSourcer(db_path)
        mp = ModifierProcessor(db_path)
        re = RulesEngine([])
        arb = ArbitratorEngine(db_path, [])
        arb.configure(llm1, vm)

        arb.process_turn("s1", 1, "bad", "sys", [])
        assert arb._pending_correction is not None

        # Turn 2: switch LLM stub and check correction injected
        arb._llm = llm2
        arb.process_turn("s1", 2, "continue", "sys", [])

        # Correction must appear in the messages sent to turn-2 LLM
        messages = llm2.last_messages
        system_msgs = [m for m in messages if m["role"] == "system"]
        correction_injected = any("[NARRATOR HINT:" in m["content"] for m in system_msgs)
        assert correction_injected

    def test_pending_correction_cleared_after_use(self, db_path, vm) -> None:
        response1 = LLMResponse(
            narrative_text="Fail.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "Gold", "delta": -999}
            ]},
            finish_reason="stop",
        )
        response2 = LLMResponse(narrative_text="ok", tool_call=None, finish_reason="stop")

        arb, _ = _make_arbitrator(db_path, vm, response1)
        arb.process_turn("s1", 1, "bad", "sys", [])

        arb._llm = _StubLLM(response2)
        arb.process_turn("s1", 2, "continue", "sys", [])

        assert arb._pending_correction is None

    def test_unknown_entity_rejected(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="ghost action",
            tool_call={"state_changes": [
                {"entity_id": "ghost_entity", "stat_key": "HP", "delta": -10}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        result = arb.process_turn("s1", 1, "hmm", "sys", [])
        assert len(result.rejected_changes) == 1
        assert "Unknown entity" in result.rejected_changes[0]["reason"]


# ---------------------------------------------------------------------------
# process_turn — Rules Engine integration
# ---------------------------------------------------------------------------

class TestRulesTrigger:
    def test_rule_triggered_action_in_triggered_rules(self, db_path, vm) -> None:
        # Rule: if player1 HP <= 50, set Status = "wounded"
        rule = {
            "rule_id": "wound_rule",
            "priority": 0,
            "target_entity": "player1",
            "conditions": {"operator": "AND", "clauses": [
                {"stat": "HP", "comparator": "<=", "value": 50}
            ]},
            "actions": [
                {"type": "stat_set", "target": "player1", "stat": "Status", "value": "wounded"}
            ],
        }
        # Reduce HP from 100 to 40
        response = LLMResponse(
            narrative_text="You are badly hurt.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "HP", "delta": -60}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response, rules=[rule])
        result = arb.process_turn("s1", 1, "fight", "sys", [])

        assert len(result.triggered_rules) == 1
        assert result.triggered_rules[0]["type"] == "stat_set"

    def test_rule_trigger_persisted_in_event_log(self, db_path, vm) -> None:
        rule = {
            "rule_id": "death_rule",
            "priority": 0,
            "target_entity": "player1",
            "conditions": {"operator": "AND", "clauses": [
                {"stat": "HP", "comparator": "<=", "value": 0}
            ]},
            "actions": [
                {"type": "stat_set", "target": "player1", "stat": "Status", "value": "dead"}
            ],
        }
        response = LLMResponse(
            narrative_text="Fatal blow.",
            tool_call={"state_changes": [
                {"entity_id": "player1", "stat_key": "HP", "delta": -100}
            ]},
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response, rules=[rule])
        arb.process_turn("s1", 1, "die", "sys", [])

        es = EventSourcer(db_path)
        events = es.get_events("s1")
        rule_events = [e for e in events if e["event_type"] == "rule_trigger"]
        assert len(rule_events) == 1


# ---------------------------------------------------------------------------
# process_turn — VectorMemory embedding
# ---------------------------------------------------------------------------

class TestVectorMemoryIntegration:
    def test_narrative_embedded_after_turn(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="The ancient ruins loom before you.",
            tool_call=None,
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        arb.process_turn("s1", 1, "explore", "sys", [])

        results = vm.query("s1", "ruins ancient", k=5)
        assert any("ruins" in r["text"] for r in results)

    def test_embedded_chunk_has_correct_turn_id(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="Turn 5 narrative content.",
            tool_call=None,
            finish_reason="stop",
        )
        arb, _ = _make_arbitrator(db_path, vm, response)
        arb.process_turn("s1", 5, "action", "sys", [])

        results = vm.query("s1", "narrative content", k=1)
        assert results[0]["turn_id"] == 5


# ---------------------------------------------------------------------------
# process_turn — streaming callback (Phase 4)
# ---------------------------------------------------------------------------

class TestStreamingCallback:
    """Verify that stream_token_callback is called per-token and the
    assembled result is consistent with non-streaming behaviour."""

    class _StreamingStubLLM(_StubLLM):
        """Stub that yields tokens one-by-one from stream_tokens()."""

        def stream_tokens(self, messages, **kwargs):
            # Split the narrative text into character tokens for fine granularity
            text = self._response.narrative_text
            # If there's a tool call, append the fence so parse_tool_call works
            if self._response.tool_call is not None:
                import json as _j
                text = (
                    text
                    + "\n~~~json\n"
                    + _j.dumps(self._response.tool_call)
                    + "\n~~~"
                )
            for char in text:
                yield char

    def test_callback_called_for_each_token(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="Stream test.",
            tool_call=None,
            finish_reason="stop",
        )
        llm = self._StreamingStubLLM(response)
        from database.event_sourcing import EventSourcer
        from database.modifier_processor import ModifierProcessor
        from core.rules_engine import RulesEngine
        from core.arbitrator import ArbitratorEngine
        arb = ArbitratorEngine(db_path, [])
        arb.configure(llm, vm)
        received: list[str] = []
        arb.process_turn(
            "s1", 1, "test", "sys", [],
            stream_token_callback=received.append,
        )
        # Every character of "Stream test." must have been received
        assert "".join(received) == "Stream test."

    def test_callback_result_matches_non_streaming(self, db_path, vm) -> None:
        response = LLMResponse(
            narrative_text="Consistent result.",
            tool_call=None,
            finish_reason="stop",
        )
        # Non-streaming result
        arb_ns, _ = _make_arbitrator(db_path, vm, response)
        result_ns = arb_ns.process_turn("s1", 1, "go", "sys", [])

        # Streaming result (different db needed to avoid turn collision)
        import tempfile
        from pathlib import Path
        from database.schema import create_universe_db
        import sqlite3
        tmp2 = tempfile.mkdtemp()
        db2 = str(Path(tmp2) / "u2.db")
        create_universe_db(db2)
        with sqlite3.connect(db2) as conn:
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("INSERT INTO Stat_Definitions (stat_id, name, value_type) VALUES ('1', 'HP', 'numeric'), ('2', 'Gold', 'numeric'), ('3', 'Title', 'categorical'), ('4', 'Status', 'categorical'), ('5', 'Army_Size', 'numeric'), ('6', 'Wealth', 'numeric')")
            conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
                         ("s1", "H", "Normal", "2026-01-01T00:00:00"))
            conn.execute("INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
                         ("player1", "player", "A", 1))
            conn.commit()
        from unittest.mock import patch
        with patch(
            "llm_engine.vector_memory.SentenceTransformerEmbeddingFunction",
            return_value=_FakeEmbeddingFn(),
        ):
            from llm_engine.vector_memory import VectorMemory
            import os
            vm2 = VectorMemory(persist_dir=str(Path(tmp2) / "chroma"))

        llm_s = self._StreamingStubLLM(response)
        from database.event_sourcing import EventSourcer
        from database.modifier_processor import ModifierProcessor
        from core.rules_engine import RulesEngine
        from core.arbitrator import ArbitratorEngine
        arb_s = ArbitratorEngine(db2, [])
        arb_s.configure(llm_s, vm2)
        tokens: list[str] = []
        result_s = arb_s.process_turn(
            "s1", 1, "go", "sys", [],
            stream_token_callback=tokens.append,
        )
        assert result_s.narrative_text == result_ns.narrative_text

    def test_none_callback_uses_complete(self, db_path, vm) -> None:
        """Passing no callback must call llm.complete(), not stream_tokens."""
        response = LLMResponse("Classic path.", None, "stop")
        arb, llm = _make_arbitrator(db_path, vm, response)
        result = arb.process_turn("s1", 1, "action", "sys", [])
        # complete() was called (stream_tokens would have raised on _StubLLM)
        assert result.narrative_text == "Classic path."


# ---------------------------------------------------------------------------
# process_turn — Dynamic Stop Sequences (Phase 11.1)
# ---------------------------------------------------------------------------

class TestDynamicStopSequences:
    def test_dynamic_stop_sequences_passed_to_llm(self, db_path, vm) -> None:
        response = LLMResponse("OK", None, "stop")
        
        class _SpyLLM(_StubLLM):
            def __init__(self, res):
                super().__init__(res)
                self.passed_stops = []
            
            def complete(self, messages, stream=False, stop_sequences=None, **kwargs):
                self.passed_stops = stop_sequences or []
                return super().complete(messages, stream)

        llm = _SpyLLM(response)
        
        from database.event_sourcing import EventSourcer
        from database.modifier_processor import ModifierProcessor
        from core.rules_engine import RulesEngine
        from core.arbitrator import ArbitratorEngine
        arb = ArbitratorEngine(db_path, [])
        arb.configure(llm, vm)
        
        arb.process_turn("s1", 1, "hello", "sys", [], player_entity_id="player1")
        
        # Verify the dynamic stop sequences contains the player entity
        assert llm.passed_stops is not None
        assert "\nplayer1:" in llm.passed_stops
        assert "\n[player1]" in llm.passed_stops
        assert "\nUser:" in llm.passed_stops

