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

        header = QLabel("<b>Lore Reference</b>")
        layout.addWidget(header)

        self._answer_display = QTextEdit()
        self._answer_display.setReadOnly(True)
        self._answer_display.setAcceptRichText(False)
        self._answer_display.setPlaceholderText("Lore answers appear here...")
        self._answer_display.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        layout.addWidget(self._answer_display)

        self._question_input = QLineEdit()
        self._question_input.setPlaceholderText("Ask about the lore...")
        layout.addWidget(self._question_input)

        self._ask_button = QPushButton("Ask")
        layout.addWidget(self._ask_button)

        self._ask_button.clicked.connect(self._on_ask_clicked)
        self._question_input.returnPressed.connect(self._on_ask_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        """Provide backend references for use by the worker.

        Called by TabletopView.load_session() and reload_llm().
        Must be called before any query is attempted.

        Args:
            llm:           The session LLMBackend instance.
            vector_memory: The session VectorMemory instance.
            save_id:       The active save ID for scoping lore queries.
            lore_book:     Optional Lore_Book entry list to inject into
                           Mini-Dico prompts for structured world knowledge.
            global_lore:   Optional foundational world lore string.
            temperature:   Sampling temperature (0.0 to 1.0).
            top_p:         Nucleus sampling parameter (0.0 to 1.0).
        """
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
                "[Lore Reference not available - no active session.]"
            )
            return
        if self._worker and self._worker.isRunning():
            return  # Ignore while a query is in progress

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
        self._answer_display.setPlainText(f"[Error: {message}]")
        self._ask_button.setEnabled(True)
