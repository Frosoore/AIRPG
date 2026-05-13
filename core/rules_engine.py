"""
core/rules_engine.py

JSON-based Rules Engine for Axiom AI.

The engine evaluates a set of creator-defined rules against an entity's
current stats and returns the list of actions that should be applied.

Canonical Rule JSON schema
--------------------------
{
    "rule_id": "str",
    "priority": int,                  // lower number = higher priority
    "target_entity": "str | '*'",     // '*' means applies to any entity
    "conditions": {
        "operator": "AND" | "OR",
        "clauses": [
            {
                "stat": "str",
                "comparator": "<=" | ">=" | "==" | "!=" | "<" | ">",
                "value": number | "str"
            },
            // nested condition groups are also supported:
            {
                "operator": "AND" | "OR",
                "clauses": [ ... ]
            }
        ]
    },
    "actions": [
        {
            "type": "stat_change" | "stat_set" | "trigger_event" | "set_status",
            "target": "str",          // entity_id to affect
            "stat": "str",            // stat key (for stat_change / stat_set)
            "delta": number,          // signed delta (for stat_change)
            "value": "str" | number   // absolute value (for stat_set / set_status)
        }
    ]
}

Notes
-----
- Rules are evaluated in ascending priority order (0 = highest priority).
- A rule with target_entity == '*' is evaluated for every entity.
- A rule with a specific target_entity is only evaluated when entity_id matches.
- apply_actions() is a pure function: it does NOT write to the database.
  The caller (Arbitrator, Phase 2) is responsible for persisting changes via
  EventSourcer.
"""

from typing import Any, Union


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Stats = dict[str, str]       # entity stat snapshot: stat_key -> raw string value
Action = dict[str, Any]      # a single action dict as defined in the schema
Rule = dict[str, Any]        # a full rule dict as defined in the schema


# ---------------------------------------------------------------------------
# RulesEngine
# ---------------------------------------------------------------------------

