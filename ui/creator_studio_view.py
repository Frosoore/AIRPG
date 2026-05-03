"""
ui/creator_studio_view.py

Creator Studio screen for AIRPG.
Provides a spreadsheet-like interface for building universe content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.entity_editor import EntityEditorWidget
from ui.widgets.lore_book_editor import LoreBookEditorWidget
from ui.widgets.rule_editor import RuleEditorWidget
from ui.widgets.stat_definition_editor import StatDefinitionEditorWidget
from ui.widgets.scheduled_events_editor import ScheduledEventsEditorWidget
from ui.widgets.populate_tab import PopulateTabWidget
from workers.db_worker import DbWorker
from core.config import load_config
from core.localization import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class CreatorStudioView(QWidget):
    """The universe builder screen."""

    def __init__(self, main_window: "MainWindow", parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._db_path: str | None = None
        self._db_worker: DbWorker | None = None
        self._save_worker: DbWorker | None = None
        
        # Pending AI operations (Chain: Save -> AI Task)
        self._pending_ai_tasks: list[str] = [] 
        self._pending_ai_mode: str = "auto"
        self._pending_ai_text: str | None = None

        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        self._universe_label = QLabel(tr("creator_studio"))
        self._universe_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        header.addWidget(self._universe_label)
        header.addStretch()

        self._save_btn = QPushButton(f"{tr('save_changes')} (Ctrl+S)")
        self._save_btn.setToolTip(tr("save_changes_tooltip") if "save_changes_tooltip" in tr("ready") else "Save all changes to the universe database (Ctrl+S)")
        self._back_btn = QPushButton(tr("hub"))
        self._back_btn.setToolTip(tr("back_to_hub_tooltip") if "back_to_hub_tooltip" in tr("ready") else "Return to the main library Hub")
        header.addWidget(self._save_btn)
        header.addWidget(self._back_btn)
        layout.addLayout(header)

        # Tabs
        self._tabs = QTabWidget()
        self._entity_editor = EntityEditorWidget()
        self._rule_editor = RuleEditorWidget()
        self._stat_editor = StatDefinitionEditorWidget()
        self._lore_book_editor = LoreBookEditorWidget()
        self._scheduled_events_editor = ScheduledEventsEditorWidget()
        self._populate_tab = PopulateTabWidget()
        
        self._tabs.addTab(self._build_lore_tab(), tr("tab_meta"))
        self._tabs.addTab(self._stat_editor, tr("stats"))
        self._tabs.addTab(self._entity_editor, tr("tab_entities"))
        self._tabs.addTab(self._rule_editor, tr("tab_rules"))
        self._tabs.addTab(self._scheduled_events_editor, tr("tab_events"))
        self._tabs.addTab(self._lore_book_editor, tr("tab_lore"))
        self._tabs.addTab(self._populate_tab, tr("populate"))
        layout.addWidget(self._tabs)

        # Connections
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._back_btn.clicked.connect(self._on_back_clicked)
        
        self._lore_book_editor.populate_requested.connect(self._on_populate_requested_single)
        self._populate_tab.populate_requested.connect(self._on_populate_requested)

    def _setup_shortcuts(self) -> None:
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.activated.connect(self._on_save_clicked)
        
        # Tab Navigation (Ctrl+1 to Ctrl+7)
        for i in range(7):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i+1}"), self)
            shortcut.activated.connect(lambda idx=i: self._tabs.setCurrentIndex(idx))

    def _build_lore_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self._lore_group = QGroupBox(tr("world_lore"))
        lore_layout = QVBoxLayout(self._lore_group)
        self._lore_edit = QPlainTextEdit()
        self._lore_edit.setPlaceholderText(tr("global_lore_placeholder"))
        lore_layout.addWidget(self._lore_edit)
        layout.addWidget(self._lore_group)

        self._prompt_group = QGroupBox(tr("sys_prompt_override"))
        prompt_layout = QVBoxLayout(self._prompt_group)
        self._system_prompt_edit = QPlainTextEdit()
        self._system_prompt_edit.setPlaceholderText(tr("system_prompt_placeholder"))
        self._system_prompt_edit.setMinimumHeight(80)
        prompt_layout.addWidget(self._system_prompt_edit)
        layout.addWidget(self._prompt_group)

        self._first_msg_group = QGroupBox(tr("init_narrative"))
        first_msg_layout = QVBoxLayout(self._first_msg_group)
        self._first_message_edit = QPlainTextEdit()
        self._first_message_edit.setPlaceholderText(tr("first_msg_placeholder"))
        self._first_message_edit.setMinimumHeight(80)
        first_msg_layout.addWidget(self._first_message_edit)
        layout.addWidget(self._first_msg_group)

        self._tension_group = QGroupBox(tr("world_tension_level"))
        tension_form = QFormLayout(self._tension_group)
        self._tension_spin = QDoubleSpinBox()
        self._tension_spin.setRange(0.0, 1.0)
        self._tension_spin.setSingleStep(0.05)
        self._tension_label_row = QLabel(f"{tr('tension')} (0.0-1.0):")
        tension_form.addRow(self._tension_label_row, self._tension_spin)
        
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 1.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_label_row = QLabel("LLM Temperature:")
        tension_form.addRow(self._temp_label_row, self._temp_spin)
        
        self._top_p_spin = QDoubleSpinBox()
        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.05)
        self._top_p_label_row = QLabel("LLM Top P:")
        tension_form.addRow(self._top_p_label_row, self._top_p_spin)

        from PySide6.QtWidgets import QComboBox
        self._verbosity_combo = QComboBox()
        self._verbosity_combo.addItems([tr("short"), tr("balanced"), tr("talkative")])
        self._verbosity_label_row = QLabel(f"{tr('verbosity')}:")
        tension_form.addRow(self._verbosity_label_row, self._verbosity_combo)

        layout.addWidget(self._tension_group)
        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        self._universe_label.setText(tr("creator_studio"))
        self._save_btn.setText(f"{tr('save_changes')} (Ctrl+S)")
        self._back_btn.setText(tr("hub"))
        self._tabs.setTabText(0, tr("tab_meta"))
        self._tabs.setTabText(1, tr("stats"))
        self._tabs.setTabText(2, tr("tab_entities"))
        self._tabs.setTabText(3, tr("tab_rules"))
        self._tabs.setTabText(4, tr("tab_events"))
        self._tabs.setTabText(5, tr("tab_lore"))
        self._tabs.setTabText(6, tr("populate"))

        self._lore_group.setTitle(tr("world_lore"))
        self._prompt_group.setTitle(tr("sys_prompt_override"))
        self._first_msg_group.setTitle(tr("init_narrative"))
        self._tension_group.setTitle(tr("world_tension_level"))
        self._tension_label_row.setText(f"{tr('tension')} (0.0-1.0):")
        self._temp_label_row.setText(tr("llm_temp"))
        self._top_p_label_row.setText(tr("llm_top_p"))
        self._verbosity_label_row.setText(f"{tr('verbosity')}:")
        
        self._lore_edit.setPlaceholderText(tr("global_lore_placeholder"))
        self._system_prompt_edit.setPlaceholderText(tr("system_prompt_placeholder"))
        self._first_message_edit.setPlaceholderText(tr("first_msg_placeholder"))

        self._entity_editor.retranslate_ui()
        self._rule_editor.retranslate_ui()
        self._stat_editor.retranslate_ui()
        self._lore_book_editor.retranslate_ui()
        self._scheduled_events_editor.retranslate_ui()

    def load_universe(self, db_path: str) -> None:
        self._db_path = db_path
        self._db_worker = DbWorker(db_path)
        self._db_worker.full_universe_loaded.connect(self._on_full_universe_loaded)
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        self._db_worker.load_full_universe()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(dict)
    def _on_full_universe_loaded(self, data: dict) -> None:
        sdefs = data.get("stat_definitions", [])
        self._stat_editor.populate(sdefs)
        self._entity_editor.populate(data.get("entities", []))
        self._entity_editor.set_stat_definitions(sdefs)
        self._rule_editor.populate(data.get("rules", []))
        self._rule_editor.set_stat_definitions(sdefs)
        self._lore_book_editor.populate(data.get("lore_book", []))
        self._scheduled_events_editor.set_events_and_calendar(data.get("scheduled_events", []), data.get("meta", {}))
        self._on_meta_loaded(data.get("meta", {}))

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        if index in (2, 3):
            sdefs = self._stat_editor.collect_data()
            self._entity_editor.set_stat_definitions(sdefs)
            self._rule_editor.set_stat_definitions(sdefs)

    @Slot()
    def _on_save_clicked(self) -> None:
        if not self._db_path: return

        events, cal_meta = self._scheduled_events_editor.collect_data()
        
        meta = {
            "global_lore": self._lore_edit.toPlainText().strip(),
            "system_prompt": self._system_prompt_edit.toPlainText().strip(),
            "first_message": self._first_message_edit.toPlainText().strip(),
            "world_tension_level": str(self._tension_spin.value()),
            "llm_temperature": str(self._temp_spin.value()),
            "llm_top_p": str(self._top_p_spin.value()),
            "llm_verbosity": self._verbosity_combo.currentText().lower(),
            "calendar_config": cal_meta.get("calendar_config", "{}")
        }

        data = {
            "meta": meta,
            "stat_definitions": self._stat_editor.collect_data(),
            "entities": self._entity_editor.collect_data(),
            "rules": self._rule_editor.collect_data(),
            "lore_book": self._lore_book_editor.collect_data(),
            "scheduled_events": events
        }

        self._save_worker = DbWorker(self._db_path)
        self._save_worker.save_complete.connect(self._on_save_complete)
        self._save_worker.error_occurred.connect(self._on_worker_error)
        self._save_worker.save_full_universe(
            data["entities"], data["rules"], data["meta"], 
            data["lore_book"], data["stat_definitions"], data["scheduled_events"]
        )

    @Slot()
    def _on_save_complete(self) -> None:
        self._main_window.on_status_update(tr("universe_saved"))
        if self._pending_ai_tasks:
            tasks = list(self._pending_ai_tasks)
            self._pending_ai_tasks = []
            for task in tasks:
                if task == "meta":
                    self._db_worker.populate_meta(self._pending_ai_mode, self._pending_ai_text)
                elif task == "stats":
                    self._db_worker.populate_stats(self._pending_ai_mode, self._pending_ai_text)
                elif task == "entities":
                    self._db_worker.populate_entities(self._pending_ai_mode, self._pending_ai_text)
                elif task == "rules":
                    self._db_worker.populate_rules(self._pending_ai_mode, self._pending_ai_text)
                elif task == "events":
                    self._db_worker.populate_events(self._pending_ai_mode, self._pending_ai_text)
                elif task == "lore":
                    self._db_worker.populate_lore(self._pending_ai_mode, self._pending_ai_text)

    @Slot(list, str, object)
    def _on_populate_requested(self, tasks: list[str], mode: str, text: str | None) -> None:
        self._pending_ai_tasks = tasks
        self._pending_ai_mode = mode
        self._pending_ai_text = text
        self._on_save_clicked()

    @Slot(str, object)
    def _on_populate_requested_single(self, task: str, text: str | None) -> None:
        """Helper for single-tab populate buttons."""
        self._on_populate_requested([task], "auto", text)

    def _on_meta_loaded(self, meta: dict) -> None:
        name = meta.get("universe_name", "Universe")
        self._universe_label.setText(f"{tr('creator_studio')} - {name}")
        self._lore_edit.setPlainText(meta.get("global_lore", ""))
        self._system_prompt_edit.setPlainText(meta.get("system_prompt", ""))
        self._first_message_edit.setPlainText(meta.get("first_message", ""))
        self._tension_spin.setValue(float(meta.get("world_tension_level", "0.3")))
        self._temp_spin.setValue(float(meta.get("llm_temperature", "0.7")))
        self._top_p_spin.setValue(float(meta.get("llm_top_p", "1.0")))
        
        v = meta.get("llm_verbosity", "balanced")
        idx = -1
        for i in range(self._verbosity_combo.count()):
            if self._verbosity_combo.itemText(i).lower() == tr(v).lower() or self._verbosity_combo.itemText(i).lower() == v.lower():
                idx = i
                break
        self._verbosity_combo.setCurrentIndex(max(0, idx))

    @Slot()
    def _on_back_clicked(self) -> None:
        self._main_window.show_hub()

    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        self._pending_ai_task = None
        QMessageBox.critical(self, tr("error"), message)
