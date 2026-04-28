"""
ui/widgets/lore_book_editor.py

Visual editor for the Lore_Book table in the Creator Studio.
Uses a spreadsheet-like grid for direct lore management and managed categories.
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
    QMenu,
    QInputDialog,
    QMessageBox,
)
from core.localization import tr


class LoreBookEditorWidget(QWidget):
    """Spreadsheet-like lore builder for the Creator Studio."""

    populate_requested = Signal(str, object)
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[dict] = []
        self._categories: list[str] = ["General", "Faction", "Location", "Character", "Magic"]
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        top_row = QHBoxLayout()
        self._header = QLabel(f"<b>{tr('tab_lore')}</b>")
        top_row.addWidget(self._header)
        top_row.addStretch()
        layout.addLayout(top_row)

        # Input Row (Write before Add)
        input_group = QHBoxLayout()
        
        self._in_category = QComboBox()
        self._in_category.addItems(self._categories)
        self._in_category.setEditable(False)
        
        self._add_cat_btn = QPushButton("+")
        self._add_cat_btn.setToolTip(tr("add_category_tooltip") if "add_category_tooltip" in tr("ready") else "Add new category")
        self._add_cat_btn.setFixedWidth(40)
        self._add_cat_btn.clicked.connect(self._on_add_category)
        
        self._in_name = QLineEdit()
        self._in_name.setPlaceholderText(tr("name"))
        
        self._add_btn = QPushButton(f"{tr('add')} +")
        self._add_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self._add_btn.clicked.connect(self._on_add_clicked)

        input_group.addWidget(self._in_category, 2)
        input_group.addWidget(self._add_cat_btn, 0)
        input_group.addWidget(self._in_name, 4)
        input_group.addWidget(self._add_btn, 1)
        layout.addLayout(input_group)

        # Lore Table
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels([
            tr("type"), tr("name"), tr("description")
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
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

        self._del_btn.clicked.connect(self._on_delete_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        self._header.setText(f"<b>{tr('tab_lore')}</b>")
        self._add_btn.setText(f"{tr('add')} +")
        self._del_btn.setText(tr("delete"))
        self._in_name.setPlaceholderText(tr("name"))
        self._add_cat_btn.setText("+")
        self._add_cat_btn.setToolTip(tr("add_category_tooltip") if "add_category_tooltip" in tr("ready") else "Add new category")
        self._table.setHorizontalHeaderLabels([tr("type"), tr("name"), tr("description")])

    def populate(self, entries: list[dict]) -> None:
        """Load lore data into the table."""
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._entries = [dict(e) for e in entries]
        
        # Collect unique categories
        for e in self._entries:
            cat = e.get("category", "General")
            if cat and cat not in self._categories:
                self._categories.append(cat)
        self._refresh_category_combos()

        for ent in self._entries:
            self._add_lore_row(ent)
        
        self._table.blockSignals(False)

    def collect_data(self) -> list[dict]:
        """Gather data from table back into a list of dicts."""
        data = []
        for r in range(self._table.rowCount()):
            cat_w = self._table.cellWidget(r, 0)
            category = cat_w.currentText() if isinstance(cat_w, QComboBox) else "General"
            
            name = self._table.item(r, 1).text().strip()
            content = self._table.item(r, 2).text().strip()
            
            eid = self._table.item(r, 1).data(Qt.UserRole) or uuid.uuid4().hex
            
            data.append({
                "entry_id": eid,
                "category": category,
                "name": name,
                "content": content
            })
        return data

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    def _add_lore_row(self, ent: dict) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        
        cat_combo = QComboBox()
        cat_combo.addItems(self._categories)
        cat_combo.setCurrentText(ent.get("category", "General"))
        self._table.setCellWidget(row, 0, cat_combo)
        cat_combo.currentTextChanged.connect(lambda _: self.changed.emit())
        
        it_name = QTableWidgetItem(ent.get("name", ""))
        it_name.setData(Qt.UserRole, ent.get("entry_id", uuid.uuid4().hex))
        it_name.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogDetailedView))
        
        it_desc = QTableWidgetItem(ent.get("content", ""))
        
        self._table.setItem(row, 1, it_name)
        self._table.setItem(row, 2, it_desc)

    @Slot()
    def _on_add_clicked(self) -> None:
        cat = self._in_category.currentText()
        name = self._in_name.text().strip() or "(unnamed)"
        
        new_ent = {
            "entry_id": uuid.uuid4().hex,
            "category": cat,
            "name": name,
            "content": ""
        }
        self._add_lore_row(new_ent)
        self._in_name.clear()
        self._table.setCurrentCell(self._table.rowCount()-1, 2)
        self.changed.emit()

    @Slot()
    def _on_add_category(self) -> None:
        text, ok = QInputDialog.getText(self, "New Category", "Category Name:")
        if ok and text.strip():
            cat = text.strip()
            if cat not in self._categories:
                self._categories.append(cat)
                self._refresh_category_combos()
                self._in_category.setCurrentText(cat)

    def _refresh_category_combos(self) -> None:
        self._in_category.clear()
        self._in_category.addItems(self._categories)
        # We don't refresh table combos as it's destructive, but new rows will have it

    @Slot()
    def _on_delete_clicked(self) -> None:
        indices = self._table.selectionModel().selectedRows()
        rows = sorted([i.row() for i in indices], reverse=True) if indices else [self._table.currentRow()]
        for r in rows:
            if 0 <= r < self._table.rowCount():
                self._table.removeRow(r)
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete:
            self._on_delete_clicked()
        else:
            super().keyPressEvent(event)
