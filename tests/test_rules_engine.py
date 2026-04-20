"""
tests/test_rules_engine.py

Unit tests for core/rules_engine.py — covers condition evaluation (AND/OR,
nesting, comparators), priority ordering, action application, and edge cases.
"""

import pytest
from core.rules_engine import RulesEngine


# ---------------------------------------------------------------------------
# Rule factory helpers
# ---------------------------------------------------------------------------

def _make_rule(
    rule_id: str,
    priority: int,
    conditions: dict,
    actions: list,
    target_entity: str = "*",
) -> dict:
    return {
        "rule_id": rule_id,
        "priority": priority,
        "target_entity": target_entity,
        "conditions": conditions,
        "actions": actions,
    }


def _and(*clauses) -> dict:
    return {"operator": "AND", "clauses": list(clauses)}


def _or(*clauses) -> dict:
    return {"operator": "OR", "clauses": list(clauses)}


def _clause(stat: str, comparator: str, value) -> dict:
    return {"stat": stat, "comparator": comparator, "value": value}


def _stat_change(target: str, stat: str, delta: float) -> dict:
    return {"type": "stat_change", "target": target, "stat": stat, "delta": delta}


def _stat_set(target: str, stat: str, value) -> dict:
    return {"type": "stat_set", "target": target, "stat": stat, "value": value}


# ---------------------------------------------------------------------------
# evaluate() — condition logic
# ---------------------------------------------------------------------------

class TestEvaluateConditions:
    def test_and_fires_when_all_true(self) -> None:
        rule = _make_rule(
            "r1", 0,
            conditions=_and(_clause("HP", "<=", 10), _clause("Poisoned", "==", "true")),
            actions=[_stat_set("player1", "Status", "dying")],
        )
        engine = RulesEngine([rule])
        stats = {"HP": "5", "Poisoned": "true"}
        assert engine.evaluate("player1", stats) == rule["actions"]

    def test_and_does_not_fire_if_one_false(self) -> None:
        rule = _make_rule(
            "r1", 0,
            conditions=_and(_clause("HP", "<=", 10), _clause("Poisoned", "==", "true")),
            actions=[_stat_set("player1", "Status", "dying")],
        )
        engine = RulesEngine([rule])
        stats = {"HP": "5", "Poisoned": "false"}
        assert engine.evaluate("player1", stats) == []

    def test_or_fires_on_first_branch(self) -> None:
        rule = _make_rule(
            "r1", 0,
            conditions=_or(_clause("Gold", "==", 0), _clause("Reputation", "<", -100)),
            actions=[_stat_set("player1", "Status", "bankrupt")],
        )
        engine = RulesEngine([rule])
        assert engine.evaluate("player1", {"Gold": "0", "Reputation": "50"}) == rule["actions"]

    def test_or_fires_on_second_branch(self) -> None:
        rule = _make_rule(
            "r1", 0,
            conditions=_or(_clause("Gold", "==", 0), _clause("Reputation", "<", -100)),
            actions=[_stat_set("player1", "Status", "outcast")],
        )
        engine = RulesEngine([rule])
        assert engine.evaluate("player1", {"Gold": "500", "Reputation": "-200"}) == rule["actions"]

    def test_or_does_not_fire_if_both_false(self) -> None:
        rule = _make_rule(
            "r1", 0,
            conditions=_or(_clause("Gold", "==", 0), _clause("Reputation", "<", -100)),
            actions=[_stat_set("player1", "Status", "outcast")],
        )
        engine = RulesEngine([rule])
        assert engine.evaluate("player1", {"Gold": "100", "Reputation": "50"}) == []

    def test_nested_conditions(self) -> None:
        """(HP <= 10 AND Poisoned == true) OR (Shield == 0 AND Stunned == true)"""
        conditions = _or(
            _and(_clause("HP", "<=", 10), _clause("Poisoned", "==", "true")),
            _and(_clause("Shield", "==", 0), _clause("Stunned", "==", "true")),
        )
        rule = _make_rule("r1", 0, conditions, [_stat_set("e", "Status", "danger")])
        engine = RulesEngine([rule])

        assert engine.evaluate("e", {"HP": "5", "Poisoned": "true", "Shield": "10", "Stunned": "false"})
        assert engine.evaluate("e", {"HP": "50", "Poisoned": "false", "Shield": "0", "Stunned": "true"})
        assert not engine.evaluate("e", {"HP": "50", "Poisoned": "false", "Shield": "10", "Stunned": "false"})


# ---------------------------------------------------------------------------
# evaluate() — target_entity filtering
# ---------------------------------------------------------------------------

class TestTargetEntityFiltering:
    def test_wildcard_fires_for_any_entity(self) -> None:
        rule = _make_rule("r1", 0, _and(_clause("HP", "<=", 0)), [_stat_set("*", "Status", "dead")],
                          target_entity="*")
        engine = RulesEngine([rule])
        assert engine.evaluate("player1", {"HP": "0"})
        assert engine.evaluate("npc42", {"HP": "-5"})

    def test_specific_entity_only_fires_for_that_entity(self) -> None:
        rule = _make_rule("r1", 0, _and(_clause("HP", "<=", 0)), [_stat_set("boss", "Status", "dead")],
                          target_entity="boss")
        engine = RulesEngine([rule])
        assert engine.evaluate("boss", {"HP": "0"})
        assert not engine.evaluate("player1", {"HP": "0"})


