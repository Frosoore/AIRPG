"""
debug/test_audio_crossfade.py

Standalone debug script to verify AmbianceManager cross-fade logic without 
launching the full AIRPG UI.

Usage:
    python3 debug/test_audio_crossfade.py <tag1> <tag2>
"""

import sys
import os
import time
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from ui.ambiance_manager import AmbianceManager

def test_audio():
    app = QApplication(sys.argv)
    
    manager = AmbianceManager()
    manager.set_global_volume(0.8)
    
    if len(sys.argv) < 3:
        print("Usage: python3 debug/test_audio_crossfade.py <tag1> <tag2>")
        return

    tag1 = sys.argv[1]
    tag2 = sys.argv[2]

    print(f"--- Starting Audio Test ---")
    print(f"Transitioning to: {tag1}")
    manager.update_ambiance(tag1)
    
    # We need to process events for the timer to work
    start_time = time.time()
    while time.time() - start_time < 5:
        app.processEvents()
        time.sleep(0.1)
        
    print(f"Transitioning to: {tag2} (Cross-fade should start)")
    manager.update_ambiance(tag2)
    
    start_time = time.time()
    while time.time() - start_time < 10:
        app.processEvents()
        # Print volumes for debugging
        vol_a = manager._out_a.volume()
        vol_b = manager._out_b.volume()
        active = "A" if manager._active_player == manager._player_a else "B"
        print(f"Vol A: {vol_a:.2f} | Vol B: {vol_b:.2f} | Active: {active}", end="\r")
        time.sleep(0.1)

    print("\n--- Test Complete ---")
    manager.stop_all()

if __name__ == "__main__":
    test_audio()
