"""
ui/ambiance_manager.py

Handles cross-fading and dynamic background audio for AIRPG.
Uses two QMediaPlayer instances to seamlessly transition between ambiance tags.
"""

import random
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class AmbianceManager(QObject):
    """Manages background music with smooth cross-fading.

    Attributes:
        FADE_DURATION_MS: Total time for the cross-fade transition.
        FADE_STEP_MS: Interval between volume adjustment steps.
    """

    FADE_DURATION_MS = 3000
    FADE_STEP_MS = 50

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._global_volume = 0.5
        self._current_tag: str | None = None
        self._enabled = True

        # Player A
        self._out_a = QAudioOutput()
        self._player_a = QMediaPlayer()
        self._player_a.setAudioOutput(self._out_a)
        self._player_a.setLoops(QMediaPlayer.Infinite)

        # Player B
        self._out_b = QAudioOutput()
        self._player_b = QMediaPlayer()
        self._player_b.setAudioOutput(self._out_b)
        self._player_b.setLoops(QMediaPlayer.Infinite)

        # State tracking
        self._active_player = self._player_a
        self._active_out = self._out_a
        self._fading_player = self._player_b
        self._fading_out = self._out_b

        # Fader Timer
        self._fade_timer = QTimer()
        self._fade_timer.setInterval(self.FADE_STEP_MS)
        self._fade_timer.timeout.connect(self._on_fade_step)
        self._fade_progress = 0.0  # 0.0 to 1.0

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable audio playback."""
        self._enabled = enabled
        if not enabled:
            self.stop_all()

    def set_global_volume(self, volume: float) -> None:
        """Set the target peak volume (0.0 to 1.0)."""
        self._global_volume = max(0.0, min(1.0, volume))
        # Update current active player volume immediately if not fading
        if not self._fade_timer.isActive():
            self._active_out.setVolume(self._global_volume)

    def update_ambiance(self, tag: str) -> None:
        """Trigger a cross-fade to a new ambiance tag."""
        if not self._enabled or tag == self._current_tag:
            return

        print(f"[AMBIANCE] Requesting transition to '{tag}'")
        self._current_tag = tag
        audio_file = self._pick_random_file(tag)

        if not audio_file:
            print(f"[AMBIANCE] No audio assets found for '{tag}'. Stopping all.")
            self.stop_all()
            return

        print(f"[AMBIANCE] Selected track: {audio_file.name}")
        # Prepare the fading player (the one currently silent or fading out)
        # Swap roles
        self._fading_player, self._active_player = self._active_player, self._fading_player
        self._fading_out, self._active_out = self._active_out, self._fading_out

        # Start new track at volume 0
        self._active_out.setVolume(0.0)
        self._active_player.setSource(QUrl.fromLocalFile(str(audio_file.absolute())))
        self._active_player.play()

        # Start fading
        self._fade_progress = 0.0
        self._fade_timer.start()

    def stop_all(self) -> None:
        """Immediately stop all audio."""
        self._fade_timer.stop()
        self._player_a.stop()
        self._player_b.stop()
        self._current_tag = None

    def _pick_random_file(self, tag: str) -> Path | None:
        """Find a random audio file in assets/audio/<tag>/."""
        audio_dir = Path(__file__).parent.parent / "assets" / "audio" / tag
        if not audio_dir.exists() or not audio_dir.is_dir():
            return None

        files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.ogg")) + list(audio_dir.glob("*.wav"))
        return random.choice(files) if files else None

    @Slot()
    def _on_fade_step(self) -> None:
        """Adjust volumes for cross-fade."""
        self._fade_progress += self.FADE_STEP_MS / self.FADE_DURATION_MS
        
        if self._fade_progress >= 1.0:
            self._fade_progress = 1.0
            self._fade_timer.stop()
            self._fading_player.stop()
            
        # Linear cross-fade
        self._active_out.setVolume(self._fade_progress * self._global_volume)
        self._fading_out.setVolume((1.0 - self._fade_progress) * self._global_volume)
