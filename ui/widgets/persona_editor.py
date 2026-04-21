"""
ui/widgets/persona_editor.py

Visual editor for the Personas table in the Creator Studio.
"""

from __future__ import annotations

import uuid
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from core.localization import tr

class PersonaEditorWidget(QWidget):
    """Visual editor for defining player personas."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._personas: list[dict] = []
        self._current_index: int = -1
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter()

        # Left: List and Actions
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self._list = QListWidget()
        self._header = QLabel(f"<b>{tr('persona_template').replace(':', '')}</b>")
        left_layout.addWidget(self._header)
        left_layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton(tr("add"))
        self._del_btn = QPushButton(tr("delete"))
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._del_btn)
        left_layout.addLayout(btn_row)

        # Right: Editor Form
        self._form = QWidget()
        form_layout = QVBoxLayout(self._form)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(tr("name"))
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText(tr("description"))

        # Use localized colon
        from core.config import load_config
        lang = getattr(load_config(), "language", "en")
        colon = "：" if lang in ("zh", "ja") else ":"
        if lang == "fr": colon = " :"
        
        self._name_label = QLabel(tr("name") + colon)
        self._desc_label = QLabel(tr("description") + colon)
        form_layout.addWidget(self._name_label)
        form_layout.addWidget(self._name_edit)
        form_layout.addWidget(self._desc_label)
        form_layout.addWidget(self._desc_edit)
        form_layout.addStretch()

        splitter.addWidget(left_panel)
        splitter.addWidget(self._form)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

        self._set_form_enabled(False)

        # Connections
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._del_btn.clicked.connect(self._on_delete_clicked)
        self._name_edit.textChanged.connect(self._on_form_changed)
        self._desc_edit.textChanged.connect(self._on_form_changed)

    def retranslate_ui(self) -> None:
        """Refresh all UI text."""
        self._header.setText(f"<b>{tr('persona_template').replace(':', '')}</b>")
        self._add_btn.setText(tr("add"))
        self._del_btn.setText(tr("delete"))
        
        # Use localized colon
        from core.config import load_config
        lang = getattr(load_config(), "language", "en")
        colon = "：" if lang in ("zh", "ja") else ":"
        if lang == "fr": colon = " :"
        
        self._name_label.setText(tr("name") + colon)
        self._desc_label.setText(tr("description") + colon)
        
        self._name_edit.setPlaceholderText(tr("name"))
        self._desc_edit.setPlaceholderText(tr("description"))

    def populate(self, personas: list[dict]) -> None:
        """Replace internal list and refresh the UI."""
        self._personas = [dict(p) for p in personas]
        self._refresh_list()
        self._set_form_enabled(False)
        self._clear_form()

    def collect_data(self) -> list[dict]:
        """Return the current in-memory list of persona dicts."""
        self._flush_form()
        return [dict(p) for p in self._personas]

    def _refresh_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for p in self._personas:
            self._list.addItem(p.get("name") or "(unnamed)")
        self._list.blockSignals(False)

    def _set_form_enabled(self, enabled: bool) -> None:
        self._name_edit.setEnabled(enabled)
        self._desc_edit.setEnabled(enabled)

    def _clear_form(self) -> None:
        self._name_edit.clear()
        self._desc_edit.clear()

    def _flush_form(self) -> None:
        if 0 <= self._current_index < len(self._personas):
            name = self._name_edit.text().strip()
            self._personas[self._current_index]["name"] = name
            self._personas[self._current_index]["description"] = self._desc_edit.toPlainText()
            item = self._list.item(self._current_index)
            if item:
                item.setText(name or "(unnamed)")

    @Slot(int)
    def _on_selection_changed(self, row: int) -> None:
        self._flush_form()
        self._current_index = row
        if 0 <= row < len(self._personas):
            p = self._personas[row]
            self._name_edit.blockSignals(True)
            self._desc_edit.blockSignals(True)
            self._name_edit.setText(p.get("name", ""))
            self._desc_edit.setPlainText(p.get("description", ""))
            self._name_edit.blockSignals(False)
            self._desc_edit.blockSignals(False)
            self._set_form_enabled(True)
        else:
            self._set_form_enabled(False)
            self._clear_form()

    @Slot()
    def _on_add_clicked(self) -> None:
        default_name = tr("persona_template").replace(":", "").upper()
        p = {"persona_id": str(uuid.uuid4()), "name": default_name, "description": ""}
        self._personas.append(p)
        self._refresh_list()
        self._list.setCurrentRow(len(self._personas) - 1)

    @Slot()
    def _on_delete_clicked(self) -> None:
        """Delete the currently selected persona."""
        row = self._current_index
        if row < 0 or row >= len(self._personas):
            return

        # 1. Block signals for the list
        self._list.blockSignals(True)

        # 2. Delete data
        self._personas.pop(row)
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
            # Clear form if no personas left
            self._set_form_enabled(False)
            self._clear_form()

    @Slot()
    def _on_form_changed(self) -> None:
        # For instant list feedback
        self._flush_form()