class RulesEngine:
    """Evaluates JSON rules against entity stats and produces triggered actions.

    Args:
        rules: List of rule dicts loaded from the Rules table of a universe db.
               Rules are sorted by priority at construction time.
    """

    def __init__(self, rules: list[Rule]) -> None:
        # Sort once at construction; lower priority value = evaluated first
        self._rules: list[Rule] = sorted(rules, key=lambda r: int(r.get("priority", 0)))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, entity_id: str, stats: Stats) -> list[Action]:
        """Evaluate all rules against an entity's current stats.

        Rules are processed in priority order.  A rule fires when:
          - Its target_entity is '*' OR equals entity_id, AND
          - Its conditions evaluate to True.

        Args:
            entity_id: The ID of the entity whose stats are being tested.
            stats:     The entity's current stat snapshot (stat_key -> value).

        Returns:
            List of action dicts from all triggered rules, in priority order.
            May be empty if no rules fire.
        """
        triggered_actions: list[Action] = []

        for rule in self._rules:
            target = rule.get("target_entity", "*")
            if target != "*" and target != entity_id:
                continue

            conditions = rule.get("conditions", {})
            if self._evaluate_conditions(conditions, stats):
                triggered_actions.extend(rule.get("actions", []))

        return triggered_actions

    def apply_actions(self, actions: list[Action], stats: Stats) -> Stats:
        """Apply a list of actions to a stats snapshot and return the updated copy.

        This is a pure function.  The original stats dict is not mutated.

        Supported action types:
            stat_change — adds 'delta' (float) to an existing or zero-valued stat.
            stat_set    — unconditionally sets a stat to the string form of 'value'.
            set_status  — alias for stat_set; sets 'stat' to string 'value'.
            trigger_event — no immediate stat mutation; included in output for the
                            caller to dispatch as a new Event_Log entry.

        Args:
            actions: List of action dicts (typically from evaluate()).
            stats:   The current stat snapshot to transform.

        Returns:
            New Stats dict with all applicable mutations applied.
        """
        result: Stats = dict(stats)

        for action in actions:
            action_type: str = action.get("type", "")

            if action_type == "stat_change":
                stat_key: str = action["stat"]
                delta: float = float(action["delta"])
                current_raw = result.get(stat_key, "0")
                try:
                    current = float(current_raw)
                except ValueError:
                    current = 0.0
                new_val = current + delta
                if new_val == int(new_val):
                    result[stat_key] = str(int(new_val))
                else:
                    result[stat_key] = str(new_val)

            elif action_type in ("stat_set", "set_status"):
                stat_key = action["stat"]
                result[stat_key] = str(action["value"])

            # trigger_event: caller responsibility — no stat mutation here

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_conditions(
        self,
        conditions: dict[str, Any],
        stats: Stats,
    ) -> bool:
        """Recursively evaluate a conditions block against stats.

        The conditions dict may be:
          - A group: {"operator": "AND"|"OR", "clauses": [...]}
          - A leaf clause: {"stat": str, "comparator": str, "value": ...}

        Args:
            conditions: The conditions dict or clause dict to evaluate.
            stats:      The entity's current stat snapshot.

        Returns:
            True if the conditions are satisfied, False otherwise.

        Raises:
            ValueError: If the operator is not 'AND' or 'OR'.
            KeyError: If a required key is missing from a clause.
        """
        # Detect whether this is a group or a leaf clause
        if "operator" in conditions:
            operator: str = conditions["operator"].upper()
            clauses: list[dict[str, Any]] = conditions["clauses"]

            if operator == "AND":
                return all(self._evaluate_conditions(clause, stats) for clause in clauses)
            elif operator == "OR":
                return any(self._evaluate_conditions(clause, stats) for clause in clauses)
            else:
                raise ValueError(f"Unknown logical operator: '{operator}'. Expected 'AND' or 'OR'.")

        # Leaf clause
        stat_key = conditions["stat"]
        comparator: str = conditions["comparator"]
        threshold: Union[str, int, float] = conditions["value"]
        current_raw: str = stats.get(stat_key, "0")

        return self._compare(current_raw, comparator, threshold)

    @staticmethod
    def _compare(
        stat_value: str,
        comparator: str,
        threshold: Union[str, int, float],
    ) -> bool:
        """Type-safe comparison between a stat value and a threshold.

        When both sides are numeric (i.e. the stat_value can be parsed as a
        float and the threshold is an int or float), numeric comparison is used.
        Otherwise, string equality/inequality is used.

        Args:
            stat_value:  The entity's raw string stat value.
            comparator:  One of: '<=', '>=', '==', '!=', '<', '>'.
            threshold:   The value from the rule clause (string or number).

        Returns:
            True if the comparison holds, False otherwise.

        Raises:
            ValueError: If comparator is not one of the six supported operators.
        """
        # Attempt numeric comparison
        try:
            numeric_stat = float(stat_value)
            numeric_threshold = float(threshold)  # type: ignore[arg-type]
            use_numeric = True
        except (ValueError, TypeError):
            use_numeric = False

        if use_numeric:
            a: float = numeric_stat
            b: float = numeric_threshold
            if comparator == "<=":
                return a <= b
            elif comparator == ">=":
                return a >= b
            elif comparator == "==":
                return a == b
            elif comparator == "!=":
                return a != b
            elif comparator == "<":
                return a < b
            elif comparator == ">":
                return a > b
            else:
                raise ValueError(f"Unknown comparator: '{comparator}'")

        # String comparison (only == and != are meaningful)
        str_stat = str(stat_value)
        str_threshold = str(threshold)
        if comparator == "==":
            return str_stat == str_threshold
        elif comparator == "!=":
            return str_stat != str_threshold
        else:
            raise ValueError(
                f"Comparator '{comparator}' is not supported for non-numeric stat "
                f"value '{stat_value}' vs threshold '{threshold}'. "
                "Use '==' or '!=' for string comparisons."
            )
