"""
ui/widgets/lore_book_editor.py

Visual editor for the Lore_Book table in the Creator Studio.

Provides a two-panel splitter layout: a list of entries on the left
and a form for editing a single entry (category, name, content) on the
right.  Mirrors the paradigm of EntityEditorWidget.

THREADING RULE: No database I/O here.  Data is loaded by DbWorker and
passed via populate(); collected by _on_save_clicked via collect_data().
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class LoreBookEditorWidget(QWidget):
    """Visual editor for Lore_Book entries.

    Left panel: scrollable list of entries (shown as "Category - Name").
    Right panel: editable form for category, name, and content.

    Usage::
        editor = LoreBookEditorWidget()
        editor.populate(list_of_entry_dicts)
        ...
        entries = editor.collect_data()
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[dict] = []
        self._current_index: int = -1
        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the two-panel splitter layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # ---- Left panel: entry list ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.addWidget(QLabel("<b>Lore Entries</b>"))

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Entry")
        del_btn = QPushButton("Delete Entry")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        left_layout.addLayout(btn_row)

        add_btn.clicked.connect(self._on_add_clicked)
        del_btn.clicked.connect(self._on_delete_clicked)

        # ---- Right panel: entry form ----
        right = QGroupBox("Entry Details")
        form = QFormLayout(right)

        self._category_edit = QLineEdit()
        self._category_edit.setPlaceholderText("e.g. Faction, Magic System, Location")
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. The Red Guard")
        self._content_edit = QPlainTextEdit()
        self._content_edit.setPlaceholderText(
            "Describe this lore entry in detail..."
        )
        self._content_edit.setMinimumHeight(180)

        form.addRow("Category:", self._category_edit)
        form.addRow("Name:", self._name_edit)
        form.addRow("Content:", self._content_edit)

        # Sync form changes back to in-memory list
        self._category_edit.textChanged.connect(self._on_form_changed)
        self._name_edit.textChanged.connect(self._on_form_changed)
        self._content_edit.textChanged.connect(self._on_form_changed)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([200, 400])
        layout.addWidget(splitter)

        self._set_form_enabled(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate(self, entries: list[dict]) -> None:
        """Populate the editor with a list of Lore_Book entry dicts.

        Each dict must have keys: entry_id, category, name, content.

        Args:
            entries: List of entry dicts loaded from the database.
        """
        self._entries = [dict(e) for e in entries]
        self._current_index = -1
        self._refresh_list()
        self._set_form_enabled(False)
        self._clear_form()

    def collect_data(self) -> list[dict]:
        """Return the current in-memory list of entry dicts.

        Flushes any pending form edits before returning.

        Returns:
            List of entry dicts with keys: entry_id, category, name, content.
        """
        # Phase 7: Absolute Persistence Protocol - Sync and refresh UI label
        self._flush_form()
        for entry in self._entries:
            if not entry.get("entry_id"):
                entry["entry_id"] = uuid.uuid4().hex
        return [dict(e) for e in self._entries]

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_add_clicked(self) -> None:
        """Add a new blank entry and select it."""
        entry = {
            "entry_id": str(uuid.uuid4()),
            "category": "",
            "name": "New Entry",
            "content": "",
        }
        self._entries.append(entry)
        self._refresh_list()
        self._list.setCurrentRow(len(self._entries) - 1)

    @Slot()
    def _on_delete_clicked(self) -> None:
        """Delete the currently selected entry."""
        row = self._current_index
        if row < 0 or row >= len(self._entries):
            return

        # 1. Block signals for the list
        self._list.blockSignals(True)

        # 2. Delete data
        self._entries.pop(row)
        self._list.takeItem(row)

        # 3. Reset local selection BEFORE unblocking
        self._current_index = -1

        # 4. Unblock signals
        self._list.blockSignals(False)

        # 5. Force selection of the new item at the same position (or last)
        new_row = self._list.currentRow()
        if new_row >= 0:
            self._on_selection_changed(new_row)
        else:
            # Clear form if no entries left
            self._set_form_enabled(False)
            self._clear_form()

    @Slot(int)
    def _on_selection_changed(self, row: int) -> None:
        """Load the selected entry into the form."""
        self._flush_form()
        self._current_index = row
        if 0 <= row < len(self._entries):
            entry = self._entries[row]
            self._category_edit.blockSignals(True)
            self._name_edit.blockSignals(True)
            self._content_edit.blockSignals(True)
            self._category_edit.setText(entry.get("category", ""))
            self._name_edit.setText(entry.get("name", ""))
            self._content_edit.setPlainText(entry.get("content", ""))
            self._category_edit.blockSignals(False)
            self._name_edit.blockSignals(False)
            self._content_edit.blockSignals(False)
            self._set_form_enabled(True)
        else:
            self._set_form_enabled(False)
            self._clear_form()

    @Slot()
    def _on_form_changed(self) -> None:
        """Sync form values to the in-memory entry and refresh the list label."""
        if 0 <= self._current_index < len(self._entries):
            self._entries[self._current_index]["category"] = (
                self._category_edit.text().strip()
            )
            self._entries[self._current_index]["name"] = (
                self._name_edit.text().strip()
            )
            self._entries[self._current_index]["content"] = (
                self._content_edit.toPlainText()
            )
            # Refresh just the label for the current row
            label = self._make_label(self._entries[self._current_index])
            if self._list.item(self._current_index):
                self._list.item(self._current_index).setText(label)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        """Rebuild the QListWidget from `_entries`."""
        self._list.blockSignals(True)
        self._list.clear()
        for entry in self._entries:
            self._list.addItem(QListWidgetItem(self._make_label(entry)))
        self._list.blockSignals(False)

    @staticmethod
    def _make_label(entry: dict) -> str:
        """Return a human-readable label for a list row."""
        cat = entry.get("category", "").strip() or "Uncategorised"
        name = entry.get("name", "").strip() or "(unnamed)"
        return f"{cat} - {name}"

    def _flush_form(self) -> None:
        """Write current form values back to the in-memory entry."""
        if 0 <= self._current_index < len(self._entries):
            category = self._category_edit.text().strip()
            name = self._name_edit.text().strip()
            content = self._content_edit.toPlainText()

            self._entries[self._current_index]["category"] = category
            self._entries[self._current_index]["name"] = name
            self._entries[self._current_index]["content"] = content

            # Phase 7: Refresh the list item text immediately
            label = self._make_label(self._entries[self._current_index])
            item = self._list.item(self._current_index)
            if item:
                item.setText(label)

    def _set_form_enabled(self, enabled: bool) -> None:
        """Enable or disable the right-panel form fields."""
        self._category_edit.setEnabled(enabled)
        self._name_edit.setEnabled(enabled)
        self._content_edit.setEnabled(enabled)

    def _clear_form(self) -> None:
        """Clear all form fields without triggering sync signals."""
        for widget in (self._category_edit, self._name_edit):
            widget.blockSignals(True)
            widget.clear()
            widget.blockSignals(False)
        self._content_edit.blockSignals(True)
        self._content_edit.clear()
        self._content_edit.blockSignals(False)
