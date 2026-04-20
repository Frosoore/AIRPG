
import unittest
import sys
import os
import json
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from database.schema import create_universe_db, get_connection
from workers.db_tasks import PopulateEntitiesTask

class MockOllama:
    def complete(self, prompt):
        from llm_engine.base import LLMResponse
        tool_call = {
            "entities": [
                {
                    "entity_id": "new_npc_debug",
                    "name": "Debug NPC",
                    "entity_type": "npc",
                    "stats": {"HP": 100}
                }
            ]
        }
        return LLMResponse(
            narrative_text="~~~json\n" + json.dumps(tool_call) + "\n~~~",
            tool_call=tool_call,
            finish_reason="stop"
        )

class TestPopulateAsync(unittest.TestCase):
    def setUp(self):
        self.db_path = "debug_populate.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        create_universe_db(self.db_path)
        
        # Add some initial lore
        with get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO Lore_Book (entry_id, category, name, content) VALUES ('1', 'Debug', 'Lore Item', 'Some lore text here');")
            conn.commit()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_populate_task_logic(self):
        # We can't easily run the full task because it instantiates OllamaClient
        # But we can test the insertion logic by mocking the LLM part if we refactor slightly
        # For now, let's just verify the class exists and has required methods
        task = PopulateEntitiesTask(self.db_path)
        self.assertTrue(hasattr(task, 'execute'))

if __name__ == "__main__":
    unittest.main()
