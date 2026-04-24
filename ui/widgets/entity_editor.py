"""
ui/widgets/entity_editor.py

Visual entity and stat editor for the Creator Studio.
Uses a spreadsheet-like grid for direct entity management.
"""

from __future__ import annotations

import uuid
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
    QMenu,
    QInputDialog,
)
from core.localization import tr


class EntityEditorWidget(QWidget):
    """Spreadsheet-like entity builder for the Creator Studio."""

    # Canonical keys
    _ENTITY_TYPES: list[str] = ["player", "npc", "faction", "world"]

    # Emits (mode: str, custom_text: str|None)
    # mode is "auto" (from lore) or "custom"
    populate_requested = Signal(str, object)
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entities_data: list[dict] = []
        self._stat_defs: list[dict] = []
        self._selected_row: int = -1
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # --- LEFT: ENTITY TABLE ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        header_row = QHBoxLayout()
        self._header = QLabel(f"<b>{tr('tab_entities')}</b>")
        header_row.addWidget(self._header)
        header_row.addStretch()
        
        # Dual Populate Menu
        self._populate_btn = QPushButton(f"{tr('populate')} ✨")
        self._populate_menu = QMenu(self)
        self._pop_auto_action = self._populate_menu.addAction(tr("populate_tooltip") or "Generate from Lore/Stats")
        self._pop_custom_action = self._populate_menu.addAction("Populate from Custom Text...")
        self._populate_btn.setMenu(self._populate_menu)
        
        self._pop_auto_action.triggered.connect(lambda: self.populate_requested.emit("auto", None))
        self._pop_custom_action.triggered.connect(self._on_custom_populate_clicked)
        
        header_row.addWidget(self._populate_btn)
        left_layout.addLayout(header_row)

        # Input Row (Write before Add)
        input_group = QHBoxLayout()
        self._in_id = QLineEdit()
        self._in_id.setPlaceholderText(tr("id"))
        self._in_type = QComboBox()
        for etype in self._ENTITY_TYPES:
            self._in_type.addItem(tr(f"entity_{etype}"), etype)
        self._in_name = QLineEdit()
        self._in_name.setPlaceholderText(tr("name"))
        
        self._add_btn = QPushButton(f"{tr('add')} +")
        self._add_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self._add_btn.clicked.connect(self._on_add_clicked)

        input_group.addWidget(self._in_id, 2)
        input_group.addWidget(self._in_type, 2)
        input_group.addWidget(self._in_name, 3)
        input_group.addWidget(self._add_btn, 1)
        left_layout.addLayout(input_group)

        # Entity Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels([
            tr("id"), tr("type"), tr("name"), tr("description")
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.setAlternatingRowColors(True)
        self._table.currentCellChanged.connect(lambda r, c, pr, pc: self._on_row_selected())
        self._table.itemChanged.connect(self._on_item_changed)
        left_layout.addWidget(self._table)

        self._del_btn = QPushButton(tr("delete"))
        self._del_btn.setToolTip(f"{tr('delete')} (Del)")
        self._del_btn.clicked.connect(self._on_delete_entity)
        left_layout.addWidget(self._del_btn)

        # --- RIGHT: STATS FOR SELECTED ENTITY ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        
        self._stats_group = QGroupBox(tr("initial_stats"))
        stats_layout = QVBoxLayout(self._stats_group)

        self._stats_table = QTableWidget(0, 2)
        self._stats_table.setHorizontalHeaderLabels([tr("stat_name"), tr("initial_value")])
        self._stats_table.horizontalHeader().setStretchLastSection(True)
        self._stats_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        stats_layout.addWidget(self._stats_table)

        stat_btn_row = QHBoxLayout()
        self._add_stat_btn = QPushButton(f"{tr('add_stat')} +")
        self._add_all_stats_btn = QPushButton("Add All Stats")
        self._rem_stat_btn = QPushButton(tr("remove_stat"))
        
        stat_btn_row.addWidget(self._add_stat_btn)
        stat_btn_row.addWidget(self._add_all_stats_btn)
        stat_btn_row.addWidget(self._rem_stat_btn)
        stats_layout.addLayout(stat_btn_row)

        self._add_stat_btn.clicked.connect(lambda: self._on_add_stat_row())
        self._add_all_stats_btn.clicked.connect(self._on_add_all_stats)
        self._rem_stat_btn.clicked.connect(self._on_remove_stat_row)

        right_layout.addWidget(self._stats_group)
        right_layout.addStretch()

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([500, 300])
        layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        self._header.setText(f"<b>{tr('tab_entities')}</b>")
        self._add_btn.setText(f"{tr('add')} +")
        self._del_btn.setText(tr("delete"))
        self._populate_btn.setText(f"{tr('populate')} ✨")
        
        self._in_id.setPlaceholderText(tr("id"))
        self._in_name.setPlaceholderText(tr("name"))
        
        self._table.setHorizontalHeaderLabels([
            tr("id"), tr("type"), tr("name"), tr("description")
        ])
        
        self._stats_group.setTitle(tr("initial_stats"))
        self._add_stat_btn.setText(f"{tr('add_stat')} +")
        self._rem_stat_btn.setText(tr("remove_stat"))
        self._stats_table.setHorizontalHeaderLabels([tr("stat_name"), tr("initial_value")])

    @Slot(list)
    def populate(self, entities: list[dict]) -> None:
        """Load entity data into the table."""
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._entities_data = [dict(e) for e in entities] # Deepish copy
        
        for ent in self._entities_data:
            self._add_entity_row(ent)
        
        self._table.blockSignals(False)
        if self._table.rowCount() > 0:
            self._table.setCurrentCell(0, 2) # Select name of first entity

    @Slot(list)
    def set_stat_definitions(self, stat_defs: list[dict]) -> None:
        self._stat_defs = stat_defs

    def collect_data(self) -> list[dict]:
        """Gather data from tables back into a list of dicts."""
        self._sync_stats_from_ui()
        # Ensure description and other fields in _entities_data are up to date from table
        for r in range(self._table.rowCount()):
            eid = self._table.item(r, 0).text().strip()
            # Find in data (matching by original position or ID)
            # For simplicity, we assume row index matches _entities_data index
            if r < len(self._entities_data):
                self._entities_data[r]["entity_id"] = eid
                self._entities_data[r]["name"] = self._table.item(r, 2).text().strip()
                self._entities_data[r]["description"] = self._table.item(r, 3).text().strip()
                # Type is set on add and kept in it_type itemData or text
        return self._entities_data

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    def _add_entity_row(self, ent: dict) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        
        it_id = QTableWidgetItem(ent.get("entity_id", ""))
        it_id.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogDetailedView))
        
        etype = ent.get("entity_type", "npc")
        it_type = QTableWidgetItem(tr(f"entity_{etype}"))
        it_type.setData(Qt.UserRole, etype)
        it_type.setFlags(it_type.flags() & ~Qt.ItemIsEditable)
        
        it_name = QTableWidgetItem(ent.get("name", ""))
        it_desc = QTableWidgetItem(ent.get("description", ""))
        
        self._table.setItem(row, 0, it_id)
        self._table.setItem(row, 1, it_type)
        self._table.setItem(row, 2, it_name)
        self._table.setItem(row, 3, it_desc)

    @Slot()
    def _on_add_clicked(self) -> None:
        """Create entity from input row."""
        eid = self._in_id.text().strip() or f"entity_{uuid.uuid4().hex[:6]}"
        name = self._in_name.text().strip() or tr("entity_npc").upper()
        etype = self._in_type.currentData()
        
        new_ent = {
            "entity_id": eid,
            "entity_type": etype,
            "name": name,
            "description": "",
            "stats": {}
        }
        self._entities_data.append(new_ent)
        self._add_entity_row(new_ent)
        self._in_id.clear()
        self._in_name.clear()
        self._table.setCurrentCell(self._table.rowCount()-1, 2)
        self.changed.emit()

    @Slot()
    def _on_row_selected(self) -> None:
        """Load stats for the selected entity."""
        self._sync_stats_from_ui()
        row = self._table.currentRow()
        self._selected_row = row
        
        self._stats_table.setRowCount(0)
        if row < 0 or row >= len(self._entities_data):
            return
            
        ent = self._entities_data[row]
        stats = ent.get("stats", {})
        for k, v in stats.items():
            self._add_stat_row_with_data(k, v)

    @Slot()
    def _on_add_stat_row(self) -> None:
        """Add a blank stat row to the selected entity."""
        self._add_stat_row_with_data("", "")
        self.changed.emit()

    def _add_stat_row_with_data(self, key: str, value: str) -> None:
        r = self._stats_table.rowCount()
        self._stats_table.insertRow(r)
        
        key_combo = QComboBox()
        stat_names = [s["name"] for s in self._stat_defs]
        if key and key not in stat_names:
            stat_names.insert(0, key)
        key_combo.addItems(stat_names)
        key_combo.setCurrentText(key)
        self._stats_table.setCellWidget(r, 0, key_combo)
        key_combo.currentTextChanged.connect(lambda t: self._update_stat_value_widget(r, t))
        
        self._update_stat_value_widget(r, key, value)

    def _update_stat_value_widget(self, row: int, stat_name: str, initial_val: str = None) -> None:
        sdef = next((s for s in self._stat_defs if s["name"] == stat_name), None)
        if not sdef:
            self._stats_table.setCellWidget(row, 1, QLineEdit(str(initial_val or "")))
            return

        vtype = sdef.get("value_type", "numeric")
        params = sdef.get("parameters", {})
        if vtype == "numeric":
            spin = QDoubleSpinBox()
            spin.setRange(float(params.get("min", -999999)), float(params.get("max", 999999)))
            val = float(initial_val) if initial_val not in (None, "") else float(params.get("min", 0))
            spin.setValue(val)
            self._stats_table.setCellWidget(row, 1, spin)
        elif vtype == "categorical":
            cb = QComboBox()
            options = params.get("options", [])
            cb.addItems(options)
            if initial_val in options: cb.setCurrentText(initial_val)
            self._stats_table.setCellWidget(row, 1, cb)

    def _sync_stats_from_ui(self) -> None:
        """Save current stats table into the active entity dict."""
        if self._selected_row < 0 or self._selected_row >= len(self._entities_data):
            return
            
        stats = {}
        for r in range(self._stats_table.rowCount()):
            key_w = self._stats_table.cellWidget(r, 0)
            val_w = self._stats_table.cellWidget(r, 1)
            
            key = key_w.currentText() if isinstance(key_w, QComboBox) else ""
            if isinstance(val_w, QDoubleSpinBox): val = str(val_w.value())
            elif isinstance(val_w, QComboBox): val = val_w.currentText()
            else: val = val_w.text() if hasattr(val_w, "text") else ""
            
            if key: stats[key] = val
        self._entities_data[self._selected_row]["stats"] = stats

    @Slot()
    def _on_add_all_stats(self) -> None:
        if self._selected_row < 0: return
        existing_keys = [self._stats_table.cellWidget(r, 0).currentText() 
                         for r in range(self._stats_table.rowCount()) 
                         if isinstance(self._stats_table.cellWidget(r, 0), QComboBox)]
        
        for sdef in self._stat_defs:
            if sdef["name"] not in existing_keys:
                self._add_stat_row_with_data(sdef["name"], "")
        self.changed.emit()

    @Slot()
    def _on_remove_stat_row(self) -> None:
        r = self._stats_table.currentRow()
        if r >= 0: self._stats_table.removeRow(r)
        self.changed.emit()

    @Slot()
    def _on_delete_entity(self) -> None:
        indices = self._table.selectionModel().selectedRows()
        rows = sorted([i.row() for i in indices], reverse=True) if indices else [self._table.currentRow()]
        for r in rows:
            if 0 <= r < len(self._entities_data):
                del self._entities_data[r]
                self._table.removeRow(r)
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        self.changed.emit()

    def _on_custom_populate_clicked(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Populate ✨", "Describe the entities to generate (NPCs, Factions...):")
        if ok and text.strip():
            self.populate_requested.emit("custom", text.strip())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete:
            self._on_delete_entity()
        else:
            super().keyPressEvent(event)
