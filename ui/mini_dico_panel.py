"""
ui/mini_dico_panel.py

Mini-Dico (Lore Reference) side panel for the Tabletop screen.

Provides encyclopedic lore lookups that are completely siloed from the
main narrative context - no entity stats, no chat history are sent.

THREADING RULE: The LLM call and VectorMemory query are delegated
entirely to MiniDicoWorker.  No I/O on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from workers.mini_dico_worker import MiniDicoWorker
from core.localization import tr


class MiniDicoPanel(QWidget):
    """Encyclopedic lore-lookup panel, siloed from the narrative context.

    The panel is always visible alongside the chat but shares zero context
    with it.  Each query spawns an independent MiniDicoWorker.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(360)

        # Set via configure() when the tabletop session starts
        self._llm = None
        self._vector_memory = None
        self._save_id: str = ""
        self._lore_book: list[dict] = []
        self._global_lore: str | None = None
        self._worker: MiniDicoWorker | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 4, 4, 4)

        self._header = QLabel(f"<b>{tr('tab_lore')}</b>")
        layout.addWidget(self._header)

        self._answer_display = QTextEdit()
        self._answer_display.setReadOnly(True)
        self._answer_display.setAcceptRichText(False)
        self._answer_display.setPlaceholderText(
            tr("ready") # Fallback placeholder
        )
        self._answer_display.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        layout.addWidget(self._answer_display)

        self._question_input = QLineEdit()
        self._question_input.setPlaceholderText(tr("lore_search"))
        layout.addWidget(self._question_input)

        self._ask_button = QPushButton(tr("send")) # Reuse "Send" or add "Ask"
        if "ask" in tr("ready"):
             self._ask_button.setText(tr("ask"))
        else:
             self._ask_button.setText("Ask")
             
        layout.addWidget(self._ask_button)

        self._ask_button.clicked.connect(self._on_ask_clicked)
        self._question_input.returnPressed.connect(self._on_ask_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Refresh all UI text."""
        self._header.setText(f"<b>{tr('tab_lore')}</b>")
        self._question_input.setPlaceholderText(tr("lore_search"))
        
        ask_text = tr("send")
        if "ask" in tr("ready"):
             ask_text = tr("ask")
        self._ask_button.setText(ask_text)

    def configure(
        self,
        llm,
        vector_memory,
        save_id: str,
        lore_book: list[dict] | None = None,
        global_lore: str | None = None,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> None:
        """Provide backend references for use by the worker."""
        self._llm = llm
        self._vector_memory = vector_memory
        self._save_id = save_id
        self._lore_book = lore_book or []
        self._global_lore = global_lore
        self._temperature = temperature
        self._top_p = top_p

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_ask_clicked(self) -> None:
        """Spawn MiniDicoWorker for the current question."""
        question = self._question_input.text().strip()
        if not question:
            return
        if self._llm is None or self._vector_memory is None:
            self._answer_display.setPlainText(
                f"[{tr('no_sessions')}]"
            )
            return
        if self._worker and self._worker.isRunning():
            return 

        self._ask_button.setEnabled(False)
        self._answer_display.clear()

        self._worker = MiniDicoWorker(
            llm=self._llm,
            vector_memory=self._vector_memory,
            question=question,
            universe_save_id=self._save_id,
            lore_book=self._lore_book,
            global_lore=self._global_lore,
            temperature=self._temperature,
            top_p=self._top_p,
        )
        self._worker.token_received.connect(self._append_token)
        self._worker.response_complete.connect(self._on_response_complete)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    @Slot(str)
    def _append_token(self, token: str) -> None:
        """Append a response token to the answer display."""
        cursor = self._answer_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self._answer_display.setTextCursor(cursor)
        self._answer_display.ensureCursorVisible()

    @Slot(str)
    def _on_response_complete(self, full_text: str) -> None:
        """Re-enable the Ask button when the response finishes."""
        self._ask_button.setEnabled(True)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        """Show the error in the answer display and re-enable Ask."""
        self._answer_display.setPlainText(f"[{tr('error')}: {message}]")
        self._ask_button.setEnabled(True)
