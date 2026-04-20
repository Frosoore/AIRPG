
import unittest
import sys
from pathlib import Path
from typing import Iterator

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from llm_engine.base import LLMBackend, LLMMessage, LLMResponse

class MockLLM(LLMBackend):
    def complete(self, messages, stream=False, temperature=0.7, top_p=1.0, response_format=None, stop_sequences=None, max_tokens=None) -> LLMResponse:
        tool_call = {"game_state_tag": "combat", "state_changes": []}
        return LLMResponse(
            narrative_text=f"Response with temp={temperature} top_p={top_p}",
            tool_call=tool_call,
            finish_reason="stop"
        )
    
    def stream_tokens(self, messages, temperature=0.7, top_p=1.0, response_format=None, stop_sequences=None, max_tokens=None) -> Iterator[str]:
        yield f"Stream with temp={temperature} top_p={top_p}"
    
    def is_available(self) -> bool:
        return True

class TestLLMLogic(unittest.TestCase):
    def test_parameter_propagation(self):
        llm = MockLLM()
        messages = [{"role": "user", "content": "hi"}]
        
        # Test complete()
        resp = llm.complete(messages, temperature=0.1, top_p=0.2)
        self.assertEqual(resp.narrative_text, "Response with temp=0.1 top_p=0.2")
        self.assertEqual(resp.tool_call["game_state_tag"], "combat")
        
        # Test stream_tokens()
        tokens = list(llm.stream_tokens(messages, temperature=0.3, top_p=0.4))
        self.assertEqual(tokens[0], "Stream with temp=0.3 top_p=0.4")
        
    def test_defaults(self):
        llm = MockLLM()
        messages = [{"role": "user", "content": "hi"}]
        
        # Test default values in complete()
        resp = llm.complete(messages)
        self.assertEqual(resp.narrative_text, "Response with temp=0.7 top_p=1.0")

if __name__ == "__main__":
    unittest.main()
