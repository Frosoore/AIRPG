"""
ui/loading_view.py

Simple loading screen for AIRPG shown during universe transitions.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class LoadingView(QWidget):
    """Simple centered loading screen."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self._label = QLabel("Loading Universe...")
        self._label.setStyleSheet("font-size: 18px; font-weight: bold; color: #d4d4d4;")
        self._label.setAlignment(Qt.AlignCenter)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # Indeterminate
        self._progress.setFixedWidth(300)

        layout.addWidget(self._label)
        layout.addSpacing(20)
        layout.addWidget(self._progress)

    def set_message(self, message: str) -> None:
        """Update the loading text."""
        self._label.setText(message)
