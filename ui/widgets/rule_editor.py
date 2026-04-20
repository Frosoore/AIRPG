"""
ui/widgets/rule_editor.py

Visual JSON rule builder for the Creator Studio.

Exposes AND/OR condition trees and action rows as form widgets.
No raw JSON is ever shown to the user.

THREADING RULE: No I/O here.  Data in via populate() (DbWorker signal);
data out via collect_data() (called before DbWorker save task).
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class RuleEditorWidget(QWidget):
    """Visual rule builder for the Creator Studio Rules tab.

    Renders conditions as an AND/OR tree of clause rows and actions as
    a list of typed action rows.  No raw JSON shown.

    populate() receives list[dict] from DbWorker; collect_data() returns
    list[dict] to be written by DbWorker - no I/O in this widget.
    """

    _COMPARATORS: list[str] = ["<=", ">=", "==", "!=", "<", ">"]
    _ACTION_TYPES: list[str] = ["stat_change", "stat_set", "trigger_event", "set_status"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rules_data: list[dict] = []
        self._condition_rows: list[_ConditionRow] = []
        self._action_rows: list[_ActionRow] = []
        self._selected_row: int = -1  # Row whose data is currently in the form
        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # Left - rule list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("<b>Rules</b>"))

        self._rule_list = QListWidget()
        self._rule_list.currentRowChanged.connect(self._on_rule_selected)
        left_layout.addWidget(self._rule_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add")
        del_btn = QPushButton("Delete")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        left_layout.addLayout(btn_row)

        add_btn.clicked.connect(self._on_add_rule)
        del_btn.clicked.connect(self._on_delete_rule)

        # Right - rule form in a scroll area
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_widget = QWidget()
        self._right_layout = QVBoxLayout(right_widget)
        right_scroll.setWidget(right_widget)

        # Basic fields
        basic_form = QFormLayout()
        self._id_input = QLineEdit()
        self._priority_spin = QSpinBox()
        self._priority_spin.setRange(0, 999)
        self._target_input = QLineEdit()
        self._target_input.setPlaceholderText("entity_id or *")
        basic_form.addRow("Rule ID:", self._id_input)
        basic_form.addRow("Priority:", self._priority_spin)
        basic_form.addRow("Target Entity:", self._target_input)
        self._right_layout.addLayout(basic_form)

        # Conditions group
        self._conditions_group = QGroupBox("Conditions")
        self._conditions_layout = QVBoxLayout(self._conditions_group)

        cond_top = QHBoxLayout()
        cond_top.addWidget(QLabel("Operator:"))
        self._operator_combo = QComboBox()
        self._operator_combo.addItems(["AND", "OR"])
        cond_top.addWidget(self._operator_combo)
        cond_top.addStretch()
        self._conditions_layout.addLayout(cond_top)

        self._clauses_container = QVBoxLayout()
        self._conditions_layout.addLayout(self._clauses_container)

        add_clause_btn = QPushButton("Add Condition")
        add_clause_btn.clicked.connect(self._on_add_condition)
        self._conditions_layout.addWidget(add_clause_btn)
        self._right_layout.addWidget(self._conditions_group)

        # Actions group
        self._actions_group = QGroupBox("Actions")
        self._actions_layout = QVBoxLayout(self._actions_group)

        self._actions_container = QVBoxLayout()
        self._actions_layout.addLayout(self._actions_container)

        add_action_btn = QPushButton("Add Action")
        add_action_btn.clicked.connect(self._on_add_action)
        self._actions_layout.addWidget(add_action_btn)
        self._right_layout.addWidget(self._actions_group)
        self._right_layout.addStretch()

        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setSizes([200, 500])
        layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @Slot(list)
    def populate(self, rules: list[dict]) -> None:
        """Populate the rule list from a list of rule dicts.

        Called by DbWorker.rules_loaded signal.

        Args:
            rules: List of rule dicts in canonical Rules Engine schema.
        """
        self._selected_row = -1
        self._rules_data = rules
        self._rule_list.clear()
        for rule in rules:
            self._rule_list.addItem(
                f"[{rule.get('priority', 0)}] {rule.get('rule_id', '?')}"
            )
        if rules:
            self._rule_list.setCurrentRow(0)

    def collect_data(self) -> list[dict]:
        """Return the current form state as a list of rule dicts.

        Called by CreatorStudioView.on_save_clicked().  No I/O.

        Returns:
            List of rule dicts in canonical Rules Engine JSON schema.
        """
        # Phase 7: Absolute Persistence Protocol - Sync and refresh UI label
        self._sync_current_form()
        return list(self._rules_data)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_rule_selected(self, row: int) -> None:
        """Flush the previous rule's form data, then load the new selection."""
        # Flush before advancing _selected_row so sync targets the previous slot
        self._sync_current_form()
        self._selected_row = row

        if row < 0 or row >= len(self._rules_data):
            return
        rule = self._rules_data[row]

        self._id_input.setText(rule.get("rule_id", ""))
        self._priority_spin.setValue(int(rule.get("priority", 0)))
        self._target_input.setText(rule.get("target_entity", "*"))

        # Conditions
        self._clear_condition_rows()
        conditions = rule.get("conditions", {})
        operator = conditions.get("operator", "AND")
        idx = self._operator_combo.findText(operator)
        self._operator_combo.setCurrentIndex(max(0, idx))
        for clause in conditions.get("clauses", []):
            if "stat" in clause:
                self._add_condition_row(
                    clause.get("stat", ""),
                    clause.get("comparator", "=="),
                    str(clause.get("value", "")),
                )

        # Actions
        self._clear_action_rows()
        for action in rule.get("actions", []):
            self._add_action_row(
                action.get("type", "stat_change"),
                action.get("target", ""),
                action.get("stat", ""),
                str(action.get("delta", action.get("value", ""))),
            )

    @Slot()
    def _on_add_rule(self) -> None:
        """Flush current form then add a blank rule."""
        self._sync_current_form()
        new_rule = {
            "rule_id": f"rule_{uuid.uuid4().hex[:6]}",
            "priority": len(self._rules_data),
            "target_entity": "*",
            "conditions": {"operator": "AND", "clauses": []},
            "actions": [],
        }
        self._rules_data.append(new_rule)
        self._rule_list.addItem(
            f"[{new_rule['priority']}] {new_rule['rule_id']}"
        )
        self._rule_list.setCurrentRow(len(self._rules_data) - 1)

    @Slot()
    def _on_delete_rule(self) -> None:
        """Delete the currently selected rule."""
        row = self._selected_row
        if row < 0 or row >= len(self._rules_data):
            return

        # 1. Block signals to prevent premature UI refreshes
        self._rule_list.blockSignals(True)

        # 2. Delete data and visual item
        del self._rules_data[row]
        self._rule_list.takeItem(row)

        # 3. Reset local selection BEFORE unblocking
        self._selected_row = -1

        # 4. Unblock signals
        self._rule_list.blockSignals(False)

        # 5. Force selection of the new item at the same position (or last)
        new_row = self._rule_list.currentRow()
        if new_row >= 0:
            self._on_rule_selected(new_row)
        else:
            # Clear form if no rules left
            self._id_input.clear()
            self._priority_spin.setValue(0)
            self._target_input.clear()
            self._clear_condition_rows()
            self._clear_action_rows()

    @Slot()
    def _on_add_condition(self) -> None:
        self._add_condition_row("", "==", "")

    @Slot()
    def _on_add_action(self) -> None:
        self._add_action_row("stat_change", "", "", "")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _add_condition_row(
        self, stat: str, comparator: str, value: str
    ) -> "_ConditionRow":
        row = _ConditionRow(stat, comparator, value, self._COMPARATORS)
        row.remove_requested.connect(lambda r=row: self._remove_condition_row(r))
        self._condition_rows.append(row)
        self._clauses_container.addWidget(row)
        return row

    def _remove_condition_row(self, row: "_ConditionRow") -> None:
        if row in self._condition_rows:
            self._condition_rows.remove(row)
            row.deleteLater()

    def _clear_condition_rows(self) -> None:
        for row in list(self._condition_rows):
            row.deleteLater()
        self._condition_rows.clear()

    def _add_action_row(
        self, action_type: str, target: str, stat: str, value: str
    ) -> "_ActionRow":
        row = _ActionRow(action_type, target, stat, value, self._ACTION_TYPES)
        row.remove_requested.connect(lambda r=row: self._remove_action_row(r))
        self._action_rows.append(row)
        self._actions_container.addWidget(row)
        return row

    def _remove_action_row(self, row: "_ActionRow") -> None:
        if row in self._action_rows:
            self._action_rows.remove(row)
            row.deleteLater()

    def _clear_action_rows(self) -> None:
        for row in list(self._action_rows):
            row.deleteLater()
        self._action_rows.clear()

    def _sync_current_form(self) -> None:
        """Write form values back to _rules_data for the row being edited.

        Uses _selected_row (the slot whose data is displayed) rather than
        currentRow(), which has already advanced to the new selection by the
        time _on_rule_selected fires.
        """
        row_idx = self._selected_row
        if row_idx < 0 or row_idx >= len(self._rules_data):
            return

        clauses = []
        for cond_row in self._condition_rows:
            clause = cond_row.to_dict()
            if clause["stat"]:
                clauses.append(clause)

        actions = []
        for action_row in self._action_rows:
            action = action_row.to_dict()
            if action.get("stat") or action.get("type") == "trigger_event":
                actions.append(action)

        rule_id = self._id_input.text().strip()
        priority = self._priority_spin.value()

        self._rules_data[row_idx] = {
            "rule_id": rule_id,
            "priority": priority,
            "target_entity": self._target_input.text().strip() or "*",
            "conditions": {
                "operator": self._operator_combo.currentText(),
                "clauses": clauses,
            },
            "actions": actions,
        }

        # Phase 7: Refresh the list item text immediately
        item = self._rule_list.item(row_idx)
        if item:
            item.setText(f"[{priority}] {rule_id or '?'}")


