"""
ui/widgets/rule_editor.py

Visual editor for universe rules in the Creator Studio.
Uses a main rule table and sub-tables for conditions and actions.
"""

from __future__ import annotations

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
    QGroupBox,
    QSpinBox,
)
from core.localization import tr


class RuleEditorWidget(QWidget):
    """Spreadsheet-like rule builder for the Creator Studio."""

    # Canonical keys
    _COMPARATORS: list[str] = ["<=", ">=", "==", "!=", "<", ">"]
    _ACTION_TYPES: list[str] = ["stat_change", "stat_set", "trigger_event", "set_status"]

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rules_data: list[dict] = []
        self._stat_defs: list[dict] = []
        self._selected_row: int = -1
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        self._header = QLabel(f"<b>{tr('tab_rules')}</b>")
        layout.addWidget(self._header)

        # Input Row (Write before Add)
        input_group = QHBoxLayout()
        self._in_id = QLineEdit()
        self._in_id.setPlaceholderText(tr("rule_id"))
        self._in_id.setToolTip("Unique identifier for this rule")
        self._in_id.returnPressed.connect(self._on_add_clicked)

        self._in_priority = QSpinBox()
        self._in_priority.setRange(0, 999)
        self._in_priority.setToolTip("Higher priority rules fire first")
        
        self._in_target = QLineEdit()
        self._in_target.setPlaceholderText(tr("placeholder_target"))
        self._in_target.setToolTip("Entity ID this rule applies to ('*' for all)")
        self._in_target.returnPressed.connect(self._on_add_clicked)
        
        self._add_btn = QPushButton(f"{tr('add')} +")
        self._add_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self._add_btn.setToolTip("Add this rule to the universe (Enter)")
        self._add_btn.clicked.connect(self._on_add_clicked)

        input_group.addWidget(self._in_id, 2)
        input_group.addWidget(QLabel(tr("priority")))
        input_group.addWidget(self._in_priority, 1)
        input_group.addWidget(self._in_target, 2)
        input_group.addWidget(self._add_btn, 1)
        layout.addLayout(input_group)

        # Rules Table
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels([
            tr("rule_id"), tr("priority"), tr("target")
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.currentCellChanged.connect(lambda r, c, pr, pc: self._on_row_selected())
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, 2) # Give more space to main table

        # Bottom Panels: Conditions and Actions
        bottom_layout = QHBoxLayout()
        
        # --- Conditions ---
        self._cond_group = QGroupBox(tr("conditions"))
        cond_layout = QVBoxLayout(self._cond_group)
        
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel(tr("operator")))
        self._operator_combo = QComboBox()
        self._operator_combo.addItems([tr("and"), tr("or")])
        self._operator_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        op_row.addWidget(self._operator_combo)
        op_row.addStretch()
        cond_layout.addLayout(op_row)
        
        self._cond_table = QTableWidget(0, 3)
        self._cond_table.setHorizontalHeaderLabels([tr("stat"), tr("comparator"), tr("value")])
        self._cond_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._cond_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        cond_layout.addWidget(self._cond_table)
        
        cond_btns = QHBoxLayout()
        self._add_cond_btn = QPushButton(f"{tr('add_condition')} +")
        self._rem_cond_btn = QPushButton(tr("remove"))
        cond_btns.addWidget(self._add_cond_btn)
        cond_btns.addWidget(self._rem_cond_btn)
        cond_layout.addLayout(cond_btns)
        
        self._add_cond_btn.clicked.connect(self._on_add_cond_row)
        self._rem_cond_btn.clicked.connect(self._on_rem_cond_row)
        
        bottom_layout.addWidget(self._cond_group)

        # --- Actions ---
        self._act_group = QGroupBox(tr("actions"))
        act_layout = QVBoxLayout(self._act_group)
        
        self._act_table = QTableWidget(0, 4)
        self._act_table.setHorizontalHeaderLabels([tr("type"), tr("target"), tr("stat"), tr("value")])
        self._act_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._act_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        act_layout.addWidget(self._act_table)
        
        act_btns = QHBoxLayout()
        self._add_act_btn = QPushButton(f"{tr('add_action')} +")
        self._rem_act_btn = QPushButton(tr("remove"))
        act_btns.addWidget(self._add_act_btn)
        act_btns.addWidget(self._rem_act_btn)
        act_layout.addLayout(act_btns)
        
        self._add_act_btn.clicked.connect(self._on_add_act_row)
        self._rem_act_btn.clicked.connect(self._on_rem_act_row)
        
        bottom_layout.addWidget(self._act_group)
        
        layout.addLayout(bottom_layout, 3)

        # Global delete
        self._del_rule_btn = QPushButton(tr("delete"))
        self._del_rule_btn.setToolTip(f"{tr('delete_rule_tooltip') if 'delete_rule_tooltip' in tr('ready') else 'Remove selected rules'} (Del)")
        self._del_rule_btn.clicked.connect(self._on_delete_rule)
        layout.addWidget(self._del_rule_btn)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        self._header.setText(f"<b>{tr('tab_rules')}</b>")
        self._add_btn.setText(f"{tr('add')} +")
        self._del_rule_btn.setText(tr("delete"))
        
        self._in_id.setPlaceholderText(tr("rule_id"))
        self._in_target.setPlaceholderText(tr("placeholder_target"))
        
        self._table.setHorizontalHeaderLabels([tr("rule_id"), tr("priority"), tr("target")])
        self._cond_group.setTitle(tr("conditions"))
        self._act_group.setTitle(tr("actions"))
        self._add_cond_btn.setText(f"{tr('add_condition')} +")
        self._add_act_btn.setText(f"{tr('add_action')} +")
        self._rem_cond_btn.setText(tr("remove"))
        self._rem_act_btn.setText(tr("remove"))

    @Slot(list)
    def populate(self, rules: list[dict]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._rules_data = [dict(r) for r in rules]
        
        for r in self._rules_data:
            self._add_rule_row(r)
            
        self._table.blockSignals(False)
        if self._table.rowCount() > 0:
            self._table.setCurrentCell(0, 0)

    @Slot(list)
    def set_stat_definitions(self, stat_defs: list[dict]) -> None:
        self._stat_defs = stat_defs
        # If a rule is selected, we might want to refresh its combos, but let's keep it simple

    def collect_data(self) -> list[dict]:
        self._sync_subtables_from_ui()
        # Update basic fields from main table
        for r in range(self._table.rowCount()):
            if r < len(self._rules_data):
                self._rules_data[r]["rule_id"] = self._table.item(r, 0).text().strip()
                self._rules_data[r]["priority"] = int(self._table.item(r, 1).text().strip() or 0)
                self._rules_data[r]["target_entity"] = self._table.item(r, 2).text().strip()
        return self._rules_data

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    def _add_rule_row(self, rule: dict) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        
        it_id = QTableWidgetItem(rule.get("rule_id", ""))
        it_id.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogDetailedView))
        it_prio = QTableWidgetItem(str(rule.get("priority", 0)))
        it_target = QTableWidgetItem(rule.get("target_entity", "*"))
        
        self._table.setItem(row, 0, it_id)
        self._table.setItem(row, 1, it_prio)
        self._table.setItem(row, 2, it_target)

    @Slot()
    def _on_add_clicked(self) -> None:
        rid = self._in_id.text().strip() or f"rule_{uuid.uuid4().hex[:6]}"
        prio = self._in_priority.value()
        target = self._in_target.text().strip() or "*"
        
        new_rule = {
            "rule_id": rid,
            "priority": prio,
            "target_entity": target,
            "conditions": {"operator": "AND", "clauses": []},
            "actions": []
        }
        self._rules_data.append(new_rule)
        self._add_rule_row(new_rule)
        self._in_id.clear()
        self._in_target.clear()
        self._table.setCurrentCell(self._table.rowCount()-1, 0)
        self.changed.emit()

    @Slot()
    def _on_row_selected(self) -> None:
        self._sync_subtables_from_ui()
        row = self._table.currentRow()
        self._selected_row = row
        
        self._cond_table.setRowCount(0)
        self._act_table.setRowCount(0)
        
        if row < 0 or row >= len(self._rules_data):
            return
            
        rule = self._rules_data[row]
        
        # Operator
        conds = rule.get("conditions", {})
        op = str(conds.get("operator", "AND")).upper()
        self._operator_combo.setCurrentIndex(0 if op == "AND" else 1)
        
        for clause in conds.get("clauses", []):
            self._add_cond_table_row(clause)
            
        for action in rule.get("actions", []):
            self._add_act_table_row(action)

    def _add_cond_table_row(self, clause: dict) -> None:
        r = self._cond_table.rowCount()
        self._cond_table.insertRow(r)
        
        # Stat Dropdown (The FIX for Task 10)
        stat_combo = QComboBox()
        stat_names = [s["name"] for s in self._stat_defs]
        val_stat = clause.get("stat", "")
        if val_stat and val_stat not in stat_names: stat_names.insert(0, val_stat)
        stat_combo.addItems(stat_names)
        stat_combo.setCurrentText(val_stat)
        self._cond_table.setCellWidget(r, 0, stat_combo)
        stat_combo.currentTextChanged.connect(lambda _: self.changed.emit())
        
        # Comparator
        comp_combo = QComboBox()
        comp_combo.addItems(self._COMPARATORS)
        comp_combo.setCurrentText(clause.get("comparator", "=="))
        self._cond_table.setCellWidget(r, 1, comp_combo)
        comp_combo.currentTextChanged.connect(lambda _: self.changed.emit())
        
        # Value
        it_val = QTableWidgetItem(str(clause.get("value", "")))
        self._cond_table.setItem(r, 2, it_val)

    def _add_act_table_row(self, action: dict) -> None:
        r = self._act_table.rowCount()
        self._act_table.insertRow(r)
        
        # Type
        type_combo = QComboBox()
        for atype in self._ACTION_TYPES:
            type_combo.addItem(tr(f"action_{atype}"), atype)
        type_combo.setCurrentIndex(max(0, type_combo.findData(action.get("type", "stat_change"))))
        self._act_table.setCellWidget(r, 0, type_combo)
        type_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        
        # Target
        it_target = QTableWidgetItem(action.get("target", ""))
        self._act_table.setItem(r, 1, it_target)
        
        # Stat (FIX)
        stat_combo = QComboBox()
        stat_names = [s["name"] for s in self._stat_defs]
        val_stat = action.get("stat", "")
        if val_stat and val_stat not in stat_names: stat_names.insert(0, val_stat)
        stat_combo.addItems(stat_names)
        stat_combo.setCurrentText(val_stat)
        self._act_table.setCellWidget(r, 2, stat_combo)
        stat_combo.currentTextChanged.connect(lambda _: self.changed.emit())
        
        # Value
        it_val = QTableWidgetItem(str(action.get("delta", action.get("value", ""))))
        self._act_table.setItem(r, 3, it_val)

    def _sync_subtables_from_ui(self) -> None:
        if self._selected_row < 0 or self._selected_row >= len(self._rules_data):
            return
            
        # Conditions
        clauses = []
        for r in range(self._cond_table.rowCount()):
            stat_w = self._cond_table.cellWidget(r, 0)
            comp_w = self._cond_table.cellWidget(r, 1)
            val_it = self._cond_table.item(r, 2)
            
            if isinstance(stat_w, QComboBox) and isinstance(comp_w, QComboBox) and val_it:
                clauses.append({
                    "stat": stat_w.currentText(),
                    "comparator": comp_w.currentText(),
                    "value": val_it.text().strip()
                })
        
        # Actions
        actions = []
        for r in range(self._act_table.rowCount()):
            type_w = self._act_table.cellWidget(r, 0)
            target_it = self._act_table.item(r, 1)
            stat_w = self._act_table.cellWidget(r, 2)
            val_it = self._act_table.item(r, 3)
            
            if isinstance(type_w, QComboBox) and target_it and isinstance(stat_w, QComboBox) and val_it:
                atype = type_w.currentData()
                act = {
                    "type": atype,
                    "target": target_it.text().strip(),
                    "stat": stat_w.currentText()
                }
                v = val_it.text().strip()
                if atype == "stat_change": act["delta"] = float(v) if v else 0.0
                else: act["value"] = v
                actions.append(act)
                
        self._rules_data[self._selected_row]["conditions"] = {
            "operator": "AND" if self._operator_combo.currentIndex() == 0 else "OR",
            "clauses": clauses
        }
        self._rules_data[self._selected_row]["actions"] = actions

    @Slot()
    def _on_add_cond_row(self) -> None:
        self._add_cond_table_row({})
        self.changed.emit()

    @Slot()
    def _on_rem_cond_row(self) -> None:
        r = self._cond_table.currentRow()
        if r >= 0: self._cond_table.removeRow(r)
        self.changed.emit()

    @Slot()
    def _on_add_act_row(self) -> None:
        self._add_act_table_row({})
        self.changed.emit()

    @Slot()
    def _on_rem_act_row(self) -> None:
        r = self._act_table.currentRow()
        if r >= 0: self._act_table.removeRow(r)
        self.changed.emit()

    @Slot()
    def _on_delete_rule(self) -> None:
        indices = self._table.selectionModel().selectedRows()
        rows = sorted([i.row() for i in indices], reverse=True) if indices else [self._table.currentRow()]
        for r in rows:
            if 0 <= r < len(self._rules_data):
                del self._rules_data[r]
                self._table.removeRow(r)
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._table.signalsBlocked():
            return

        selected = self._table.selectedItems()
        if len(selected) > 1 and item in selected:
            self._table.blockSignals(True)
            new_text = item.text()
            col = item.column()
            for other in selected:
                if other != item and other.column() == col:
                    other.setText(new_text)
            self._table.blockSignals(False)

        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete:
            selected_items = self._table.selectedItems()
            if not selected_items:
                return

            rows = set()
            for item in selected_items:
                rows.add(item.row())

            all_cols_selected = True
            for r in rows:
                for c in range(self._table.columnCount()):
                    if self._table.item(r, c) not in selected_items:
                        all_cols_selected = False
                        break
                if not all_cols_selected: break

            if all_cols_selected:
                self._on_delete_rule()
            else:
                self._table.blockSignals(True)
                for item in selected_items:
                    item.setText("")
                self._table.blockSignals(False)
                self.changed.emit()
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self._in_id.hasFocus() or self._in_target.hasFocus():
                self._on_add_clicked()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)
