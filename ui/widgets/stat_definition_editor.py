"""
ui/widgets/stat_definition_editor.py

Visual editor for Stat Definitions in the Creator Studio.
Uses a spreadsheet-like grid for direct editing and keyboard navigation.
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
    QVBoxLayout,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
)
from core.localization import tr

try:
    from database.presets import STAT_PRESETS
except ImportError:
    STAT_PRESETS = {}


class StatDefinitionEditorWidget(QWidget):
    """Spreadsheet-like builder for the Creator Studio Stats tab."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header & Presets
        top_row = QHBoxLayout()
        self._header = QLabel(f"<b>{tr('stats')}</b>")
        top_row.addWidget(self._header)
        top_row.addStretch()

        self._preset_combo = QComboBox()
        self._preset_combo.addItems(list(STAT_PRESETS.keys()))
        self._preset_btn = QPushButton(tr("apply_preset"))
        self._preset_btn.setToolTip(tr("apply_preset_tooltip") if "apply_preset_tooltip" in tr("ready") else "Add a set of predefined stats")
        top_row.addWidget(self._preset_combo)
        top_row.addWidget(self._preset_btn)
        self._preset_btn.clicked.connect(self._on_apply_preset)
        layout.addLayout(top_row)

        # Input Row (Write before Add)
        input_group = QHBoxLayout()
        self._id_input = QLineEdit()
        self._id_input.setPlaceholderText(f"{tr('stat')} ID")
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText(tr("name"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([tr("numeric"), tr("categorical")])
        
        self._add_btn = QPushButton(f"{tr('add')} +")
        self._add_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        
        input_group.addWidget(self._id_input, 2)
        input_group.addWidget(self._name_input, 3)
        input_group.addWidget(self._type_combo, 2)
        input_group.addWidget(self._add_btn, 1)
        layout.addLayout(input_group)

        self._add_btn.clicked.connect(self._on_add_clicked)

        # Main Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            tr("id"), tr("name"), tr("type"), tr("description"), tr("options")
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.setAlternatingRowColors(True)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)

        # Bottom Actions
        bottom_row = QHBoxLayout()
        self._del_btn = QPushButton(tr("delete"))
        self._del_btn.setToolTip(f"{tr('delete')} (Del)")
        bottom_row.addWidget(self._del_btn)
        bottom_row.addStretch()
        layout.addLayout(bottom_row)

        self._del_btn.clicked.connect(self._on_delete_stat)

    @Slot(list)
    def populate(self, stats: list[dict]) -> None:
        """Populate the table from a list of stat definitions."""
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for s in stats:
            self._add_row(s)
        self._table.blockSignals(False)

    def collect_data(self) -> list[dict]:
        """Return the current table state as a list of stat definitions."""
        stats = []
        for row in range(self._table.rowCount()):
            sid = self._table.item(row, 0).text().strip()
            name = self._table.item(row, 1).text().strip()
            vtype_display = self._table.item(row, 2).text().strip()
            desc = self._table.item(row, 3).text().strip()
            params_raw = self._table.item(row, 4).text().strip()

            vtype = "numeric" if vtype_display == tr("numeric") else "categorical"
            
            params = {}
            if vtype == "numeric":
                # Try to parse "min:X, max:Y"
                try:
                    p_parts = [p.split(":") for p in params_raw.split(",") if ":" in p]
                    p_dict = {k.strip().lower(): v.strip() for k, v in p_parts}
                    params["min"] = float(p_dict.get("min", 0))
                    params["max"] = float(p_dict.get("max", 100))
                except (ValueError, TypeError):
                    params = {"min": 0, "max": 100}
            else:
                options = [o.strip() for o in params_raw.split(",") if o.strip()]
                params["options"] = options

            stats.append({
                "stat_id": sid,
                "name": name,
                "description": desc,
                "value_type": vtype,
                "parameters": params
            })
        return stats

    def retranslate_ui(self) -> None:
        """Refresh all UI text for the current language."""
        self._header.setText(f"<b>{tr('stats')}</b>")
        self._add_btn.setText(f"{tr('add')} +")
        self._del_btn.setText(tr("delete"))
        self._preset_btn.setText(tr("apply_preset"))
        
        self._id_input.setPlaceholderText(f"{tr('stat')} ID")
        self._name_input.setPlaceholderText(tr("name"))
        
        # Update type combo
        self._type_combo.blockSignals(True)
        curr = self._type_combo.currentIndex()
        self._type_combo.clear()
        self._type_combo.addItems([tr("numeric"), tr("categorical")])
        self._type_combo.setCurrentIndex(curr)
        self._type_combo.blockSignals(False)

        self._table.setHorizontalHeaderLabels([
            tr("id"), tr("name"), tr("type"), tr("description"), tr("options")
        ])

    def _add_row(self, stat: dict | None = None) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        if not stat:
            stat = {
                "stat_id": f"stat_{uuid.uuid4().hex[:6]}",
                "name": tr("new_stat"),
                "value_type": "numeric",
                "description": "",
                "parameters": {"min": 0, "max": 100}
            }

        it_id = QTableWidgetItem(stat.get("stat_id", ""))
        it_name = QTableWidgetItem(stat.get("name", ""))
        
        vtype = stat.get("value_type", "numeric")
        it_type = QTableWidgetItem(tr(vtype))
        it_type.setFlags(it_type.flags() & ~Qt.ItemIsEditable) # Type fixed on add for simplicity, or we can make it a combo
        
        it_desc = QTableWidgetItem(stat.get("description", ""))
        
        params = stat.get("parameters", {})
        if vtype == "numeric":
            from core.localization import fmt_num
            p_min = fmt_num(params.get('min', 0))
            p_max = fmt_num(params.get('max', 100))
            params_str = f"min:{p_min}, max:{p_max}"
        else:
            params_str = ", ".join(params.get("options", []))
        it_params = QTableWidgetItem(params_str)

        self._table.setItem(row, 0, it_id)
        self._table.setItem(row, 1, it_name)
        self._table.setItem(row, 2, it_type)
        self._table.setItem(row, 3, it_desc)
        self._table.setItem(row, 4, it_params)

    @Slot()
    def _on_add_clicked(self) -> None:
        """Add new stat using data from the input row."""
        sid = self._id_input.text().strip()
        name = self._name_input.text().strip()
        vtype = "numeric" if self._type_combo.currentIndex() == 0 else "categorical"

        if not sid:
            sid = f"stat_{uuid.uuid4().hex[:6]}"
        if not name:
            name = tr("new_stat")

        new_stat = {
            "stat_id": sid,
            "name": name,
            "value_type": vtype,
            "description": "",
            "parameters": {"min": 0, "max": 100} if vtype == "numeric" else {"options": []}
        }
        self._add_row(new_stat)
        self._id_input.clear()
        self._name_input.clear()
        self.changed.emit()

    @Slot()
    def _on_delete_stat(self) -> None:
        """Remove the selected row(s)."""
        indices = self._table.selectionModel().selectedRows()
        if not indices:
            # Fallback to current item's row if no full rows selected
            curr = self._table.currentRow()
            if curr >= 0:
                self._table.removeRow(curr)
                self.changed.emit()
            return

        # Sort indices in reverse to delete from bottom up
        rows = sorted([i.row() for i in indices], reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self.changed.emit()

    @Slot()
    def _on_apply_preset(self) -> None:
        """Add all stats from the selected preset pack."""
        preset_name = self._preset_combo.currentText()
        if preset_name not in STAT_PRESETS:
            return

        for stat_template in STAT_PRESETS[preset_name]:
            new_stat = {
                "stat_id": uuid.uuid4().hex[:6],
                "name": stat_template["name"],
                "description": stat_template.get("description", ""),
                "value_type": stat_template["value_type"],
                "parameters": stat_template.get("parameters", {})
            }
            self._add_row(new_stat)
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        """Handle Delete key to remove rows."""
        if event.key() == Qt.Key_Delete:
            self._on_delete_stat()
        else:
            super().keyPressEvent(event)
