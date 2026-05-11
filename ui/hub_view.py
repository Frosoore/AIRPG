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
from core.localization import tr
from workers.db_helpers import (
    create_new_save,
    load_saves,
    provision_blank_universe,
)
from workers.db_worker import DbWorker
from workers.import_export_worker import ImportExportWorker
from core.paths import UNIVERSES_DIR

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class HubView(QWidget):
    """The library home screen listing all installed AIRPG universes.

    Args:
        main_window: Reference to MainWindow for navigation calls.
        parent:      Optional Qt parent widget.
    """

    _GRID_COLUMNS: int = 3
    _LIBRARY_DIR: str = str(UNIVERSES_DIR)

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
        self._header_label = QLabel(tr("hub_title"))
        self._header_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        toolbar.addWidget(self._header_label)
        toolbar.addStretch()

        self._import_st_btn = QPushButton(tr("import_st"))
        self._import_st_btn.setToolTip("Import a character card from SillyTavern format.")
        self._import_btn = QPushButton(tr("import"))
        self._import_btn.setToolTip("Import an existing .airpg universe file.")
        self._create_btn = QPushButton(tr("new_universe"))
        self._create_btn.setToolTip("Create a brand new empty universe.")
        toolbar.addWidget(self._import_st_btn)
        toolbar.addWidget(self._import_btn)
        toolbar.addWidget(self._create_btn)
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
        self._import_st_btn.clicked.connect(self._on_import_st_clicked)
        self._import_btn.clicked.connect(self._on_import_clicked)
        self._create_btn.clicked.connect(self._on_create_new_clicked)

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

    def retranslate_ui(self) -> None:
        """Refresh all UI text for the current language."""
        self._header_label.setText(tr("hub_title"))
        self._import_st_btn.setText(tr("import_st"))
        self._import_btn.setText(tr("import"))
        self._create_btn.setText(tr("new_universe"))
        
        # Refresh cards to update their internal buttons (Play, Edit, etc)
        self.refresh_library()

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
                # Retranslate the card labels
                if hasattr(card, "retranslate_ui"): card.retranslate_ui()
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
                
            placeholder = QLabel(tr("no_universes_placeholder"))
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
            tr("import_st"),
            str(Path.home()),
            "SillyTavern Cards (*.png *.json);;All Files (*)",
        )
        if not st_path:
            return

        self._progress_dialog = QProgressDialog(
            tr("importing_st") if "importing_st" in tr("ready") else "Importing SillyTavern card...", 
            tr("cancel"), 0, 4, self
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
            tr("import"),
            str(Path.home()),
            "AIRPG Universe (*.airpg);;All Files (*)",
        )
        if not airpg_path:
            return

        self._progress_dialog = QProgressDialog(
            tr("importing_universe") if "importing_universe" in tr("ready") else "Importing universe...", 
            tr("cancel"), 0, 4, self
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
            tr("new_universe"),
            tr("universe_name"),
        )
        if not ok or not name.strip():
            return
        # Provision a blank DB, then open Creator Studio
        db_path = self._provision_blank_universe(name.strip())
        if db_path:
            self._main_window.show_creator_studio(db_path)

    @Slot(str)
    def _on_card_play_requested(self, db_path: str) -> None:
        """Switch to the Setup screen for this universe."""
        self._main_window.show_setup(db_path)

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
            tr("delete_universe"),
            tr("confirm_delete_universe", name=universe_name),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            import os
            os.remove(db_path)
            self.refresh_library()
            self._main_window.on_status_update(tr("ready"))
        except OSError as exc:
            QMessageBox.critical(self, tr("error"), f"{exc}")

    @Slot(str)
    def _on_card_export_requested(self, db_path: str) -> None:
        """Save-dialog then start ImportExportWorker in export mode."""
        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("export"),
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
            lambda path: QMessageBox.information(self, tr("export_complete"), tr("save_to") + ":\n" + path)
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
        self._main_window.on_status_update(tr("ready"))

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
        QMessageBox.critical(self, tr("error"), message)

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
            QMessageBox.critical(self, tr("error"), f"{exc}")
            return None
