"""
ui/setup_view.py

Setup screen for AIRPG.
Replaces the old SessionLobbyDialog with a full-screen 3-tab experience:
1. Saves (Resume existing)
2. Persona (Global character templates)
3. Setup (Dynamic world-specific initialization)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from core.config import load_config, GLOBAL_DB_FILE
from core.localization import tr
from workers.db_helpers import create_new_save
from workers.db_worker import DbWorker

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class PersonaCreationDialog(QDialog):
    """Dialog to create a new global persona."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create New Persona")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Persona Name")
        form.addRow(tr("name"), self.name_edit)
        
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlaceholderText("Persona Description...")
        form.addRow(tr("description"), self.desc_edit)
        
        layout.addLayout(form)
        
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_data(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self.desc_edit.toPlainText().strip()


class SetupView(QWidget):
    """Full-screen setup screen for starting or resuming a game."""

    def __init__(self, main_window: "MainWindow", parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._db_path: str | None = None
        self._save_id: str | None = None
        self._player_persona: str = ""
        self._all_personas: list[dict] = []
        self._setup_configs: list[dict] = []
        self._setup_widgets: dict[str, QWidget] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        self._title_label = QLabel(tr("session_lobby"))
        self._title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        header.addWidget(self._title_label)
        header.addStretch()
        
        self._back_btn = QPushButton(tr("hub"))
        self._back_btn.clicked.connect(self._on_back_clicked)
        header.addWidget(self._back_btn)
        layout.addLayout(header)

        self._tabs = QTabWidget()
        
        # Tab 1: Saves
        self._saves_tab = QWidget()
        self._setup_saves_tab()
        self._tabs.addTab(self._saves_tab, tr("resume_save"))

        # Tab 2: Persona
        self._persona_tab = QWidget()
        self._setup_persona_tab()
        self._tabs.addTab(self._persona_tab, "Persona")

        # Tab 3: Story Setup
        self._setup_tab = QWidget()
        self._setup_story_setup_tab()
        self._tabs.addTab(self._setup_tab, tr("tab_setup"))

        layout.addWidget(self._tabs)

        # Bottom Launch Button
        self._launch_btn = QPushButton(tr("launch_session"))
        self._launch_btn.setFixedHeight(50)
        self._launch_btn.setStyleSheet("font-weight: bold; font-size: 16px; background-color: #2E7D32;")
        self._launch_btn.clicked.connect(self._on_launch_clicked)
        layout.addWidget(self._launch_btn)

    def _setup_saves_tab(self) -> None:
        layout = QVBoxLayout(self._saves_tab)
        self._saves_list = QListWidget()
        self._saves_list.setStyleSheet("font-size: 14px;")
        layout.addWidget(self._saves_list)
        
        self._del_save_btn = QPushButton(tr("delete_save"))
        self._del_save_btn.setStyleSheet("color: #FF4B4B;")
        self._del_save_btn.clicked.connect(self._on_delete_save_clicked)
        layout.addWidget(self._del_save_btn, 0, Qt.AlignRight)

    def _setup_persona_tab(self) -> None:
        layout = QVBoxLayout(self._persona_tab)
        
        # Persona Selection
        layout.addWidget(QLabel("<b>Select your Persona:</b>"))
        self._persona_list = QListWidget()
        self._persona_list.setStyleSheet("font-size: 14px;")
        layout.addWidget(self._persona_list)
        
        self._add_persona_btn = QPushButton("Add a Persona +")
        self._add_persona_btn.setFixedHeight(35)
        self._add_persona_btn.clicked.connect(self._on_add_persona_clicked)
        layout.addWidget(self._add_persona_btn)

        layout.addSpacing(10)
        
        # Character Metadata
        form = QFormLayout()
        self._new_player_name = QLineEdit(tr("hero"))
        form.addRow(tr("save_name"), self._new_player_name)
        
        self._difficulty_combo = QComboBox()
        self._difficulty_combo.addItem(tr("normal"), "Normal")
        self._difficulty_combo.addItem(tr("hardcore"), "Hardcore")
        self._difficulty_combo.addItem(tr("companion"), "Companion")
        form.addRow(tr("difficulty"), self._difficulty_combo)
        
        layout.addLayout(form)
        layout.addStretch()

    def _setup_story_setup_tab(self) -> None:
        layout = QVBoxLayout(self._setup_tab)
        self._setup_scroll = QScrollArea()
        self._setup_scroll.setWidgetResizable(True)
        self._setup_content = QWidget()
        self._setup_form = QFormLayout(self._setup_content)
        self._setup_scroll.setWidget(self._setup_content)
        layout.addWidget(self._setup_scroll)

    def retranslate_ui(self) -> None:
        self._title_label.setText(tr("session_lobby"))
        self._back_btn.setText(tr("hub"))
        self._tabs.setTabText(0, tr("resume_save"))
        self._tabs.setTabText(2, tr("tab_setup"))
        self._launch_btn.setText(tr("launch_session"))
        self._del_save_btn.setText(tr("delete_save"))

    def load_universe(self, db_path: str) -> None:
        self._db_path = db_path
        self._save_id = None
        self._player_persona = ""
        self._all_personas = []
        self._setup_configs = []
        
        # Clear UI
        self._saves_list.clear()
        self._persona_list.clear()
        self._new_player_name.setText(tr("hero"))
        
        # Clear dynamic setup
        while self._setup_form.count():
            child = self._setup_form.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._setup_widgets = {}

        # 1. Load Saves
        self._db_worker = DbWorker(db_path)
        self._db_worker.saves_loaded.connect(self._on_saves_loaded)
        self._db_worker.full_universe_loaded.connect(self._on_universe_loaded)
        self._db_worker.error_occurred.connect(lambda msg: QMessageBox.critical(self, tr("error"), msg))
        
        self._db_worker.load_saves_async()
        self._db_worker.load_full_universe()

        # 2. Load Global Personas
        self._global_worker = DbWorker(str(GLOBAL_DB_FILE))
        self._global_worker.personas_loaded.connect(self._on_personas_loaded)
        self._global_worker.load_global_personas()

    @Slot(list)
    def _on_saves_loaded(self, saves: list[dict]) -> None:
        self._saves_list.clear()
        for s in saves:
            label = f"{s['player_name']} ({s['difficulty']}) - {s['last_updated'][:10]}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, s)
            self._saves_list.addItem(item)
        
        # If saves exist, default to the Saves tab
        if saves:
            self._tabs.setCurrentIndex(0)
        else:
            self._tabs.setCurrentIndex(1)

    @Slot(dict)
    def _on_universe_loaded(self, data: dict) -> None:
        self._setup_configs = data.get("story_setup", [])
        self._build_dynamic_setup()
        
        # Check Companion support
        meta = data.get("meta", {})
        companion_enabled = meta.get("companion_mode_enabled") == "1"
        
        self._difficulty_combo.clear()
        self._difficulty_combo.addItem(tr("normal"), "Normal")
        self._difficulty_combo.addItem(tr("hardcore"), "Hardcore")
        if companion_enabled:
            self._difficulty_combo.addItem(tr("companion"), "Companion")

    def _build_dynamic_setup(self) -> None:
        for config in self._setup_configs:
            sid = config["setup_id"]
            q_text = config["question"]
            stype = config["type"]
            options = config.get("options", [])
            
            widget: QWidget | None = None
            if stype == "text":
                widget = QLineEdit()
                widget.setPlaceholderText("...")
            elif stype == "single_choice":
                widget = QComboBox()
                widget.addItems(options)
            elif stype == "multi_choice":
                widget = QWidget()
                vbox = QVBoxLayout(widget)
                vbox.setContentsMargins(0, 0, 0, 0)
                max_sel = config.get("max_selections", 1)
                for opt in options:
                    cb = QCheckBox(opt)
                    vbox.addWidget(cb)
                # Note: max_sel enforcement will happen on Launch
            
            if widget:
                self._setup_form.addRow(f"<b>{q_text}</b>", widget)
                self._setup_widgets[sid] = widget

    @Slot(list)
    def _on_personas_loaded(self, personas: list[dict]) -> None:
        self._all_personas = personas
        self._persona_list.clear()
        
        # Add a default option
        none_item = QListWidgetItem("-- No Persona --")
        none_item.setData(Qt.UserRole, "")
        self._persona_list.addItem(none_item)
        
        for p in personas:
            item = QListWidgetItem(p["name"])
            item.setData(Qt.UserRole, p["description"])
            item.setToolTip(p["description"][:200] + "..." if len(p["description"]) > 200 else p["description"])
            self._persona_list.addItem(item)
            
        self._persona_list.setCurrentRow(0)

    def _on_add_persona_clicked(self) -> None:
        dialog = PersonaCreationDialog(self)
        if dialog.exec() == QDialog.Accepted:
            name, desc = dialog.get_data()
            if not name:
                return
                
            new_p = {"persona_id": str(uuid.uuid4()), "name": name, "description": desc}
            self._all_personas.append(new_p)
            
            # Save to global DB
            self._global_worker.save_global_personas(self._all_personas)
            
            # Re-populate list and select the new one
            self._on_personas_loaded(self._all_personas)
            # Select the new one (it's the last one)
            self._persona_list.setCurrentRow(self._persona_list.count() - 1)

    @Slot()
    def _on_delete_save_clicked(self) -> None:
        item = self._saves_list.currentItem()
        if not item: return
        save = item.data(Qt.UserRole)
        reply = QMessageBox.warning(
            self, tr("warning"), tr("confirm_delete"),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._db_worker.delete_save(save["save_id"])
            self._db_worker.load_saves_async()

    @Slot()
    def _on_back_clicked(self) -> None:
        self._main_window.show_hub()

    @Slot()
    def _on_launch_clicked(self) -> None:
        # 1. Check if we are resuming
        item = self._saves_list.currentItem()
        if item and self._tabs.currentIndex() == 0:
            save = item.data(Qt.UserRole)
            self._main_window.show_tabletop(
                self._db_path, save["save_id"], player_persona=save.get("player_persona", "")
            )
            return

        # 2. Check if we are creating a new game
        name = self._new_player_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Setup", "Please enter a name for your character.")
            return

        # Get Selected Persona
        persona_item = self._persona_list.currentItem()
        persona = persona_item.data(Qt.UserRole) if persona_item else ""

        # Collect setup answers
        answers = {}
        for sid, widget in self._setup_widgets.items():
            config = next(c for c in self._setup_configs if c["setup_id"] == sid)
            if config["type"] == "text":
                answers[sid] = widget.text().strip()
            elif config["type"] == "single_choice":
                answers[sid] = widget.currentText()
            elif config["type"] == "multi_choice":
                selected = []
                # Iterate over checkboxes in the layout
                layout = widget.layout()
                for i in range(layout.count()):
                    cb = layout.itemAt(i).widget()
                    if isinstance(cb, QCheckBox) and cb.isChecked():
                        selected.append(cb.text())
                
                max_sel = config.get("max_selections", 1)
                if len(selected) > max_sel:
                    QMessageBox.warning(self, "Setup", f"Too many options selected for '{config['question']}' (Max: {max_sel})")
                    return
                answers[sid] = ", ".join(selected)

        diff = self._difficulty_combo.currentData()

        save_id = create_new_save(self._db_path, name, diff, player_persona=persona)        
        self._main_window.show_tabletop(
            self._db_path, save_id, player_persona=persona, setup_answers=answers
        )
