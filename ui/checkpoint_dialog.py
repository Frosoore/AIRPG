"""
ui/checkpoint_dialog.py

Checkpoint selection dialog for the Tabletop rewind feature.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QVBoxLayout,
)
from core.localization import tr


class CheckpointDialog(QDialog):
    """Lists available checkpoint turn IDs and returns the user's selection.

    Args:
        checkpoints: Sorted (ascending) list of integer turn IDs.
        parent:      Optional Qt parent widget.
    """

    def __init__(self, checkpoints: list[int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("rewind_title"))
        self.setMinimumWidth(280)
        self._selected: int | None = None
        # Most-recent first in the list
        self._turn_ids = list(reversed(checkpoints))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("rewind_title") + ":"))

        self._list = QListWidget()
        for turn_id in self._turn_ids:
            self._list.addItem(tr("turn_fmt", count=turn_id))
        if self._list.count():
            self._list.setCurrentRow(0)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        # Manually translate buttons if needed or use defaults if they map to system locale
        # PySide6 defaults often follow system language but let's be explicit
        buttons.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        
        buttons.accepted.connect(self._on_accepted)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_turn_id(self) -> int | None:
        """Return the selected turn ID, or None if the dialog was cancelled."""
        return self._selected

    def _on_accepted(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._turn_ids):
            self._selected = self._turn_ids[row]
        self.accept()
