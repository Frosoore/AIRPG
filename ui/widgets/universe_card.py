"""
ui/widgets/universe_card.py

Individual universe card widget for the Hub library grid.

Each card represents one installed universe (.db file) and exposes
Play and Export buttons.  A lightweight metadata read is performed
on construction to show the name and last-played timestamp.
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
from core.localization import tr
from workers.db_helpers import read_universe_card_metadata


class UniverseCard(QFrame):
    """A card in the Hub library grid representing one universe.

    Signals:
        play_requested(str):   Emitted when Play is clicked.
        export_requested(str): Emitted when Export is clicked.
        edit_requested(str):   Emitted when Edit is clicked.
        delete_requested(str): Emitted when Delete is clicked.
    """

    play_requested = Signal(str)
    export_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    _CARD_WIDTH: int = 240

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
        self._universe_name = universe_name
        self._last_updated = last_updated
        self._difficulty = difficulty
        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the card layout."""
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setFixedWidth(self._CARD_WIDTH)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Title
        self._title_label = QLabel(f"<b>{self._universe_name}</b>")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        # Last updated
        self._updated_label = QLabel(f"{tr('last_played')}: {self._last_updated}")
        self._updated_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._updated_label)

        # Difficulty badge
        if self._difficulty == "Hardcore":
            badge_color = "#c0392b" # Red
        elif self._difficulty == "Companion":
            badge_color = "#2980b9" # Blue
        else:
            badge_color = "#27ae60" # Green
        
        self._difficulty_label = QLabel(tr(self._difficulty.lower()))
        self._difficulty_label.setStyleSheet(
            f"background: {badge_color}; color: white; "
            f"border-radius: 4px; padding: 2px 6px; font-size: 11px;"
        )
        layout.addWidget(self._difficulty_label)

        layout.addStretch()

        # Primary buttons row: Play + Export
        btn_layout = QHBoxLayout()
        self._play_btn = QPushButton(tr("play"))
        self._export_btn = QPushButton(tr("export"))
        btn_layout.addWidget(self._play_btn)
        btn_layout.addWidget(self._export_btn)
        layout.addLayout(btn_layout)

        # Secondary buttons row: Edit + Delete
        mgmt_layout = QHBoxLayout()
        self._edit_btn = QPushButton(tr("edit"))
        self._delete_btn = QPushButton(tr("delete"))
        self._delete_btn.setStyleSheet("color: #e74c3c;")
        mgmt_layout.addWidget(self._edit_btn)
        mgmt_layout.addWidget(self._delete_btn)
        layout.addLayout(mgmt_layout)

        self._play_btn.clicked.connect(lambda: self.play_requested.emit(self._db_path))
        self._export_btn.clicked.connect(lambda: self.export_requested.emit(self._db_path))
        self._edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._db_path))
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._db_path))

    def retranslate_ui(self):
        """Dynamic text update for card elements."""
        from core.config import load_config
        lang = getattr(load_config(), "language", "en")
        colon = "：" if lang in ("zh", "ja") else ":"
        if lang == "fr": colon = " :"
        
        # Avoid direct string addition which might be causing issues on some Qt versions/platforms
        label_text = f"{tr('last_played')}{colon} {self._last_updated}"
        self._updated_label.setText(label_text)
        self._difficulty_label.setText(tr(self._difficulty.lower()))
        self._play_btn.setText(tr("play"))
        self._export_btn.setText(tr("export"))
        self._edit_btn.setText(tr("edit"))
        self._delete_btn.setText(tr("delete"))
