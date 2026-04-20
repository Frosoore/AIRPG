"""
ui/creator_studio_view.py

Creator Studio screen for AIRPG.

Provides a visual interface for building universe content (entities, rules,
lore settings, and the Lore Book) without exposing raw JSON to the creator.

THREADING RULE: All SQLite writes are delegated to DbWorker.
No database I/O happens on the main thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
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
from workers.db_worker import DbWorker
from core.config import load_config, build_llm_from_config

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class CreatorStudioView(QWidget):
    """The universe builder screen.

    Args:
        main_window: Reference to MainWindow for navigation calls.
        parent:      Optional Qt parent widget.
    """

    def __init__(self, main_window: "MainWindow", parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._db_path: str | None = None
        self._db_worker: DbWorker | None = None
        self._save_worker: DbWorker | None = None
        self._populate_after_save: bool = False

        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the studio layout with tabs for entities and rules."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        self._universe_label = QLabel("Creator Studio")
        self._universe_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        header.addWidget(self._universe_label)
        header.addStretch()

        self._save_btn = QPushButton("Save Changes")
        self._back_btn = QPushButton("Back to Hub")
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
        
        self._tabs.addTab(self._build_lore_tab(), "Lore & Settings")
        self._tabs.addTab(self._stat_editor, "Stats")
        self._tabs.addTab(self._entity_editor, "Entities")
        self._tabs.addTab(self._rule_editor, "Rules")
        self._tabs.addTab(self._scheduled_events_editor, "Scheduled Events")
        self._tabs.addTab(self._lore_book_editor, "Lore Book")
        layout.addWidget(self._tabs)

        # Connections
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._back_btn.clicked.connect(self._on_back_clicked)
        self._entity_editor.populate_requested.connect(self._on_populate_requested)

    def _build_lore_tab(self) -> QWidget:
        """Build the 'Lore & Settings' tab widget."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        lore_group = QGroupBox("Global World Lore")
        lore_layout = QVBoxLayout(lore_group)
        self._lore_edit = QPlainTextEdit()
        self._lore_edit.setPlaceholderText(
            "Foundational context for the LLM.  Describe the world's geography, "
            "history, and core themes here."
        )
        lore_layout.addWidget(self._lore_edit)
        layout.addWidget(lore_group)

        prompt_group = QGroupBox("System Prompt Override")
        prompt_layout = QVBoxLayout(prompt_group)
        self._system_prompt_edit = QPlainTextEdit()
        self._system_prompt_edit.setPlaceholderText(
            "e.g. You are the narrator of a gritty dark-fantasy world..."
        )
        self._system_prompt_edit.setMinimumHeight(80)
        prompt_layout.addWidget(self._system_prompt_edit)
        layout.addWidget(prompt_group)

        # Phase 7: First Message option
        first_msg_group = QGroupBox("Initial Narrative (First Message)")
        first_msg_layout = QVBoxLayout(first_msg_group)
        self._first_message_edit = QPlainTextEdit()
        self._first_message_edit.setPlaceholderText(
            "The very first text the player sees when starting a new game in this universe...\n\n"
            "Separate multiple variants with ---VARIANT---"
        )
        self._first_message_edit.setMinimumHeight(80)
        first_msg_layout.addWidget(self._first_message_edit)
        layout.addWidget(first_msg_group)

        tension_group = QGroupBox("World Tension Level")
        tension_form = QFormLayout(tension_group)
        self._tension_spin = QDoubleSpinBox()
        self._tension_spin.setRange(0.0, 1.0)
        self._tension_spin.setSingleStep(0.05)
        self._tension_spin.setToolTip(
            "0.0 = mundane world (trade, politics). "
            "1.0 = high tension (assassinations, wars, cataclysms)."
        )
        tension_form.addRow("Tension (0.0-1.0):", self._tension_spin)
        
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 1.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_spin.setToolTip("LLM Temperature (0.0 = deterministic, 1.0 = creative)")
        tension_form.addRow("LLM Temperature:", self._temp_spin)
        
        self._top_p_spin = QDoubleSpinBox()
        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.05)
        self._top_p_spin.setToolTip("LLM Top P (Nucleus Sampling)")
        tension_form.addRow("LLM Top P:", self._top_p_spin)

        from PySide6.QtWidgets import QComboBox
        self._verbosity_combo = QComboBox()
        self._verbosity_combo.addItems(["Short", "Balanced", "Talkative"])
        self._verbosity_combo.setToolTip("Controls how detailed the AI's narrative responses will be.")
        tension_form.addRow("Default Verbosity:", self._verbosity_combo)

        layout.addWidget(tension_group)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_universe(self, db_path: str) -> None:
        """Load all data for the given universe into the editors.

        Uses DbWorker.load_full_universe to fetch entities, rules, lore book,
        and meta in a single pass, ensuring UI synchronization and preventing
        task-overwriting bugs.
        """
        self._db_path = db_path
        self._db_worker = DbWorker(db_path)
        self._db_worker.entities_loaded.connect(self._entity_editor.populate)
        self._db_worker.entities_loaded.connect(lambda _: self._entity_editor.set_populate_enabled(True))
        self._db_worker.rules_loaded.connect(self._rule_editor.populate)
        self._db_worker.stat_definitions_loaded.connect(self._stat_editor.populate)
        self._db_worker.stat_definitions_loaded.connect(self._entity_editor.set_stat_definitions)
        self._db_worker.lore_book_loaded.connect(self._lore_book_editor.populate)
        self._db_worker.scheduled_events_loaded.connect(self._scheduled_events_editor.set_events)
        self._db_worker.universe_meta_loaded.connect(self._on_meta_loaded)
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)

        # Single atomic load task
        self._db_worker.load_full_universe()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        """Sync data between tabs when switching (e.g. Stat definitions)."""
        if self._tabs.widget(index) == self._entity_editor:
            # Stats -> Entities sync
            stat_defs = self._stat_editor.collect_data()
            self._entity_editor.set_stat_definitions(stat_defs)

    @Slot()
    def _on_save_clicked(self) -> None:
        """Collect all tab data and launch ONE atomic DbWorker save task.

        Phase 7: Absolute Persistence Protocol.  Collects data from all four
        tabs and issues a single save_full_universe call.  The worker is held in
        self._save_worker to prevent premature GC, and error_occurred is
        connected to a critical alert dialog.
        """
        if not self._db_path:
            QMessageBox.warning(self, "No Universe", "No universe is currently loaded.")
            return

        entities = self._entity_editor.collect_data()
        rules = self._rule_editor.collect_data()
        stat_definitions = self._stat_editor.collect_data()
        lore_book = self._lore_book_editor.collect_data()
        scheduled_events = self._scheduled_events_editor.get_events()
        
        fm_text = self._first_message_edit.toPlainText().strip()
        variants = [v.strip() for v in fm_text.split("---VARIANT---") if v.strip()]
        import json
        if variants:
            fm_payload = json.dumps({"active": 0, "variants": variants})
        else:
            fm_payload = ""

        meta = {
            "global_lore": self._lore_edit.toPlainText().strip(),
            "system_prompt": self._system_prompt_edit.toPlainText().strip(),
            "first_message": fm_payload,
            "world_tension_level": str(self._tension_spin.value()),
            "llm_temperature": str(self._temp_spin.value()),
            "llm_top_p": str(self._top_p_spin.value()),
            "llm_verbosity": self._verbosity_combo.currentText().lower(),
        }

        # Phase 7: Enforced worker persistence and error wiring
        self._save_worker = DbWorker(self._db_path)
        self._save_worker.save_complete.connect(self._on_save_complete)
        self._save_worker.error_occurred.connect(self._on_worker_error)
        self._save_worker.status_update.connect(self._main_window.on_status_update)
        self._save_worker.save_full_universe(
            entities, rules, meta, lore_book, stat_definitions, scheduled_events
        )

    @Slot()
    def _on_save_complete(self) -> None:
        """Show absolute visual confirmation that the database commit succeeded."""
        self._main_window.on_status_update("Universe saved successfully.")
        
        # Phase 11: Auto-trigger Populate if it was requested
        if self._populate_after_save:
            self._populate_after_save = False
            if self._db_worker:
                self._db_worker.populate_entities()

    @Slot()
    def _on_back_clicked(self) -> None:
        """Return to the hub library."""
        self._main_window.show_hub()

    @Slot()
    def _on_populate_requested(self) -> None:
        """Chain Save -> Populate sequence to ensure AI sees latest Stats/Lore.
        
        Local models read from the DB file. If the user just imported stats
        but didn't save, the AI prompt would show 'No stats defined'.
        """
        if not self._db_path:
            return

        self._populate_after_save = True
        self._entity_editor.set_populate_enabled(False)
        self._main_window.on_status_update("Saving changes before AI generation...")
        
        # Trigger the standard save flow
        self._on_save_clicked()

    @Slot(dict)
    def _on_meta_loaded(self, meta: dict) -> None:
        """Update the title label and populate Lore & Settings fields."""
        name = meta.get("universe_name", "Universe")
        self._universe_label.setText(f"Creator Studio - {name}")

        self._lore_edit.setPlainText(meta.get("global_lore", ""))
        self._system_prompt_edit.setPlainText(meta.get("system_prompt", ""))
        
        fm_raw = meta.get("first_message", "")
        fm_text = fm_raw
        import json
        try:
            data = json.loads(fm_raw)
            if isinstance(data, dict) and "variants" in data:
                fm_text = "\n\n---VARIANT---\n\n".join(data["variants"])
        except Exception:
            pass
        self._first_message_edit.setPlainText(fm_text)
        
        try:
            tension = float(meta.get("world_tension_level", "0.3"))
        except ValueError:
            tension = 0.3
        self._tension_spin.setValue(max(0.0, min(1.0, tension)))
        
        try:
            temp = float(meta.get("llm_temperature", "0.7"))
        except ValueError:
            temp = 0.7
        self._temp_spin.setValue(max(0.0, min(1.0, temp)))
        
        try:
            top_p = float(meta.get("llm_top_p", "1.0"))
        except ValueError:
            top_p = 1.0
        self._top_p_spin.setValue(max(0.0, min(1.0, top_p)))
        
        verbosity = meta.get("llm_verbosity", "balanced").capitalize()
        idx = self._verbosity_combo.findText(verbosity)
        self._verbosity_combo.setCurrentIndex(max(0, idx))

        self._main_window.on_status_update("Ready.")

    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        """Show a critical error dialog and re-enable UI."""
        self._populate_after_save = False
        self._entity_editor.set_populate_enabled(True)
        QMessageBox.critical(self, "Database Error", message)
