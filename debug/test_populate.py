"""
debug/test_populate.py

Debug script to verify Populate logic (prompt building + filtering)
without launching the full UI.
"""

import sys
import json
import re
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_engine.prompt_builder import build_populate_prompt
from llm_engine.base import LLMBackend, LLMResponse

class DummyLLM(LLMBackend):
    def complete(self, messages, stream=False, response_format=None):
        # Simulate a successful JSON response matching the new flat schema
        tool_call = {
            "entities": [
                {
                    "name": "Aria the Swift",
                    "entity_type": "npc",
                    "description": "A fast scout from the northern borders."
                },
                {
                    "name": "Guard", # Duplicate name, should be filtered
                    "entity_type": "npc",
                    "description": "A generic guard."
                }
            ]
        }
        return LLMResponse(
            narrative_text="~~~json\n" + json.dumps(tool_call) + "\n~~~",
            tool_call=tool_call,
            finish_reason="stop"
        )
    def stream_tokens(self, messages): yield ""
    def is_available(self): return True

def test_logic():
    print("🧪 Testing Populate Logic...")
    
    lore_chunk = "A scout named Aria is watching the gates. A generic Guard stands nearby."
    existing_names = ["Guard"]
    existing_ids = {"guard"}
    
    # 1. Test Prompt Builder
    print("  [ ] Building prompt...")
    msgs = build_populate_prompt(lore_chunk, existing_names)
    assert len(msgs) == 2
    assert "Aria" in msgs[1]["content"]
    assert "description" in msgs[1]["content"]
    print("  [✓] Prompt built OK")
    
    # 2. Test Filtering and ID Generation (Mirroring workers/db_tasks.py)
    print("  [ ] Testing filtering and ID generation...")
    llm = DummyLLM()
    resp = llm.complete(msgs)
    new_ents = resp.tool_call["entities"]
    
    filtered = []
    for ent in new_ents:
        name = ent.get("name", "").strip()
        if not name: continue
        
        # Python-side ID generation
        eid = re.sub(r'[^a-z0-9]', '_', name.lower())
        eid = re.sub(r'_+', '_', eid).strip('_')
        
        if eid in existing_ids:
            print(f"      (Skipping {name} as {eid} already exists)")
            continue
            
        filtered.append((eid, name, ent.get("description")))
        
    assert len(filtered) == 1
    assert filtered[0][0] == "aria_the_swift"
    assert filtered[0][1] == "Aria the Swift"
    print("  [✓] Filtering and ID logic OK")
    
    print("\n✨ Populate logic verification passed.")

if __name__ == "__main__":
    test_logic()
