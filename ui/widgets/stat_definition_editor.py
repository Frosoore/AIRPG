"""
ui/widgets/stat_definition_editor.py

Visual editor for Stat Definitions in the Creator Studio.
Allows defining stats as 'numeric' or 'categorical' with specific parameters.
"""

from __future__ import annotations

import json
import uuid

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
    QDoubleSpinBox,
)

try:
    from database.presets import STAT_PRESETS
except ImportError:
    STAT_PRESETS = {}


class StatDefinitionEditorWidget(QWidget):
    """Visual builder for the Creator Studio Stats tab.

    Users can manage the list of stats and define their types and parameters.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stats_data: list[dict] = []
        self._selected_row: int = -1
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # Left - Stat list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("<b>Stat Definitions</b>"))

        self._stat_list = QListWidget()
        self._stat_list.currentRowChanged.connect(self._on_stat_selected)
        left_layout.addWidget(self._stat_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add")
        del_btn = QPushButton("Delete")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        left_layout.addLayout(btn_row)

        add_btn.clicked.connect(self._on_add_stat)
        del_btn.clicked.connect(self._on_delete_stat)

        # Stat Presets UI
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(list(STAT_PRESETS.keys()))
        self._preset_btn = QPushButton("Apply Preset")
        
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(self._preset_combo)
        preset_layout.addWidget(self._preset_btn)
        left_layout.addLayout(preset_layout)

        self._preset_btn.clicked.connect(self._on_apply_preset)

        # Right - Stat form
        right = QWidget()
        right_layout = QVBoxLayout(right)
        
        basic_form = QFormLayout()
        self._id_input = QLineEdit()
        self._name_input = QLineEdit()
        self._desc_input = QLineEdit()
        self._type_combo = QComboBox()
        self._type_combo.addItems(["numeric", "categorical"])
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        basic_form.addRow("Stat ID:", self._id_input)
        basic_form.addRow("Name:", self._name_input)
        basic_form.addRow("Description:", self._desc_input)
        basic_form.addRow("Value Type:", self._type_combo)
        right_layout.addLayout(basic_form)

        # Parameters Stack
        self._params_stack = QStackedWidget()
        
        # Numeric Params
        self._numeric_widget = QWidget()
        num_layout = QFormLayout(self._numeric_widget)
        self._min_spin = QDoubleSpinBox()
        self._min_spin.setRange(-999999, 999999)
        self._max_spin = QDoubleSpinBox()
        self._max_spin.setRange(-999999, 999999)
        self._max_spin.setValue(100)
        num_layout.addRow("Min Value:", self._min_spin)
        num_layout.addRow("Max Value:", self._max_spin)
        
        # Categorical Params
        self._categorical_widget = QWidget()
        cat_layout = QFormLayout(self._categorical_widget)
        self._options_input = QLineEdit()
        self._options_input.setPlaceholderText("Choice 1, Choice 2, ...")
        cat_layout.addRow("Options (CSV):", self._options_input)

        self._params_stack.addWidget(self._numeric_widget)
        self._params_stack.addWidget(self._categorical_widget)
        
        right_layout.addWidget(QLabel("<b>Type Parameters</b>"))
        right_layout.addWidget(self._params_stack)
        right_layout.addStretch()

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([200, 400])
        layout.addWidget(splitter)

    @Slot(list)
    def populate(self, stats: list[dict]) -> None:
        """Populate the stat list."""
        self._selected_row = -1
        self._stats_data = stats
        self._stat_list.clear()
        for stat in stats:
            self._stat_list.addItem(f"{stat.get('name', '?')} ({stat.get('stat_id', '?')})")
        if stats:
            self._stat_list.setCurrentRow(0)

    def collect_data(self) -> list[dict]:
        """Return the current form state as a list of stat definitions."""
        self._sync_current_form()
        return list(self._stats_data)

    def _on_stat_selected(self, row: int) -> None:
        self._sync_current_form()
        self._selected_row = row

        if row < 0 or row >= len(self._stats_data):
            return
        stat = self._stats_data[row]

        self._id_input.setText(stat.get("stat_id", ""))
        self._name_input.setText(stat.get("name", ""))
        self._desc_input.setText(stat.get("description", ""))
        
        vtype = stat.get("value_type", "numeric")
        idx = self._type_combo.findText(vtype)
        self._type_combo.setCurrentIndex(max(0, idx))
        self._on_type_changed(self._type_combo.currentIndex())

        params = stat.get("parameters", {})
        if vtype == "numeric":
            self._min_spin.setValue(float(params.get("min", 0)))
            self._max_spin.setValue(float(params.get("max", 100)))
        else:
            options = params.get("options", [])
            self._options_input.setText(", ".join(options))

    @Slot()
    def _on_add_stat(self) -> None:
        self._sync_current_form()
        new_stat = {
            "stat_id": f"stat_{uuid.uuid4().hex[:6]}",
            "name": "New Stat",
            "description": "",
            "value_type": "numeric",
            "parameters": {"min": 0, "max": 100}
        }
        self._stats_data.append(new_stat)
        self._stat_list.addItem(f"{new_stat['name']} ({new_stat['stat_id']})")
        self._stat_list.setCurrentRow(len(self._stats_data) - 1)

    @Slot()
    def _on_delete_stat(self) -> None:
        row = self._selected_row
        if row < 0 or row >= len(self._stats_data):
            return
            
        # 1. Block signals to prevent the list from triggering premature events
        self._stat_list.blockSignals(True)
        
        # 2. Remove the data and the visual item
        del self._stats_data[row]
        self._stat_list.takeItem(row)
        
        # 3. Reset local selection BEFORE unblocking,
        # to prevent _sync_current_form from overwriting the new row with old UI data
        self._selected_row = -1 
        
        # 4. Unblock signals
        self._stat_list.blockSignals(False)
        
        # 5. Force selection of the new element (if list is not empty)
        new_row = self._stat_list.currentRow()
        if new_row >= 0:
            self._on_stat_selected(new_row)
        else:
            # Clear form if everything was deleted
            self._id_input.clear()
            self._name_input.clear()
            self._desc_input.clear()

    @Slot()
    def _on_apply_preset(self) -> None:
        """Add all stats from the selected preset pack."""
        preset_name = self._preset_combo.currentText()
        if preset_name not in STAT_PRESETS:
            return

        self._sync_current_form()
        for stat_template in STAT_PRESETS[preset_name]:
            new_stat = {
                "stat_id": uuid.uuid4().hex[:6],
                "name": stat_template["name"],
                "description": stat_template.get("description", ""),
                "value_type": stat_template["value_type"],
                "parameters": stat_template.get("parameters", {})
            }
            self._stats_data.append(new_stat)
            self._stat_list.addItem(f"{new_stat['name']} ({new_stat['stat_id']})")
        
        if STAT_PRESETS[preset_name]:
            self._stat_list.setCurrentRow(len(self._stats_data) - 1)

    @Slot(int)
    def _on_type_changed(self, index: int) -> None:
        self._params_stack.setCurrentIndex(index)

    def _sync_current_form(self) -> None:
        row = self._selected_row
        if row < 0 or row >= len(self._stats_data):
            return

        vtype = self._type_combo.currentText()
        params = {}
        if vtype == "numeric":
            params = {"min": self._min_spin.value(), "max": self._max_spin.value()}
        else:
            options = [o.strip() for o in self._options_input.text().split(",") if o.strip()]
            params = {"options": options}

        stat_id = self._id_input.text().strip()
        name = self._name_input.text().strip()

        self._stats_data[row] = {
            "stat_id": stat_id,
            "name": name,
            "description": self._desc_input.text().strip(),
            "value_type": vtype,
            "parameters": params
        }

        item = self._stat_list.item(row)
        if item:
            item.setText(f"{name or '?'} ({stat_id or '?'})")
