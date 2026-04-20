"""
ui/settings_dialog.py

Settings dialog for AIRPG - LLM backend configuration.

Allows the user to switch between Ollama (local) and Gemini (cloud),
configure model names and URLs, and test the connection.

THREADING RULE: "Test Connection" spawns ConnectionTestWorker.
No network calls on the main thread.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import AppConfig, build_llm_from_config, save_config, GLOBAL_DB_FILE
from ui.widgets.persona_editor import PersonaEditorWidget
from workers.connection_test_worker import ConnectionTestWorker
from workers.db_worker import DbWorker


class SettingsDialog(QDialog):
    """LLM backend and application settings dialog.

    Loads its fields from an AppConfig on construction, and returns the
    updated AppConfig via collect_config() when the user presses Save.

    Args:
        config:  The current AppConfig to display.
        db_path: Optional path to the active universe database.
        parent:  Optional Qt parent widget.
    """

    def __init__(self, config: AppConfig, db_path: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings - AIRPG")
        self.setMinimumWidth(460)
        self._config = config
        self._db_path = db_path
        self._test_worker: ConnectionTestWorker | None = None
        self._db_worker: DbWorker | None = None
        self._universe_meta: dict = {}

        self._setup_ui()
        self.load_from_config(config)

        # Asynchronously load global personas from SQLite
        self._load_personas_async()
        
        # Asynchronously load universe meta if available
        if self._db_path:
            self._load_universe_meta_async()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()

        # ---- Universal API tab ----
        univ_widget = QWidget()
        univ_form = QFormLayout(univ_widget)
        self._univ_url = QLineEdit()
        self._univ_url.setPlaceholderText("http://localhost:11434/v1")
        self._univ_key = QLineEdit()
        self._univ_key.setEchoMode(QLineEdit.Password)
        self._univ_key.setPlaceholderText("Optional API Key")
        self._univ_model = QLineEdit()
        self._univ_model.setPlaceholderText("e.g. llama3.2 or gpt-4")
        self._extraction_model = QLineEdit()
        self._extraction_model.setPlaceholderText("e.g. llama3.1:8b")
        self._extraction_model.setToolTip("Model used strictly for JSON data extraction (e.g. Populate).")
        self._univ_test_btn = QPushButton("Test Connection")
        self._univ_status = QLabel("")
        univ_form.addRow("Base URL:", self._univ_url)
        univ_form.addRow("API Key:", self._univ_key)
        univ_form.addRow("Main Model:", self._univ_model)
        univ_form.addRow("Extraction Model:", self._extraction_model)
        test_row = QHBoxLayout()
        test_row.addWidget(self._univ_test_btn)
        test_row.addWidget(self._univ_status)
        test_row.addStretch()
        univ_form.addRow(test_row)
        self._tabs.addTab(univ_widget, "Universal API (Local/Cloud)")

        # ---- Gemini tab ----
        gemini_widget = QWidget()
        gemini_form = QFormLayout(gemini_widget)
        self._gemini_key = QLineEdit()
        self._gemini_key.setEchoMode(QLineEdit.Password)
        self._gemini_key.setPlaceholderText("Your Google Gemini API key")
        self._gemini_model = QLineEdit()
        self._gemini_model.setPlaceholderText("e.g. gemini-2.0-flash")
        self._gemini_test_btn = QPushButton("Test Connection")
        self._gemini_status = QLabel("")
        gemini_form.addRow("API Key:", self._gemini_key)
        gemini_form.addRow("Model name:", self._gemini_model)
        test_row2 = QHBoxLayout()
        test_row2.addWidget(self._gemini_test_btn)
        test_row2.addWidget(self._gemini_status)
        test_row2.addStretch()
        gemini_form.addRow(test_row2)
        self._tabs.addTab(gemini_widget, "Cloud (Gemini)")
        
        # ---- Universe Parameters tab ----
        self._univ_params_widget = QWidget()
        univ_params_form = QFormLayout(self._univ_params_widget)
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 1.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_spin.setValue(0.7)
        self._top_p_spin = QDoubleSpinBox()
        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.05)
        self._top_p_spin.setValue(1.0)
        
        univ_params_form.addRow("LLM Temperature:", self._temp_spin)
        univ_params_form.addRow("LLM Top P:", self._top_p_spin)
        
        self._univ_params_info = QLabel("<i>These parameters are specific to the current universe.</i>")
        self._univ_params_info.setWordWrap(True)
        univ_params_form.addRow(self._univ_params_info)
        
        self._tabs.addTab(self._univ_params_widget, "Universe Parameters")
        if not self._db_path:
            self._tabs.setTabEnabled(self._tabs.indexOf(self._univ_params_widget), False)
            self._univ_params_info.setText("<span style='color:#c0392b;'>No universe loaded.</span>")

        # ---- Personas tab ----
        self._persona_editor = PersonaEditorWidget()
        self._tabs.addTab(self._persona_editor, "Personas")

        layout.addWidget(self._tabs)

        # ---- General section ----
        general_group = QGroupBox("General & System")
        general_form = QFormLayout(general_group)
        
        self._chronicler_spin = QSpinBox()
        self._chronicler_spin.setRange(1, 500)
        self._chronicler_spin.setToolTip("Number of player turns between Chronicler world-simulation runs.")
        
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 36)
        self._font_size_spin.setToolTip("Font size for the chat display.")
        
        self._rag_chunk_spin = QSpinBox()
        self._rag_chunk_spin.setRange(1, 20)
        self._rag_chunk_spin.setToolTip("Number of memory chunks to retrieve for context (RAG).")
        
        from PySide6.QtWidgets import QCheckBox
        self._audio_cb = QCheckBox("Enable Background Audio Ambiance")
        
        general_form.addRow("Chronicler interval (turns):", self._chronicler_spin)
        general_form.addRow("Chat Font Size:", self._font_size_spin)
        general_form.addRow("RAG Context Chunks:", self._rag_chunk_spin)
        general_form.addRow("", self._audio_cb)
        
        layout.addWidget(general_group)

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Connections
        self._univ_test_btn.clicked.connect(self._test_universal)
        self._gemini_test_btn.clicked.connect(self._test_gemini)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_from_config(self, config: AppConfig) -> None:
        """Populate all form fields from an AppConfig.

        Args:
            config: The configuration to display.
        """
        self._univ_url.setText(config.universal_base_url)
        self._univ_key.setText(config.universal_api_key)
        self._univ_model.setText(config.universal_model)
        self._extraction_model.setText(config.extraction_model)
        self._gemini_key.setText(config.gemini_api_key)
        self._gemini_model.setText(config.gemini_model)
        self._chronicler_spin.setValue(config.chronicler_interval)
        self._font_size_spin.setValue(config.ui_font_size)
        self._rag_chunk_spin.setValue(config.rag_chunk_count)
        self._audio_cb.setChecked(config.enable_audio)

        # Select the correct tab
        if config.llm_backend == "gemini":
            self._tabs.setCurrentIndex(1)
        else:
            self._tabs.setCurrentIndex(0)

    def collect_config(self) -> AppConfig:
        """Read all form fields and return an updated AppConfig.

        Returns:
            New AppConfig reflecting the current form state.
        """
        backend = "universal"
        if self._tabs.currentIndex() == 1:
            backend = "gemini"

        return AppConfig(
            llm_backend=backend,
            universal_base_url=self._univ_url.text().strip() or "http://localhost:11434/v1",
            universal_api_key=self._univ_key.text().strip(),
            universal_model=self._univ_model.text().strip() or "llama3.2",
            gemini_api_key=self._gemini_key.text().strip(),
            gemini_model=self._gemini_model.text().strip() or "gemini-2.0-flash",
            extraction_model=self._extraction_model.text().strip() or "llama3.1:8b",
            chronicler_interval=self._chronicler_spin.value(),
            ui_font_size=self._font_size_spin.value(),
            enable_audio=self._audio_cb.isChecked(),
            rag_chunk_count=self._rag_chunk_spin.value(),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_universe_meta_async(self) -> None:
        """Start a DbWorker to load meta from the universe SQLite DB."""
        self._univ_db_worker = DbWorker(self._db_path)
        self._univ_db_worker.universe_meta_loaded.connect(self._on_meta_loaded)
        self._univ_db_worker.load_universe_meta()

    @Slot(dict)
    def _on_meta_loaded(self, meta: dict) -> None:
        """Populate universe parameters from meta."""
        self._universe_meta = meta
        try:
            temp = float(meta.get("llm_temperature", "0.7"))
        except ValueError:
            temp = 0.7
        self._temp_spin.setValue(max(0.0, min(1.0, temp)))
        
        try:
            top_p = float(meta.get("llm_top_p", "1.0"))
        except ValueError:
            top_p = 1.0
        self._top_p_spin.setValue(max(0.0, min(1.0, top_p)))

    def _load_personas_async(self) -> None:
        """Start a DbWorker to load global personas from the global SQLite DB."""
        self._db_worker = DbWorker(str(GLOBAL_DB_FILE))
        self._db_worker.personas_loaded.connect(self._persona_editor.populate)
        self._db_worker.load_global_personas()

    def _save_personas_async(self) -> None:
        """Start a DbWorker to save global personas to the global SQLite DB."""
        personas = self._persona_editor.collect_data()
        self._save_worker = DbWorker(str(GLOBAL_DB_FILE))
        self._save_worker.save_global_personas(personas)
        
        # If we have a universe to save too, chain into it, otherwise accept
        if self._db_path:
            self._save_worker.save_complete.connect(self._save_universe_meta_async)
        else:
            self._save_worker.save_complete.connect(self.accept)
            
        self._save_worker.error_occurred.connect(
            lambda msg: QMessageBox.critical(self, "Save Error", msg)
        )

    def _save_universe_meta_async(self) -> None:
        """Save universe-specific LLM parameters."""
        meta = {
            "llm_temperature": str(self._temp_spin.value()),
            "llm_top_p": str(self._top_p_spin.value()),
        }
        self._univ_save_worker = DbWorker(self._db_path)
        self._univ_save_worker.save_universe_meta(meta)
        self._univ_save_worker.save_complete.connect(self.accept)
        self._univ_save_worker.error_occurred.connect(
            lambda msg: QMessageBox.critical(self, "Save Error", msg)
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_save(self) -> None:
        """Save the config to disk, then save personas to SQLite, then close."""
        config = self.collect_config()
        try:
            save_config(config)
            self._config = config
        except OSError as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save settings:\n{exc}")
            return

        # Chain into persona save (which may chain into universe save)
        self._save_personas_async()

    @Slot()
    def _test_universal(self) -> None:
        """Start ConnectionTestWorker for the Universal backend."""
        self._univ_status.setText("Testing...")
        self._univ_test_btn.setEnabled(False)
        cfg = self.collect_config()
        cfg.llm_backend = "universal"
        try:
            llm = build_llm_from_config(cfg)
        except ValueError as exc:
            self._univ_status.setText(f"FAILED {exc}")
            self._univ_test_btn.setEnabled(True)
            return
        self._test_worker = ConnectionTestWorker(llm)
        self._test_worker.result_ready.connect(
            lambda ok, msg: self._on_test_result(ok, msg, self._univ_status, self._univ_test_btn)
        )
        self._test_worker.start()

    @Slot()
    def _test_gemini(self) -> None:
        """Start ConnectionTestWorker for the Gemini backend."""
        self._gemini_status.setText("Testing...")
        self._gemini_test_btn.setEnabled(False)
        cfg = self.collect_config()
        cfg.llm_backend = "gemini"
        try:
            llm = build_llm_from_config(cfg)
        except ValueError as exc:
            self._gemini_status.setText(f"FAILED {exc}")
            self._gemini_test_btn.setEnabled(True)
            return
        self._test_worker = ConnectionTestWorker(llm)
        self._test_worker.result_ready.connect(
            lambda ok, msg: self._on_test_result(ok, msg, self._gemini_status, self._gemini_test_btn)
        )
        self._test_worker.start()

    @Slot(bool, str)
    def _on_test_result(
        self,
        ok: bool,
        msg: str,
        status_label: QLabel,
        test_btn: QPushButton,
    ) -> None:
        """Update the status label after a connection test."""
        color = "#27ae60" if ok else "#c0392b"
        status_label.setText(f'<span style="color:{color};">{msg}</span>')
        test_btn.setEnabled(True)
