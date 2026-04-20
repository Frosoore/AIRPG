"""
ui/hub_view.py

Hub screen - the library home for AIRPG.

Displays all locally installed universes as a scrollable grid of cards
and provides Import and Create New controls.

THREADING RULE: All file I/O and archive processing is delegated to
ImportExportWorker.  No SQLite or filesystem operations on the main thread
beyond the lightweight metadata read inside UniverseCard.__init__.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.universe_card import UniverseCard
from core.config import GLOBAL_DB_FILE
from workers.db_helpers import (
    create_new_save,
    load_saves,
    provision_blank_universe,
)
from workers.db_worker import DbWorker
from workers.import_export_worker import ImportExportWorker

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class HubView(QWidget):
    """The library home screen listing all installed AIRPG universes.

    Args:
        main_window: Reference to MainWindow for navigation calls.
        parent:      Optional Qt parent widget.
    """

    _GRID_COLUMNS: int = 3
    _LIBRARY_DIR: str = str(Path.home() / "AIRPG" / "universes")

    def __init__(self, main_window: "MainWindow", parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._import_worker: ImportExportWorker | None = None
        self._export_worker: ImportExportWorker | None = None
        self._db_worker: DbWorker | None = None
        self._active_cards: dict[str, UniverseCard] = {}

        # Ensure library dir exists
        Path(self._LIBRARY_DIR).mkdir(parents=True, exist_ok=True)

        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the hub layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header toolbar
        toolbar = QHBoxLayout()
        header_label = QLabel("Your Library")
        header_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        toolbar.addWidget(header_label)
        toolbar.addStretch()

        import_st_btn = QPushButton("Import SillyTavern Card")
        import_btn = QPushButton("Import Universe")
        create_btn = QPushButton("Create New Universe")
        toolbar.addWidget(import_st_btn)
        toolbar.addWidget(import_btn)
        toolbar.addWidget(create_btn)
        layout.addLayout(toolbar)

        # Scroll area for universe cards
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._grid_container = QWidget()
        self._grid_layout_widget = QVBoxLayout(self._grid_container)
        self._grid_layout_widget.setAlignment(Qt.AlignTop)

        # Inner grid holder
        self._cards_row_widget = QWidget()
        from PySide6.QtWidgets import QGridLayout
        self._grid_layout = QGridLayout(self._cards_row_widget)
        self._grid_layout.setSpacing(16)
        self._grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self._grid_layout_widget.addWidget(self._cards_row_widget)
        self._grid_layout_widget.addStretch()
        self._scroll_area.setWidget(self._grid_container)
        layout.addWidget(self._scroll_area)

        # Connections
        import_st_btn.clicked.connect(self._on_import_st_clicked)
        import_btn.clicked.connect(self._on_import_clicked)
        create_btn.clicked.connect(self._on_create_new_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_library(self) -> None:
        """Scan the library directory and repopulate the card grid.

        Asynchronous: starts a DbWorker and handles result in _on_library_loaded.
        """
        self._db_worker = DbWorker("")
        self._db_worker.library_loaded.connect(self._on_library_loaded)
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.load_library(self._LIBRARY_DIR)

    @Slot(list)
    def _on_library_loaded(self, universes: list[dict]) -> None:
        """Update the grid with new metadata, reusing existing widgets where possible."""
        # 1. Identify which DBs are gone
        current_paths = {u["db_path"] for u in universes}
        for db_path in list(self._active_cards.keys()):
            if db_path not in current_paths:
                card = self._active_cards.pop(db_path)
                self._grid_layout.removeWidget(card)
                card.deleteLater()

        # 2. Add or re-position cards
        for idx, u in enumerate(universes):
            db_path = u["db_path"]
            if db_path in self._active_cards:
                card = self._active_cards[db_path]
            else:
                card = UniverseCard(
                    db_path,
                    u["name"],
                    u["last_updated"],
                    u["difficulty"]
                )
                card.play_requested.connect(self._on_card_play_requested)
                card.export_requested.connect(self._on_card_export_requested)
                card.edit_requested.connect(self._on_card_edit_requested)
                card.delete_requested.connect(self._on_card_delete_requested)
                self._active_cards[db_path] = card

            row, col = divmod(idx, self._GRID_COLUMNS)
            self._grid_layout.addWidget(card, row, col)

        # 3. Placeholder if empty
        if not universes:
            # Clear layout manually
            while self._grid_layout.count():
                item = self._grid_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                
            placeholder = QLabel(
                "No universes installed yet.\n"
                "Import a .airpg file or create a new universe to get started."
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: gray; font-size: 14px;")
            self._grid_layout.addWidget(placeholder, 0, 0)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_import_st_clicked(self) -> None:
        """Open a file dialog and start ImportExportWorker in import_st mode."""
        st_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import SillyTavern Card",
            str(Path.home()),
            "SillyTavern Cards (*.png *.json);;All Files (*)",
        )
        if not st_path:
            return

        self._progress_dialog = QProgressDialog(
            "Importing SillyTavern card...", "Cancel", 0, 4, self
        )
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setValue(0)
        self._progress_dialog.show()

        self._import_worker = ImportExportWorker(
            mode="import_st",
            source_path=st_path,
            dest_path=self._LIBRARY_DIR,
        )
        self._import_worker.import_complete.connect(self._on_import_complete)
        self._import_worker.progress_update.connect(self._on_import_progress)
        self._import_worker.error_occurred.connect(self._on_worker_error)
        self._import_worker.status_update.connect(self._main_window.on_status_update)
        self._import_worker.start()

    @Slot()
    def _on_import_clicked(self) -> None:
        """Open a file dialog and start ImportExportWorker in import mode."""
        airpg_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Universe",
            str(Path.home()),
            "AIRPG Universe (*.airpg);;All Files (*)",
        )
        if not airpg_path:
            return

        self._progress_dialog = QProgressDialog(
            "Importing universe...", "Cancel", 0, 4, self
        )
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setValue(0)
        self._progress_dialog.show()

        self._import_worker = ImportExportWorker(
            mode="import",
            source_path=airpg_path,
            dest_path=self._LIBRARY_DIR,
        )
        self._import_worker.import_complete.connect(self._on_import_complete)
        self._import_worker.progress_update.connect(self._on_import_progress)
        self._import_worker.error_occurred.connect(self._on_worker_error)
        self._import_worker.status_update.connect(self._main_window.on_status_update)
        self._import_worker.start()

    @Slot()
    def _on_create_new_clicked(self) -> None:
        """Prompt for a universe name and transition to Creator Studio."""
        name, ok = QInputDialog.getText(
            self,
            "New Universe",
            "Enter a name for your new universe:",
        )
        if not ok or not name.strip():
            return
        # Provision a blank DB, then open Creator Studio
        db_path = self._provision_blank_universe(name.strip())
        if db_path:
            self._main_window.show_creator_studio(db_path)

    @Slot(str)
    def _on_card_play_requested(self, db_path: str) -> None:
        """Open SessionLobbyDialog, then transition to Tabletop."""
        dialog = SessionLobbyDialog(db_path=db_path, parent=self)
        if dialog.exec() == QDialog.Accepted:
            save_id = dialog.save_id()
            player_persona = dialog.player_persona()
            if save_id:
                self._main_window.show_tabletop(
                    db_path, save_id, player_persona=player_persona
                )

    @Slot(str)
    def _on_card_edit_requested(self, db_path: str) -> None:
        """Open Creator Studio for editing the universe."""
        self._main_window.show_creator_studio(db_path)

    @Slot(str)
    def _on_card_delete_requested(self, db_path: str) -> None:
        """Confirm and delete a universe database file."""
        from pathlib import Path

        universe_name = Path(db_path).stem.replace("_", " ").title()
        reply = QMessageBox.warning(
            self,
            "Delete Universe",
            f"<b>Permanently delete '{universe_name}'?</b><br><br>"
            "This will remove the universe database and ALL save data. "
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            import os
            os.remove(db_path)
        except OSError as exc:
            QMessageBox.critical(self, "Delete Failed", f"Could not delete: {exc}")
            return
        self.refresh_library()
        self._main_window.on_status_update("Universe deleted.")

    @Slot(str)
    def _on_card_export_requested(self, db_path: str) -> None:
        """Save-dialog then start ImportExportWorker in export mode."""
        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Universe",
            str(Path.home() / "universe.airpg"),
            "AIRPG Universe (*.airpg)",
        )
        if not dest_path:
            return

        self._export_worker = ImportExportWorker(
            mode="export",
            source_path=db_path,
            dest_path=dest_path,
        )
        self._export_worker.export_complete.connect(
            lambda path: QMessageBox.information(self, "Export Complete", f"Saved to:\n{path}")
        )
        self._export_worker.error_occurred.connect(self._on_worker_error)
        self._export_worker.status_update.connect(self._main_window.on_status_update)
        self._export_worker.start()

    @Slot(str)
    def _on_import_complete(self, new_db_path: str) -> None:
        """Called when import finishes successfully."""
        if hasattr(self, "_progress_dialog"):
            self._progress_dialog.close()
        self.refresh_library()
        self._main_window.on_status_update("Universe imported successfully.")

    @Slot(int, int)
    def _on_import_progress(self, current: int, total: int) -> None:
        """Update the progress dialog."""
        if hasattr(self, "_progress_dialog"):
            self._progress_dialog.setValue(current)

    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        """Show error and close progress dialog if open."""
        if hasattr(self, "_progress_dialog"):
            self._progress_dialog.close()
        QMessageBox.critical(self, "Error", message)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _provision_blank_universe(self, name: str) -> str | None:
        """Create a blank universe .db for a new Creator Studio session.

        Args:
            name: Human-readable universe name.

        Returns:
            Path to the new .db, or None on failure.
        """
        from database.schema import create_universe_db

        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
        db_path = str(Path(self._LIBRARY_DIR) / f"{safe}.db")
        try:
            create_universe_db(db_path)
            provision_blank_universe(db_path, name)
            return db_path
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not create universe: {exc}")
            return None


# ---------------------------------------------------------------------------
# Session Manager Dialog (replaces _SaveSelectDialog from Phase 3)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Session Lobby Dialog (Phase 11.4)
# ---------------------------------------------------------------------------

class SessionLobbyDialog(QDialog):
    """Lobby to manage players and game saves for a universe.

    Tabs:
      1. Game Session: Resume or start a new save.
      2. Player Lobby: Manage 'player' type entities in this universe.

    Args:
        db_path: Path to the universe .db.
        parent:  Optional Qt parent.
    """

    def __init__(self, db_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Universe Lobby")
        self.setMinimumWidth(550)
        self.setMinimumHeight(600)
        self._db_path = db_path
        self._save_id: str | None = None
        self._player_persona: str = ""

        self._setup_ui()

        # Asynchronous Workers
        self._saves_worker = DbWorker(db_path)
        self._saves_worker.saves_loaded.connect(self._on_saves_loaded)
        self._saves_worker.load_saves_async()

        self._lobby_worker = DbWorker(db_path)
        self._lobby_worker.entities_loaded.connect(self._on_entities_loaded)
        self._lobby_worker.save_complete.connect(self._load_entities) # Reload after creation/deletion
        self._load_entities()

        # Asynchronous GLOBAL Persona Load
        self._global_worker = DbWorker(str(GLOBAL_DB_FILE))
        self._global_worker.personas_loaded.connect(self._on_personas_loaded)
        self._global_worker.load_global_personas()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_id(self) -> str | None:
        return self._save_id

    def player_persona(self) -> str:
        return self._player_persona

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        
        # Tab 1: Session Management
        session_tab = QWidget()
        self._setup_session_tab(session_tab)
        self._tabs.addTab(session_tab, "Game Session")

        # Tab 2: Player Lobby
        lobby_tab = QWidget()
        self._setup_lobby_tab(lobby_tab)
        self._tabs.addTab(lobby_tab, "Player Lobby")

        layout.addWidget(self._tabs)

        # Bottom Buttons
        btns = QHBoxLayout()
        self._play_btn = QPushButton("Launch Session")
        self._play_btn.setFixedHeight(40)
        self._play_btn.setStyleSheet("font-weight: bold; background-color: #2E7D32;")
        self._play_btn.clicked.connect(self._on_launch_clicked)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.clicked.connect(self.reject)
        
        btns.addWidget(cancel_btn)
        btns.addWidget(self._play_btn)
        layout.addLayout(btns)

    def _setup_session_tab(self, widget: QWidget) -> None:
        layout = QVBoxLayout(widget)
        
        # Existing saves
        self._existing_group = QGroupBox("Resume a Save")
        existing_layout = QVBoxLayout(self._existing_group)
        self._saves_list = QListWidget()
        existing_layout.addWidget(self._saves_list)
        
        save_btns = QHBoxLayout()
        self._delete_save_btn = QPushButton("Delete Save")
        self._delete_save_btn.setStyleSheet("color: #FF4B4B;")
        self._delete_save_btn.clicked.connect(self._on_delete_save_clicked)
        save_btns.addStretch()
        save_btns.addWidget(self._delete_save_btn)
        existing_layout.addLayout(save_btns)
        layout.addWidget(self._existing_group)

        # New game
        new_group = QGroupBox("New Game")
        new_form = QFormLayout(new_group)
        self._new_player_name = QLineEdit("Hero")
        new_form.addRow("Save Name:", self._new_player_name)
        
        self._difficulty_combo = QComboBox()
        self._difficulty_combo.addItems(["Normal", "Hardcore"])
        new_form.addRow("Difficulty:", self._difficulty_combo)

        self._persona_combo = QComboBox()
        new_form.addRow("Persona Template:", self._persona_combo)
        self._persona_edit = QPlainTextEdit()
        self._persona_edit.setFixedHeight(80)
        new_form.addRow("Custom Persona:", self._persona_edit)
        
        self._create_save_btn = QPushButton("Create New Save")
        self._create_save_btn.clicked.connect(self._on_new_game_clicked)
        
        layout.addWidget(new_group)
        layout.addWidget(self._create_save_btn)
        layout.addStretch()

        self._persona_combo.currentIndexChanged.connect(self._on_persona_template_changed)

    def _setup_lobby_tab(self, widget: QWidget) -> None:
        layout = QVBoxLayout(widget)
        
        info = QLabel(
            "Manage player characters available in this universe.\n"
            "You can add multiple players for a multiplayer session."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(info)

        self._player_list = QListWidget()
        layout.addWidget(self._player_list)

        actions = QHBoxLayout()
        self._add_player_btn = QPushButton("Create New Player Entity")
        self._delete_player_btn = QPushButton("Delete Player")
        self._delete_player_btn.setStyleSheet("color: #FF4B4B;")
        
        actions.addWidget(self._add_player_btn)
        actions.addWidget(self._delete_player_btn)
        layout.addLayout(actions)

        self._add_player_btn.clicked.connect(self._on_add_player_clicked)
        self._delete_player_btn.clicked.connect(self._on_delete_player_clicked)

    # ------------------------------------------------------------------
    # Slots & Logic
    # ------------------------------------------------------------------

    def _load_entities(self) -> None:
        self._lobby_worker.load_full_universe()

    @Slot(list)
    def _on_saves_loaded(self, saves: list[dict]) -> None:
        self._saves_list.clear()
        if not saves:
            self._existing_group.setVisible(False)
            return
        self._existing_group.setVisible(True)
        for s in saves:
            label = f"{s['player_name']} ({s['difficulty']}) - {s['last_updated'][:10]}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, s)
            self._saves_list.addItem(item)

    @Slot(list)
    def _on_entities_loaded(self, entities: list[dict]) -> None:
        self._player_list.clear()
        players = [e for e in entities if e.get("entity_type") == "player"]
        for p in players:
            item = QListWidgetItem(f"{p['name']} ({p['entity_id']})")
            item.setData(Qt.UserRole, p["entity_id"])
            self._player_list.addItem(item)

    @Slot(list)
    def _on_personas_loaded(self, personas: list[dict]) -> None:
        self._persona_combo.blockSignals(True)
        self._persona_combo.clear()
        self._persona_combo.addItem("-- Custom --", None)
        for p in personas:
            self._persona_combo.addItem(p["name"], p)
        self._persona_combo.blockSignals(False)

    def _on_persona_template_changed(self, index: int) -> None:
        p = self._persona_combo.currentData()
        if p:
            self._persona_edit.setPlainText(p.get("description", ""))

    def _on_add_player_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, "New Player", "Character Name:")
        if ok and name.strip():
            self._lobby_worker.create_player_entity(name.strip())

    def _on_delete_player_clicked(self) -> None:
        item = self._player_list.currentItem()
        if not item: return
        eid = item.data(Qt.UserRole)
        reply = QMessageBox.warning(self, "Confirm", f"Delete player entity '{eid}'?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._lobby_worker.delete_entity(eid)

    def _on_delete_save_clicked(self) -> None:
        item = self._saves_list.currentItem()
        if not item: return
        save = item.data(Qt.UserRole)
        reply = QMessageBox.warning(self, "Confirm", f"Delete save '{save['player_name']}'?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._saves_worker.delete_save(save["save_id"])

    def _on_new_game_clicked(self) -> None:
        name = self._new_player_name.text().strip()
        diff = self._difficulty_combo.currentText()
        persona = self._persona_edit.toPlainText().strip()
        self._save_id = create_new_save(self._db_path, name, diff, player_persona=persona)
        self._player_persona = persona
        self.accept()

    def _on_launch_clicked(self) -> None:
        # Check if we have an existing save selected
        item = self._saves_list.currentItem()
        if item:
            save = item.data(Qt.UserRole)
            self._save_id = save["save_id"]
            self._player_persona = save.get("player_persona", "")
            self.accept()
        else:
            QMessageBox.information(self, "Lobby", "Please select an existing save or create a 'New Game' first.")
