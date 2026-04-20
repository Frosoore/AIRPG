"""
ui/widgets/entity_editor.py

Visual entity and stat editor for the Creator Studio.

Users can add/delete entities and define their initial stats via a
table widget - no raw JSON is ever shown.

THREADING RULE: No I/O here.  Data is received via populate() (called
from DbWorker signal) and returned via collect_data() to be written by
DbWorker.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class EntityEditorWidget(QWidget):
    """Visual entity list and stat editor for the Creator Studio Entities tab.

    Users see a list of entities on the left and a form on the right.
    All data in/out is via Python dicts - no SQL.

    The widget owns no I/O; populate() is called by a DbWorker signal and
    collect_data() is called by CreatorStudioView before a save DbWorker task.
    """

    _ENTITY_TYPES: list[str] = ["player", "npc", "faction", "world"]

    populate_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entities_data: list[dict] = []
        self._stat_defs: list[dict] = []
        self._selected_row: int = -1  # Row whose data is currently in the form
        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # Left panel - entity list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("<b>Entities</b>"))

        self._entity_list = QListWidget()
        self._entity_list.currentRowChanged.connect(self._on_entity_selected)
        left_layout.addWidget(self._entity_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add")
        del_btn = QPushButton("Delete")
        
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        left_layout.addLayout(btn_row)
        
        self._populate_btn = QPushButton("Populate ✨")
        self._populate_btn.setToolTip("Auto-generate NPCs and factions from lore using AI")
        left_layout.addWidget(self._populate_btn)
        
        self._progress = QProgressBar()
        self._progress.setRange(0, 0) # Indeterminate mode
        self._progress.setVisible(False)
        left_layout.addWidget(self._progress)

        add_btn.clicked.connect(self._on_add_entity)
        del_btn.clicked.connect(self._on_delete_entity)
        self._populate_btn.clicked.connect(self.populate_requested.emit)

        # Right panel - entity form
        right = QWidget()
        right_layout = QFormLayout(right)

        self._id_input = QLineEdit()
        self._id_input.setPlaceholderText("e.g. player1")
        self._type_combo = QComboBox()
        self._type_combo.addItems(self._ENTITY_TYPES)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g. Aria")
        self._desc_input = QLineEdit()
        self._desc_input.setPlaceholderText("e.g. A mysterious traveler.")

        right_layout.addRow("Entity ID:", self._id_input)
        right_layout.addRow("Type:", self._type_combo)
        right_layout.addRow("Name:", self._name_input)
        right_layout.addRow("Description:", self._desc_input)

        stats_group = QGroupBox("Initial Stats")
        stats_layout = QVBoxLayout(stats_group)

        self._stats_table = QTableWidget(0, 2)
        self._stats_table.setHorizontalHeaderLabels(["Stat Name", "Initial Value"])
        self._stats_table.horizontalHeader().setStretchLastSection(True)
        stats_layout.addWidget(self._stats_table)

        stat_btn_row = QHBoxLayout()
        add_stat_btn = QPushButton("Add Stat")
        rem_stat_btn = QPushButton("Remove Stat")
        stat_btn_row.addWidget(add_stat_btn)
        stat_btn_row.addWidget(rem_stat_btn)
        stats_layout.addLayout(stat_btn_row)

        right_layout.addRow(stats_group)

        add_stat_btn.clicked.connect(self._on_add_stat_row)
        rem_stat_btn.clicked.connect(self._on_remove_stat_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([200, 400])
        layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @Slot(list)
    def populate(self, entities: list[dict]) -> None:
        """Populate the entity list from a list of entity dicts."""
        self._selected_row = -1
        self._entities_data = entities
        self._entity_list.clear()
        for entity in entities:
            self._entity_list.addItem(
                f"{entity.get('name', '?')} ({entity.get('entity_id', '?')})"
            )
        if entities:
            self._entity_list.setCurrentRow(0)

    @Slot(list)
    def set_stat_definitions(self, stat_defs: list[dict]) -> None:
        """Update the list of allowed stat definitions."""
        self._stat_defs = stat_defs
        # If an entity is currently selected, we should ideally refresh its table
        # but _on_entity_selected is usually called after this during a load.

    def add_entities(self, new_entities: list[dict]) -> None:
        """Append multiple entities to the current list without clearing."""
        self._sync_current_form()
        for ent in new_entities:
            self._entities_data.append(ent)
            self._entity_list.addItem(
                f"{ent.get('name', '?')} ({ent.get('entity_id', '?')})"
            )
        if new_entities:
            self._entity_list.setCurrentRow(len(self._entities_data) - 1)

    def set_populate_enabled(self, enabled: bool) -> None:
        """Enable or disable the AI populate button (e.g. during generation)."""
        self._populate_btn.setEnabled(enabled)
        self._progress.setVisible(not enabled)
        if enabled:
            self._populate_btn.setText("Populate ✨")
        else:
            self._populate_btn.setText("Generating...")

    def collect_data(self) -> list[dict]:
        """Return the current form state as a list of entity dicts."""
        self._sync_current_form()
        return list(self._entities_data)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_entity_selected(self, row: int) -> None:
        """Flush the previous entity's form data, then load the new selection."""
        self._sync_current_form()
        self._selected_row = row

        if row < 0 or row >= len(self._entities_data):
            return
        entity = self._entities_data[row]

        self._id_input.setText(entity.get("entity_id", ""))
        type_idx = self._type_combo.findText(entity.get("entity_type", "npc"))
        self._type_combo.setCurrentIndex(max(0, type_idx))
        self._name_input.setText(entity.get("name", ""))
        self._desc_input.setText(entity.get("description", ""))

        stats = entity.get("stats", {})
        self._stats_table.setRowCount(0)
        for key, value in stats.items():
            self._add_stat_row_with_data(key, value)

    @Slot()
    def _on_add_entity(self) -> None:
        """Flush current form then add a new blank entity."""
        self._sync_current_form()
        new_entity: dict = {
            "entity_id": f"entity_{len(self._entities_data) + 1}",
            "entity_type": "npc",
            "name": "New Entity",
            "description": "",
            "stats": {},
        }
        self._entities_data.append(new_entity)
        self._entity_list.addItem(
            f"{new_entity['name']} ({new_entity['entity_id']})"
        )
        self._entity_list.setCurrentRow(len(self._entities_data) - 1)

    @Slot()
    def _on_delete_entity(self) -> None:
        """Delete the currently selected entity."""
        row = self._selected_row
        if row < 0 or row >= len(self._entities_data):
            return

        # 1. Block signals to prevent premature UI refreshes
        self._entity_list.blockSignals(True)

        # 2. Delete data and visual item
        del self._entities_data[row]
        self._entity_list.takeItem(row)

        # 3. Reset local selection BEFORE unblocking
        self._selected_row = -1

        # 4. Unblock signals
        self._entity_list.blockSignals(False)

        # 5. Force selection of the new item at the same position (or last)
        new_row = self._entity_list.currentRow()
        if new_row >= 0:
            self._on_entity_selected(new_row)
        else:
            # Clear form if no entities left
            self._id_input.clear()
            self._name_input.clear()
            self._desc_input.clear()
            self._stats_table.setRowCount(0)

    @Slot()
    def _on_add_stat_row(self) -> None:
        """Append a blank stat row using the first available definition."""
        if not self._stat_defs:
            # Do nothing if no stats are defined in the universe
            return

        first_stat = self._stat_defs[0]["name"]
        self._add_stat_row_with_data(first_stat, "")

    @Slot()
    def _on_remove_stat_row(self) -> None:
        """Remove the currently selected stat row."""
        row = self._stats_table.currentRow()
        if row >= 0:
            self._stats_table.removeRow(row)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _add_stat_row_with_data(self, key: str, value: str) -> None:
        if not self._stat_defs:
            return

        row_idx = self._stats_table.rowCount()
        self._stats_table.insertRow(row_idx)

        # Stat Key ComboBox - NOT editable, strictly from definitions
        key_combo = QComboBox()
        key_combo.setEditable(False)
        stat_names = [s["name"] for s in self._stat_defs]
        
        # Include the key only if it matches a definition or for initial loading
        if key and key not in stat_names:
            # If we load an old save with a deleted stat, we show it but user
            # will have to change it to a valid one to stay consistent.
            stat_names.insert(0, key)
        
        key_combo.addItems(stat_names)
        key_combo.setCurrentText(key)
        self._stats_table.setCellWidget(row_idx, 0, key_combo)

        # Update value widget when key changes
        key_combo.currentTextChanged.connect(self._on_stat_key_changed)
        
        self._update_value_widget(row_idx, key, value)

    @Slot(str)
    def _on_stat_key_changed(self, stat_name: str) -> None:
        # Find which row's combo box sent the signal
        combo = self.sender()
        if not isinstance(combo, QComboBox):
            return
        
        # Find the row of this widget
        for r in range(self._stats_table.rowCount()):
            if self._stats_table.cellWidget(r, 0) == combo:
                self._update_value_widget(r, stat_name)
                break

    def _update_value_widget(self, row: int, stat_name: str, initial_value: str = None) -> None:
        # Find definition
        sdef = next((s for s in self._stat_defs if s["name"] == stat_name), None)
        
        if not sdef:
            # Fallback
            edit = QLineEdit(str(initial_value or ""))
            self._stats_table.setCellWidget(row, 1, edit)
            return

        vtype = sdef.get("value_type", "numeric")
        params = sdef.get("parameters", {})

        if vtype == "numeric":
            spin = QDoubleSpinBox()
            spin.setRange(float(params.get("min", -999999)), float(params.get("max", 999999)))
            try:
                val = float(initial_value) if initial_value not in (None, "") else float(params.get("min", 0))
                spin.setValue(val)
            except (ValueError, TypeError):
                spin.setValue(float(params.get("min", 0)))
            self._stats_table.setCellWidget(row, 1, spin)
        elif vtype == "categorical":
            combo = QComboBox()
            options = params.get("options", [])
            combo.addItems(options)
            if initial_value in options:
                combo.setCurrentText(initial_value)
            self._stats_table.setCellWidget(row, 1, combo)
        else:
            edit = QLineEdit(str(initial_value or ""))
            self._stats_table.setCellWidget(row, 1, edit)

    def _sync_current_form(self) -> None:
        """Write form values back into _entities_data for the row being edited."""
        row = self._selected_row
        if row < 0 or row >= len(self._entities_data):
            return

        stats: dict[str, str] = {}
        for r in range(self._stats_table.rowCount()):
            # Key
            key_widget = self._stats_table.cellWidget(r, 0)
            if isinstance(key_widget, QComboBox):
                key = key_widget.currentText().strip()
            else:
                key_item = self._stats_table.item(r, 0)
                key = key_item.text().strip() if key_item else ""

            # Value
            val_widget = self._stats_table.cellWidget(r, 1)
            if isinstance(val_widget, QDoubleSpinBox):
                value = str(val_widget.value())
            elif isinstance(val_widget, QComboBox):
                value = val_widget.currentText()
            elif isinstance(val_widget, QLineEdit):
                value = val_widget.text().strip()
            else:
                val_item = self._stats_table.item(r, 1)
                value = val_item.text().strip() if val_item else ""

            if key:
                stats[key] = value

        entity_id = self._id_input.text().strip()
        name = self._name_input.text().strip()
        description = self._desc_input.text().strip()

        self._entities_data[row] = {
            "entity_id": entity_id,
            "entity_type": self._type_combo.currentText(),
            "name": name,
            "description": description,
            "stats": stats,
        }

        # Refresh the list item text immediately
        item = self._entity_list.item(row)
        if item:
            item.setText(f"{name or '?'} ({entity_id or '?'})")
