"""
ui/widgets/universe_card.py

Individual universe card widget for the Hub library grid.

Each card represents one installed universe (.db file) and exposes
Play and Export buttons.  A lightweight metadata read is performed
at construction time (universe name from Universe_Meta); this is
acceptable because cards are created only during HubView.refresh_library(),
which runs outside any LLM or I/O-heavy operation.

THREADING RULE: No LLM or VectorMemory calls here.  The small SQLite
metadata read at card construction is the only permitted I/O.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from workers.db_helpers import read_universe_card_metadata


class UniverseCard(QFrame):
    """A styled card widget representing one locally installed AIRPG universe.

    Signals:
        play_requested(str):   Emitted with db_path when the Play button is clicked.
        export_requested(str): Emitted with db_path when the Export button is clicked.
        edit_requested(str):   Emitted with db_path when the Edit button is clicked.
        delete_requested(str): Emitted with db_path when the Delete button is clicked.

    Args:
        db_path: Absolute path to the universe .db file.
        parent:  Optional parent widget.
    """

    play_requested = Signal(str)
    export_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    _CARD_WIDTH: int = 280

    def __init__(
        self,
        db_path: str,
        universe_name: str,
        last_updated: str,
        difficulty: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._setup_ui(universe_name, last_updated, difficulty)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(
        self,
        universe_name: str,
        last_updated: str,
        difficulty: str,
    ) -> None:
        """Build the card layout."""
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setFixedWidth(self._CARD_WIDTH)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Title
        title_label = QLabel(f"<b>{universe_name}</b>")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # Last updated
        updated_label = QLabel(f"Last played: {last_updated}")
        updated_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(updated_label)

        # Difficulty badge
        badge_color = "#c0392b" if difficulty == "Hardcore" else "#27ae60"
        difficulty_label = QLabel(difficulty)
        difficulty_label.setStyleSheet(
            f"background: {badge_color}; color: white; "
            f"border-radius: 4px; padding: 2px 6px; font-size: 11px;"
        )
        layout.addWidget(difficulty_label)

        layout.addStretch()

        # Primary buttons row: Play + Export
        btn_layout = QHBoxLayout()
        play_btn = QPushButton("Play")
        export_btn = QPushButton("Export")
        btn_layout.addWidget(play_btn)
        btn_layout.addWidget(export_btn)
        layout.addLayout(btn_layout)

        # Secondary buttons row: Edit + Delete
        mgmt_layout = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        delete_btn = QPushButton("Delete")
        delete_btn.setStyleSheet("color: #e74c3c;")
        mgmt_layout.addWidget(edit_btn)
        mgmt_layout.addWidget(delete_btn)
        layout.addLayout(mgmt_layout)

        play_btn.clicked.connect(lambda: self.play_requested.emit(self._db_path))
        export_btn.clicked.connect(lambda: self.export_requested.emit(self._db_path))
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._db_path))
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._db_path))

