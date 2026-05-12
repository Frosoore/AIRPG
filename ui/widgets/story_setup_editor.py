"""
ui/widgets/story_setup_editor.py

Visual editor for universe story setup questions in the Creator Studio.
Allows creators to define initialization questions for players.
"""

from __future__ import annotations

import json
import uuid
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
    QSpinBox,
)
from core.localization import tr


class StorySetupEditorWidget(QWidget):
    """Spreadsheet-like editor for story setup questions."""

    _TYPES: list[str] = ["text", "single_choice", "multi_choice"]

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_data: list[dict] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        self._header = QLabel(f"<b>{tr('tab_setup')}</b>")
        layout.addWidget(self._header)

        # Input Row
        input_group = QHBoxLayout()
        
        self._in_id = QLineEdit()
        self._in_id.setPlaceholderText("Tag ID (e.g., race)")
        self._in_id.setToolTip("The ID used for @id replacements in the first message.")
        
        self._in_question = QLineEdit()
        self._in_question.setPlaceholderText("Question Text")
        self._in_question.setToolTip("The question shown to the player.")
        
        self._in_type = QComboBox()
        self._in_type.addItems(self._TYPES)
        
        self._add_btn = QPushButton(f"{tr('add')} +")
        self._add_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self._add_btn.clicked.connect(self._on_add_clicked)

        input_group.addWidget(self._in_id, 1)
        input_group.addWidget(self._in_question, 3)
        input_group.addWidget(self._in_type, 1)
        input_group.addWidget(self._add_btn, 1)
        layout.addLayout(input_group)

        # Questions Table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "ID", "Question", "Type", "Options (JSON)", "Max Sel", "Priority"
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)

        # Delete Button
        self._del_btn = QPushButton(tr("delete"))
        self._del_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self._del_btn)

    def retranslate_ui(self) -> None:
        self._header.setText(f"<b>{tr('tab_setup')}</b>")
        self._add_btn.setText(f"{tr('add')} +")
        self._del_btn.setText(tr("delete"))
        self._table.setHorizontalHeaderLabels([
            "ID", tr("question") if "question" in tr("ready") else "Question", 
            tr("type") if "type" in tr("ready") else "Type", 
            "Options (JSON)", "Max Sel", tr("priority")
        ])

    @Slot(list)
    def populate(self, setup_data: list[dict]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._setup_data = [dict(s) for s in setup_data]
        
        for s in self._setup_data:
            self._add_row(s)
            
        self._table.blockSignals(False)

    def collect_data(self) -> list[dict]:
        data = []
        for r in range(self._table.rowCount()):
            setup_id = self._table.item(r, 0).text().strip()
            if not setup_id: continue
            
            # Read from widgets in Type column
            type_w = self._table.cellWidget(r, 2)
            stype = type_w.currentText() if isinstance(type_w, QComboBox) else "text"
            
            try:
                options = json.loads(self._table.item(r, 3).text().strip() or "[]")
            except:
                options = []

            data.append({
                "setup_id": setup_id,
                "question": self._table.item(r, 1).text().strip(),
                "type": stype,
                "options": options,
                "max_selections": int(self._table.item(r, 4).text().strip() or 1),
                "priority": int(self._table.item(r, 5).text().strip() or 0)
            })
        return data

    def _add_row(self, s: dict) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        
        self._table.setItem(row, 0, QTableWidgetItem(s.get("setup_id", "")))
        self._table.setItem(row, 1, QTableWidgetItem(s.get("question", "")))
        
        type_combo = QComboBox()
        type_combo.addItems(self._TYPES)
        type_combo.setCurrentText(s.get("type", "text"))
        type_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        self._table.setCellWidget(row, 2, type_combo)
        
        self._table.setItem(row, 3, QTableWidgetItem(json.dumps(s.get("options", []))))
        self._table.setItem(row, 4, QTableWidgetItem(str(s.get("max_selections", 1))))
        self._table.setItem(row, 5, QTableWidgetItem(str(s.get("priority", 0))))

    @Slot()
    def _on_add_clicked(self) -> None:
        sid = self._in_id.text().strip()
        if not sid: return
        
        new_s = {
            "setup_id": sid,
            "question": self._in_question.text().strip(),
            "type": self._in_type.currentText(),
            "options": [],
            "max_selections": 1,
            "priority": 0
        }
        self._add_row(new_s)
        self._in_id.clear()
        self._in_question.clear()
        self.changed.emit()

    @Slot()
    def _on_delete_clicked(self) -> None:
        rows = sorted(set(index.row() for index in self._table.selectedIndexes()), reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        self.changed.emit()
