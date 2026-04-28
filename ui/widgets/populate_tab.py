"""
ui/widgets/populate_tab.py

Consolidated AI Population tab for the Creator Studio.
Allows generating entities and lore entries from existing context or custom text.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QButtonGroup,
)
from core.localization import tr


class PopulateTabWidget(QWidget):
    """Refactored AI Population interface."""

    # Emits (targets: list[str], mode: str, text: str|None)
    # targets may contain: "meta", "stats", "entities", "rules", "events", "lore"
    populate_requested = Signal(list, str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        self._header = QLabel(f"<b>{tr('populate')} ✨</b>")
        self._header.setStyleSheet("font-size: 18px;")
        layout.addWidget(self._header)

        # --- Target Group ---
        self._target_group = QGroupBox(tr("generation_target") if "generation_target" in tr("ready") else "What to generate?")
        target_layout = QVBoxLayout(self._target_group)
        
        self._check_meta = QCheckBox(tr("tab_meta"))
        self._check_stats = QCheckBox(tr("stats"))
        self._check_entities = QCheckBox(tr("tab_entities"))
        self._check_entities.setChecked(True)
        self._check_rules = QCheckBox(tr("tab_rules"))
        self._check_events = QCheckBox(tr("tab_events"))
        self._check_lore = QCheckBox(tr("tab_lore"))
        
        target_layout.addWidget(self._check_meta)
        target_layout.addWidget(self._check_stats)
        target_layout.addWidget(self._check_entities)
        target_layout.addWidget(self._check_rules)
        target_layout.addWidget(self._check_events)
        target_layout.addWidget(self._check_lore)
        layout.addWidget(self._target_group)

        # --- Source Group ---
        self._source_group = QGroupBox(tr("generation_source") if "generation_source" in tr("ready") else "Information Source")
        source_layout = QVBoxLayout(self._source_group)
        
        self._source_btn_group = QButtonGroup(self)
        
        self._radio_auto = QRadioButton(tr("populate_auto") if "populate_auto" in tr("ready") else "Automatic: Infer from existing tabs (Lore, Stats, Rules)")
        self._radio_auto.setChecked(True)
        self._source_btn_group.addButton(self._radio_auto)
        
        self._radio_custom = QRadioButton(tr("populate_custom") if "populate_custom" in tr("ready") else "Custom: Use a specific narrative prompt")
        self._source_btn_group.addButton(self._radio_custom)
        
        self._custom_text = QPlainTextEdit()
        self._custom_text.setPlaceholderText("e.g. 'Add a group of 3 rival merchants in the capital city...'")
        self._custom_text.setEnabled(False)
        self._custom_text.setMaximumHeight(150)
        
        self._radio_custom.toggled.connect(self._custom_text.setEnabled)
        
        source_layout.addWidget(self._radio_auto)
        source_layout.addWidget(self._radio_custom)
        source_layout.addWidget(self._custom_text)
        layout.addWidget(self._source_group)

        # --- Actions ---
        layout.addStretch()
        
        self._warning_label = QLabel(f"<i>{tr('populate_warning') if 'populate_warning' in tr('ready') else 'Note: Generating will automatically save your changes first.'}</i>")
        self._warning_label.setStyleSheet("color: #a6adc8;")
        self._warning_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._warning_label)

        self._start_btn = QPushButton(f"{tr('start_generation') if 'start_generation' in tr('ready') else 'Start AI Population'} ✨")
        self._start_btn.setMinimumHeight(50)
        self._start_btn.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; font-size: 14px;")
        self._start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self._start_btn)

    def retranslate_ui(self) -> None:
        self._header.setText(f"<b>{tr('populate')} ✨</b>")
        self._target_group.setTitle(tr("generation_target") if "generation_target" in tr("ready") else "What to generate?")
        self._check_meta.setText(tr("tab_meta"))
        self._check_stats.setText(tr("stats"))
        self._check_entities.setText(tr("tab_entities"))
        self._check_rules.setText(tr("tab_rules"))
        self._check_events.setText(tr("tab_events"))
        self._check_lore.setText(tr("tab_lore"))
        
        self._source_group.setTitle(tr("generation_source") if "generation_source" in tr("ready") else "Information Source")
        self._radio_auto.setText(tr("populate_auto") if "populate_auto" in tr("ready") else "Automatic: Infer from existing tabs")
        self._radio_custom.setText(tr("populate_custom") if "populate_custom" in tr("ready") else "Custom: Use a specific narrative prompt")
        
        self._warning_label.setText(f"<i>{tr('populate_warning') if 'populate_warning' in tr('ready') else 'Note: Generating will automatically save your changes first.'}</i>")
        self._start_btn.setText(f"{tr('start_generation') if 'start_generation' in tr('ready') else 'Start AI Population'} ✨")

    @Slot()
    def _on_start_clicked(self) -> None:
        targets = []
        if self._check_meta.isChecked(): targets.append("meta")
        if self._check_stats.isChecked(): targets.append("stats")
        if self._check_entities.isChecked(): targets.append("entities")
        if self._check_rules.isChecked(): targets.append("rules")
        if self._check_events.isChecked(): targets.append("events")
        if self._check_lore.isChecked(): targets.append("lore")

        if not targets:
            return

        mode = "auto" if self._radio_auto.isChecked() else "custom"
        text = self._custom_text.toPlainText().strip() if mode == "custom" else None
            
        self.populate_requested.emit(targets, mode, text)
