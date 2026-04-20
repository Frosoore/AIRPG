"""
tests/test_ambiance_manager.py

Unit tests for the AmbianceManager.
"""

import pytest
from PySide6.QtMultimedia import QMediaPlayer
from ui.ambiance_manager import AmbianceManager

@pytest.fixture
def ambiance_manager(qtbot):
    """Fixture to create an AmbianceManager with a qtbot."""
    manager = AmbianceManager()
    qtbot.addWidget(manager)
    return manager

def test_initial_state(ambiance_manager):
    """Verify default initial state."""
    assert ambiance_manager._enabled is True
    assert ambiance_manager._global_volume == 0.5
    assert ambiance_manager._current_tag is None
    assert ambiance_manager._fade_timer.isActive() is False

def test_set_global_volume(ambiance_manager):
    """Verify volume bounds and immediate update."""
    ambiance_manager.set_global_volume(0.8)
    assert ambiance_manager._global_volume == 0.8
    assert ambiance_manager._active_out.volume() == 0.8
    
    ambiance_manager.set_global_volume(1.5)
    assert ambiance_manager._global_volume == 1.0
    
    ambiance_manager.set_global_volume(-0.5)
    assert ambiance_manager._global_volume == 0.0

def test_stop_all(ambiance_manager):
    """Verify stopping all audio clears state."""
    ambiance_manager._current_tag = "test"
    ambiance_manager.stop_all()
    assert ambiance_manager._current_tag is None
    assert ambiance_manager._player_a.playbackState() == QMediaPlayer.StoppedState
    assert ambiance_manager._player_b.playbackState() == QMediaPlayer.StoppedState
    assert ambiance_manager._fade_timer.isActive() is False

def test_enabled_toggle(ambiance_manager):
    """Verify that disabling audio stops playback."""
    ambiance_manager._current_tag = "test"
    ambiance_manager.set_enabled(False)
    assert ambiance_manager._enabled is False
    assert ambiance_manager._current_tag is None

def test_fade_step_logic(ambiance_manager):
    """Manually trigger fade steps and check volume calculation."""
    ambiance_manager.set_global_volume(1.0)
    ambiance_manager._fade_progress = 0.5
    ambiance_manager._on_fade_step()
    
    # 0.5 + 50/3000 = 0.5166...
    assert ambiance_manager._fade_progress > 0.5
    assert ambiance_manager._active_out.volume() == ambiance_manager._fade_progress
    assert ambiance_manager._fading_out.volume() == pytest.approx(1.0 - ambiance_manager._fade_progress)
