
import unittest
import sys
import os
from pathlib import Path
from dataclasses import dataclass

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from core.arbitrator import Arbitrator, ArbitratorResult
from llm_engine.base import LLMResponse

class TestAudioLogic(unittest.TestCase):
    def test_arbitrator_result_tag_parsing(self):
        # Verify that ArbitratorResult stores the tag
        res = ArbitratorResult(
            narrative_text="Prose",
            game_state_tag="combat"
        )
        self.assertEqual(res.game_state_tag, "combat")

    def test_audio_folder_structure(self):
        # Verify folders were created
        tags = ['exploration', 'combat', 'tavern', 'dungeon']
        for tag in tags:
            path = Path("assets") / "audio" / tag
            self.assertTrue(path.exists(), f"Folder for {tag} should exist")
            self.assertTrue(path.is_dir(), f"{tag} should be a directory")

    def test_file_selection_logic_simulation(self):
        # Simulate the logic in _update_audio_ambiance
        tag = "exploration"
        audio_dir = Path("assets") / "audio" / tag
        
        # Create a dummy file for testing
        dummy_file = audio_dir / "test.mp3"
        dummy_file.touch()
        
        try:
            files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.ogg"))
            self.assertIn(dummy_file, files)
            
            import random
            selected = random.choice(files)
            self.assertEqual(selected, dummy_file)
        finally:
            dummy_file.unlink()

if __name__ == "__main__":
    unittest.main()
