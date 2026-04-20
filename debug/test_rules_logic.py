"""
debug/test_rules_logic.py

Standalone debug script to verify RulesEngine logic against various stat snapshots.
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from core.rules_engine import RulesEngine

def test_rules():
    # Example rules
    rules = [
        {
            "rule_id": "low_hp_death",
            "priority": 0,
            "target_entity": "*",
            "conditions": {
                "operator": "AND",
                "clauses": [
                    {"stat": "HP", "comparator": "<=", "value": 0}
                ]
            },
            "actions": [
                {"type": "stat_set", "stat": "Status", "value": "Dead"}
            ]
        },
        {
            "rule_id": "high_level_buff",
            "priority": 5,
            "target_entity": "player",
            "conditions": {
                "stat": "Level", "comparator": ">=", "value": 10
            },
            "actions": [
                {"type": "stat_change", "stat": "Power", "delta": 10}
            ]
        }
    ]

    engine = RulesEngine(rules)

    print("--- Testing Rules Logic ---")

    # Test Case 1: Death Rule
    stats1 = {"HP": "-5", "Status": "Alive"}
    actions1 = engine.evaluate("enemy_goblin", stats1)
    print(f"Test 1 (Enemy Death): Expected 'Dead' action, Got: {actions1}")
    result1 = engine.apply_actions(actions1, stats1)
    print(f"Result 1: {result1}")

    # Test Case 2: Player Level Buff
    stats2 = {"Level": "12", "Power": "50"}
    actions2 = engine.evaluate("player", stats2)
    print(f"Test 2 (Player Buff): Expected Power +10, Got: {actions2}")
    result2 = engine.apply_actions(actions2, stats2)
    print(f"Result 2: {result2}")

    # Test Case 3: No matching rules
    stats3 = {"HP": "100", "Level": "1"}
    actions3 = engine.evaluate("player", stats3)
    print(f"Test 3 (No triggers): Expected empty list, Got: {actions3}")

    print("--- Done ---")

if __name__ == "__main__":
    test_rules()
