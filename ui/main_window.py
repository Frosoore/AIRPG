"""
ui/main_window.py

Root application window for AIRPG.

Owns a QStackedWidget that hosts the three screens (Hub, Creator Studio,
Tabletop) and coordinates navigation between them.  Holds the active
session state so it can be passed to workers.

THREADING RULE: This file contains ZERO backend calls.  All I/O is
delegated exclusively to workers in the workers/ directory.
"""

from __future__ import annotations

from PySide6.QtCore import Slot, Qt, QUrl
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QSlider,
    QLabel,
    QHBoxLayout,
    QWidget,
)

from core.config import load_config
from core.localization import tr


class MainWindow(QMainWindow):
    """Root application window for AIRPG.

    Manages screen navigation via a QStackedWidget and owns the active
    session state (db_path, save_id, turn_id) that persists across navigation.

    The three screens (indices):
        0 - HubView          (library grid, import/export)
        1 - CreatorStudioView (entity + rule builder)
        2 - TabletopView      (gameplay: chat, sidebar, mini-dico)
    """

    # Import views lazily inside methods to avoid circular imports at module load
    _HUB_INDEX: int = 0
    _CREATOR_INDEX: int = 1
    _TABLETOP_INDEX: int = 2
    _LOADING_INDEX: int = 3

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("app_title"))
        self.resize(1400, 850) # Increased default width for better box display

        # Session state - populated when transitioning to Tabletop
        self._active_db_path: str | None = None
        self._active_save_id: str | None = None
        self._active_turn_id: int = 0
        self._last_chronicle_turn: int = 0

        # Audio Ambiance System (Phase 12 Overhaul)
        from ui.ambiance_manager import AmbianceManager
        self._ambiance_manager = AmbianceManager(self)
        self._current_ambiance_tag: str | None = None

        self._setup_stack()
        self._setup_menu()
        self._setup_status_bar()
        self._setup_volume_slider()
        self._check_first_launch()
        self.show_hub()  # Populate library grid on launch

    def _setup_volume_slider(self) -> None:
        """Add a volume slider to the status bar."""
        from PySide6.QtWidgets import QSizePolicy
        
        # Cleanup existing if any
        if hasattr(self, "_volume_container"):
            self._status_bar.removeWidget(self._volume_container)
            self._volume_container.deleteLater()

        self._volume_container = QWidget()
        self._volume_container.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self._volume_container)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(5)
        
        # Align content to the far right to keep it compact
        layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        self._vol_label = QLabel(tr("vol_fmt", val="50%").split("50%")[0].rstrip())
        self._vol_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed) # Compact label
        layout.addWidget(self._vol_label)
        
        self._volume_slider = QSlider(Qt.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(50)
        self._volume_slider.setFixedWidth(80) # Keep slider compact
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        layout.addWidget(self._volume_slider)
        
        self._status_bar.addPermanentWidget(self._volume_container)

    def retranslate_ui(self) -> None:
        """Dynamic text update for MainWindow elements."""
        self.setWindowTitle(tr("app_title"))
        self._setup_menu()
        if hasattr(self, "_vol_label"):
            self._vol_label.setText(tr("vol_fmt", val="50%").split("50%")[0].rstrip())
        self._status_bar.showMessage(tr("ready"))
        
        # New: Retranslate all views
        if hasattr(self, "_hub_view"): self._hub_view.retranslate_ui()
        if hasattr(self, "_creator_view"): self._creator_view.retranslate_ui()
        if hasattr(self, "_tabletop_view"): self._tabletop_view.retranslate_ui()

    def _on_volume_changed(self, value: int) -> None:
        """Update audio output volume (0.0 to 1.0)."""
        self._ambiance_manager.set_global_volume(value / 100.0)

    def update_audio_ambiance(self, tag: str) -> None:
        """Change background loop with cross-fading via AmbianceManager."""
        from core.config import load_config
        cfg = load_config()
        self._ambiance_manager.set_enabled(cfg.enable_audio)
        
        if not cfg.enable_audio:
            self._current_ambiance_tag = None
            return

        if tag == self._current_ambiance_tag:
            return

        self._current_ambiance_tag = tag
        self._ambiance_manager.update_ambiance(tag)
        self.on_status_update(f"{tr('ambiance')} {tag} ({tr('fading')})")

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _setup_stack(self) -> None:
        """Instantiate the views and add them to the QStackedWidget."""
        # Import here to avoid module-level circular imports
        from ui.hub_view import HubView
        from ui.creator_studio_view import CreatorStudioView
        from ui.tabletop_view import TabletopView
        from ui.loading_view import LoadingView

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._hub_view = HubView(main_window=self)
        self._creator_view = CreatorStudioView(main_window=self)
        self._tabletop_view = TabletopView(main_window=self)
        self._loading_view = LoadingView(self)

        self._stack.addWidget(self._hub_view)       # index 0
        self._stack.addWidget(self._creator_view)   # index 1
        self._stack.addWidget(self._tabletop_view)  # index 2
        self._stack.addWidget(self._loading_view)   # index 3

        # Connect Tabletop loading signals
        self._tabletop_view.session_loaded.connect(self._on_session_ready)
        self._tabletop_view.loading_status.connect(self._loading_view.set_message)
        self._tabletop_view.loading_failed.connect(self.show_hub)

    def _setup_menu(self) -> None:
        """Build the menu bar. Clears existing menus first to prevent duplication."""
        menu_bar = self.menuBar()
        menu_bar.clear()

        # File menu
        file_menu = menu_bar.addMenu(tr("menu_file"))
        settings_action = QAction(tr("menu_settings"), self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.setToolTip("Open the global configuration dialog.")
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction(tr("menu_quit"), self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.setToolTip("Close the application.")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Help menu
        help_menu = menu_bar.addMenu(tr("menu_help"))
        about_action = QAction(tr("menu_about"), self)
        about_action.setToolTip("Show information about AIRPG.")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_status_bar(self) -> None:
        """Create and configure the status bar."""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(tr("ready"))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def show_hub(self) -> None:
        """Switch to the Hub screen and refresh the library grid.

        Safe to call from any screen at any time.
        """
        self._stack.setCurrentIndex(self._HUB_INDEX)
        self._hub_view.refresh_library()

    def show_creator_studio(self, db_path: str) -> None:
        """Switch to the Creator Studio screen.

        Args:
            db_path: Path to the universe .db file, or empty string for a
                     new universe that has not yet been provisioned.
        """
        self._stack.setCurrentIndex(self._CREATOR_INDEX)
        self._creator_view.load_universe(db_path)

    def show_tabletop(
        self,
        db_path: str,
        save_id: str,
        player_persona: str = "",
    ) -> None:
        """Switch to the Loading screen then initialise the session.

        Args:
            db_path:        Path to the universe .db file.
            save_id:        The save to load.
            player_persona: Optional player background string passed to the
                            narrative prompt.
        """
        self._active_db_path = db_path
        self._active_save_id = save_id
        self._active_turn_id = 0
        self._last_chronicle_turn = 0

        # Switch to loading screen immediately
        self._stack.setCurrentIndex(self._LOADING_INDEX)
        self._loading_view.set_message(tr("loading_universe"))
        
        # Defer the heavy lifting to the next event loop iteration to ensure
        # the LoadingView has a chance to paint itself.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._tabletop_view.load_session(
            db_path, save_id, player_persona=player_persona
        ))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_session_ready(self) -> None:
        """Switch from LoadingView to TabletopView once data is ready."""
        self._stack.setCurrentIndex(self._TABLETOP_INDEX)

    @Slot(str)
    def on_status_update(self, message: str) -> None:
        """Write a status message to the QStatusBar.

        Connected to the status_update signal of every worker.

        Args:
            message: Short human-readable status string.
        """
        self._status_bar.showMessage(message)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _show_settings(self) -> None:
        """Open the Settings dialog and reload the LLM if settings were saved."""
        from ui.settings_dialog import SettingsDialog
        from core.config import load_config
        from PySide6.QtWidgets import QDialog
        
        db_path = self._active_db_path
        if self._stack.currentIndex() == self._CREATOR_INDEX:
            db_path = self._creator_view._db_path
            
        dialog = SettingsDialog(config=load_config(), db_path=db_path, parent=self)
        if dialog.exec() == QDialog.Accepted:
            # Update all UI text dynamically
            self.retranslate_ui()
            
            self._tabletop_view.reload_llm()
            self._tabletop_view.reload_ui_settings()
            
            # Re-evaluate audio state
            cfg = load_config()
            if not cfg.enable_audio:
                self._ambiance_manager.set_enabled(False)
            elif self._current_ambiance_tag:
                self._ambiance_manager.set_enabled(True)

            # Refresh volume label in status bar
            self._status_bar.removeWidget(self._status_bar.findChild(QWidget)) # Hacky, but works if we rebuild
            # Actually better to just store the label. Let me fix main_window to store vol_label.
            self._setup_volume_slider() # Rebuild volume slider with new language

            # Refresh current view
            if self._stack.currentIndex() == self._HUB_INDEX:
                self._hub_view.retranslate_ui()
            elif self._stack.currentIndex() == self._CREATOR_INDEX:
                self._creator_view.retranslate_ui()
            elif self._stack.currentIndex() == self._TABLETOP_INDEX:
                self._tabletop_view.retranslate_ui()

    def _show_about(self) -> None:
        """Display the About dialog."""
        QMessageBox.about(
            self,
            tr("menu_about").replace("&", ""),
            tr("about_text"),
        )

    def _check_first_launch(self) -> None:
        """Show a welcome message if this is the first time the app is launched."""
        from core.paths import SETTINGS_FILE
        if not SETTINGS_FILE.exists():
            QMessageBox.information(
                self,
                tr("welcome_title"),
                tr("welcome_text"),
            )