# ---------------------------------------------------------------------------
# evaluate() — priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:
    def test_higher_priority_actions_appear_first(self) -> None:
        low_priority = _make_rule("low", 10, _and(_clause("HP", "<", 100)),
                                  [_stat_set("p", "X", "low")])
        high_priority = _make_rule("high", 1, _and(_clause("HP", "<", 100)),
                                   [_stat_set("p", "X", "high")])
        engine = RulesEngine([low_priority, high_priority])  # intentionally reversed order
        actions = engine.evaluate("p", {"HP": "50"})
        assert len(actions) == 2
        assert actions[0]["value"] == "high"
        assert actions[1]["value"] == "low"

    def test_zero_priority_fires_first(self) -> None:
        r0 = _make_rule("r0", 0, _and(_clause("HP", "<", 100)), [_stat_set("p", "A", "first")])
        r5 = _make_rule("r5", 5, _and(_clause("HP", "<", 100)), [_stat_set("p", "A", "second")])
        engine = RulesEngine([r5, r0])
        actions = engine.evaluate("p", {"HP": "1"})
        assert actions[0]["value"] == "first"


# ---------------------------------------------------------------------------
# _compare() — comparator edge cases
# ---------------------------------------------------------------------------

class TestCompare:
    @pytest.mark.parametrize("stat_val,comparator,threshold,expected", [
        ("10", "<=", 10, True),
        ("10", "<=", 9,  False),
        ("10", ">=", 10, True),
        ("10", ">=", 11, False),
        ("10", "==", 10, True),
        ("10", "==", 11, False),
        ("10", "!=", 11, True),
        ("10", "!=", 10, False),
        ("10", "<",  11, True),
        ("10", "<",  10, False),
        ("10", ">",  9,  True),
        ("10", ">",  10, False),
        # boundary: exact zero
        ("0",  "==", 0,  True),
        ("0",  "<",  1,  True),
        ("-5", "<=", 0,  True),
        # float values
        ("10.5", ">=", 10.5, True),
        ("10.5", ">",  10.4, True),
    ])
    def test_numeric_comparisons(self, stat_val, comparator, threshold, expected) -> None:
        assert RulesEngine._compare(stat_val, comparator, threshold) == expected

    def test_string_equality(self) -> None:
        assert RulesEngine._compare("alive", "==", "alive") is True
        assert RulesEngine._compare("alive", "==", "dead") is False

    def test_string_inequality(self) -> None:
        assert RulesEngine._compare("alive", "!=", "dead") is True
        assert RulesEngine._compare("dead", "!=", "dead") is False

    def test_invalid_string_comparator_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported for non-numeric"):
            RulesEngine._compare("alive", ">=", "dead")

    def test_invalid_comparator_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown comparator"):
            RulesEngine._compare("10", "~=", 10)

    def test_invalid_operator_raises(self) -> None:
        rule = _make_rule("r1", 0,
                          {"operator": "XOR", "clauses": [_clause("HP", "==", 0)]},
                          [])
        engine = RulesEngine([rule])
        with pytest.raises(ValueError, match="Unknown logical operator"):
            engine.evaluate("p", {"HP": "0"})

    def test_missing_stat_defaults_to_zero(self) -> None:
        """A stat not present in the snapshot is treated as '0'."""
        rule = _make_rule("r1", 0, _and(_clause("Mana", "<=", 0)),
                          [_stat_set("p", "Status", "dry")])
        engine = RulesEngine([rule])
        # Mana is absent from stats → defaults to 0 → condition fires
        assert engine.evaluate("p", {}) == rule["actions"]


# ---------------------------------------------------------------------------
# apply_actions()
# ---------------------------------------------------------------------------

class TestApplyActions:
    def test_stat_change_positive(self) -> None:
        engine = RulesEngine([])
        result = engine.apply_actions(
            [_stat_change("p", "HP", 20)],
            {"HP": "80"},
        )
        assert result["HP"] == "100"

    def test_stat_change_negative(self) -> None:
        engine = RulesEngine([])
        result = engine.apply_actions(
            [_stat_change("p", "HP", -30)],
            {"HP": "100"},
        )
        assert result["HP"] == "70"

    def test_stat_change_from_zero_when_missing(self) -> None:
        engine = RulesEngine([])
        result = engine.apply_actions([_stat_change("p", "XP", 50)], {})
        assert result["XP"] == "50"

    def test_stat_set_overrides_existing(self) -> None:
        engine = RulesEngine([])
        result = engine.apply_actions(
            [_stat_set("p", "Status", "dead")],
            {"Status": "alive"},
        )
        assert result["Status"] == "dead"

    def test_multiple_actions_applied_sequentially(self) -> None:
        engine = RulesEngine([])
        actions = [
            _stat_change("p", "HP", -50),
            _stat_set("p", "Status", "wounded"),
            _stat_change("p", "XP", 100),
        ]
        result = engine.apply_actions(actions, {"HP": "100", "Status": "healthy", "XP": "0"})
        assert result["HP"] == "50"
        assert result["Status"] == "wounded"
        assert result["XP"] == "100"

    def test_original_stats_not_mutated(self) -> None:
        engine = RulesEngine([])
        original = {"HP": "100"}
        engine.apply_actions([_stat_change("p", "HP", -10)], original)
        assert original["HP"] == "100"

    def test_trigger_event_does_not_mutate_stats(self) -> None:
        engine = RulesEngine([])
        actions = [{"type": "trigger_event", "target": "p", "event": "death"}]
        result = engine.apply_actions(actions, {"HP": "0"})
        assert result == {"HP": "0"}

    def test_integer_display_no_decimal(self) -> None:
        engine = RulesEngine([])
        result = engine.apply_actions([_stat_change("p", "Gold", 5)], {"Gold": "10"})
        assert "." not in result["Gold"]
        assert result["Gold"] == "15"