# ---------------------------------------------------------------------------
# Row sub-widgets
# ---------------------------------------------------------------------------

class _ConditionRow(QWidget):
    """A single condition clause row: stat / comparator / value / x button."""

    from PySide6.QtCore import Signal
    remove_requested = Signal()

    def __init__(
        self,
        stat: str,
        comparator: str,
        value: str,
        comparators: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self._stat = QLineEdit(stat)
        self._stat.setPlaceholderText("stat key")
        self._comparator = QComboBox()
        self._comparator.addItems(comparators)
        idx = self._comparator.findText(comparator)
        self._comparator.setCurrentIndex(max(0, idx))
        self._value = QLineEdit(value)
        self._value.setPlaceholderText("value")
        remove_btn = QPushButton("x")
        remove_btn.setFixedWidth(28)
        remove_btn.clicked.connect(self.remove_requested)

        layout.addWidget(self._stat, 2)
        layout.addWidget(self._comparator, 1)
        layout.addWidget(self._value, 2)
        layout.addWidget(remove_btn)

    def to_dict(self) -> dict:
        """Return clause dict."""
        return {
            "stat": self._stat.text().strip(),
            "comparator": self._comparator.currentText(),
            "value": self._value.text().strip(),
        }


class _ActionRow(QWidget):
    """A single action row: type / target / stat / delta-value / x button."""

    from PySide6.QtCore import Signal
    remove_requested = Signal()

    def __init__(
        self,
        action_type: str,
        target: str,
        stat: str,
        value: str,
        action_types: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self._type_combo = QComboBox()
        self._type_combo.addItems(action_types)
        idx = self._type_combo.findText(action_type)
        self._type_combo.setCurrentIndex(max(0, idx))
        self._target = QLineEdit(target)
        self._target.setPlaceholderText("target entity")
        self._stat = QLineEdit(stat)
        self._stat.setPlaceholderText("stat key")
        self._value = QLineEdit(value)
        self._value.setPlaceholderText("delta / value")
        remove_btn = QPushButton("x")
        remove_btn.setFixedWidth(28)
        remove_btn.clicked.connect(self.remove_requested)

        layout.addWidget(self._type_combo, 2)
        layout.addWidget(self._target, 2)
        layout.addWidget(self._stat, 2)
        layout.addWidget(self._value, 2)
        layout.addWidget(remove_btn)

    def to_dict(self) -> dict:
        """Return action dict."""
        action_type = self._type_combo.currentText()
        d: dict = {
            "type": action_type,
            "target": self._target.text().strip(),
            "stat": self._stat.text().strip(),
        }
        raw_val = self._value.text().strip()
        if action_type == "stat_change":
            try:
                d["delta"] = float(raw_val) if raw_val else 0.0
            except ValueError:
                d["delta"] = 0.0
        else:
            d["value"] = raw_val
        return d
