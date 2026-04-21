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
    QComboBox,
)

from core.config import AppConfig, build_llm_from_config, save_config, GLOBAL_DB_FILE, load_config
from core.localization import tr, SUPPORTED_LANGUAGES
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
        self.setWindowTitle(tr("settings_title"))
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
        self._univ_key.setPlaceholderText(tr("optional_key"))
        self._univ_model = QLineEdit()
        self._univ_model.setPlaceholderText("e.g. llama3.2 or gpt-4")
        self._extraction_model = QLineEdit()
        self._extraction_model.setPlaceholderText("e.g. llama3.1:8b")
        self._extraction_model.setToolTip("Model used strictly for JSON data extraction (e.g. Populate).")
        
        self._univ_test_btn = QPushButton(tr("test_connection"))
        
        self._univ_status = QLabel("")
        
        self._univ_url_label = QLabel(tr("base_url"))
        self._univ_key_label = QLabel(tr("api_key"))
        self._univ_model_label = QLabel(tr("main_model"))
        self._univ_extraction_label = QLabel(tr("extraction_model"))

        univ_form.addRow(self._univ_url_label, self._univ_url)
        univ_form.addRow(self._univ_key_label, self._univ_key)
        univ_form.addRow(self._univ_model_label, self._univ_model)
        univ_form.addRow(self._univ_extraction_label, self._extraction_model)
        
        test_row = QHBoxLayout()
        test_row.addWidget(self._univ_test_btn)
        test_row.addWidget(self._univ_status)
        test_row.addStretch()
        univ_form.addRow(test_row)
        self._tabs.addTab(univ_widget, tr("tab_llm"))

        # ---- Gemini tab ----
        gemini_widget = QWidget()
        gemini_form = QFormLayout(gemini_widget)
        self._gemini_key = QLineEdit()
        self._gemini_key.setEchoMode(QLineEdit.Password)
        self._gemini_key.setPlaceholderText(tr("gemini_key_placeholder"))
        self._gemini_model = QLineEdit()
        self._gemini_model.setPlaceholderText("e.g. gemini-2.0-flash")
        self._gemini_test_btn = QPushButton(tr("test_connection"))
        self._gemini_status = QLabel("")
        
        self._gemini_key_label = QLabel(tr("api_key"))
        self._gemini_model_label = QLabel(tr("model_name"))
        
        gemini_form.addRow(self._gemini_key_label, self._gemini_key)
        gemini_form.addRow(self._gemini_model_label, self._gemini_model)
        
        test_row2 = QHBoxLayout()
        test_row2.addWidget(self._gemini_test_btn)
        test_row2.addWidget(self._gemini_status)
        test_row2.addStretch()
        gemini_form.addRow(test_row2)
        self._tabs.addTab(gemini_widget, tr("cloud_gemini"))
        
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
        
        self._llm_temp_label = QLabel(tr("llm_temp"))
        self._llm_top_p_label = QLabel(tr("llm_top_p"))

        univ_params_form.addRow(self._llm_temp_label, self._temp_spin)
        univ_params_form.addRow(self._llm_top_p_label, self._top_p_spin)
        
        self._univ_params_info = QLabel(tr("univ_params_info"))
        self._univ_params_info.setWordWrap(True)
        univ_params_form.addRow(self._univ_params_info)
        
        self._tabs.addTab(self._univ_params_widget, tr("univ_params"))
        if not self._db_path:
            self._tabs.setTabEnabled(self._tabs.indexOf(self._univ_params_widget), False)
            self._univ_params_info.setText(f"<span style='color:#c0392b;'>{tr('no_universe_loaded')}</span>")

        # ---- Personas tab ----
        self._persona_editor = PersonaEditorWidget()
        self._tabs.addTab(self._persona_editor, tr("persona_template").replace(":", ""))

        layout.addWidget(self._tabs)

        # ---- General section ----
        self._general_group = QGroupBox(tr("tab_general"))
        general_form = QFormLayout(self._general_group)
        
        self._lang_combo = QComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self._lang_combo.addItem(name, code)
            
        self._chronicler_spin = QSpinBox()
        self._chronicler_spin.setRange(1, 500)
        
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 36)
        
        self._rag_chunk_spin = QSpinBox()
        self._rag_chunk_spin.setRange(1, 20)
        
        from PySide6.QtWidgets import QCheckBox
        self._audio_cb = QCheckBox(tr("enable_audio"))
        
        self._lang_label = QLabel(tr("language"))
        self._chronicler_label = QLabel(tr("chronicler_interval_label"))
        self._font_size_label = QLabel(tr("ui_font_size"))
        self._rag_chunks_label = QLabel(tr("rag_chunks"))

        general_form.addRow(self._lang_label, self._lang_combo)
        general_form.addRow(self._chronicler_label, self._chronicler_spin)
        general_form.addRow(self._font_size_label, self._font_size_spin)
        general_form.addRow(self._rag_chunks_label, self._rag_chunk_spin)
        general_form.addRow("", self._audio_cb)
        
        layout.addWidget(self._general_group)

        # ---- Buttons ----
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self._buttons.button(QDialogButtonBox.Save).setText(tr("save"))
        self._buttons.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        
        self._buttons.accepted.connect(self._on_save)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        # Connections
        self._univ_test_btn.clicked.connect(self._test_universal)
        self._gemini_test_btn.clicked.connect(self._test_gemini)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Refresh all UI text for the current language."""
        self.setWindowTitle(tr("settings_title"))
        
        # Tabs
        self._tabs.setTabText(0, tr("tab_llm"))
        self._tabs.setTabText(1, tr("cloud_gemini"))
        self._tabs.setTabText(2, tr("univ_params"))
        self._tabs.setTabText(3, tr("persona_template").replace(":", ""))
        
        # Universal Tab
        self._univ_url_label.setText(tr("base_url"))
        self._univ_key_label.setText(tr("api_key"))
        self._univ_model_label.setText(tr("main_model"))
        self._univ_extraction_label.setText(tr("extraction_model"))
        self._univ_key.setPlaceholderText(tr("optional_key"))
        self._univ_test_btn.setText(tr("test_connection"))
        
        # Gemini Tab
        self._gemini_key_label.setText(tr("api_key"))
        self._gemini_model_label.setText(tr("model_name"))
        self._gemini_key.setPlaceholderText(tr("gemini_key_placeholder"))
        self._gemini_test_btn.setText(tr("test_connection"))
        
        # Univ Params
        self._llm_temp_label.setText(tr("llm_temp"))
        self._llm_top_p_label.setText(tr("llm_top_p"))
        self._univ_params_info.setText(tr("univ_params_info") if self._db_path else tr("no_universe_loaded"))
        
        # General section
        self._general_group.setTitle(tr("tab_general"))
        self._lang_label.setText(tr("language"))
        self._chronicler_label.setText(tr("chronicler_interval_label"))
        self._font_size_label.setText(tr("ui_font_size"))
        self._rag_chunks_label.setText(tr("rag_chunks"))
        self._audio_cb.setText(tr("enable_audio"))
        
        # Sub-widgets
        if hasattr(self._persona_editor, "retranslate_ui"): self._persona_editor.retranslate_ui()

        # Buttons
        self._buttons.button(QDialogButtonBox.Save).setText(tr("save"))
        self._buttons.button(QDialogButtonBox.Cancel).setText(tr("cancel"))

    def load_from_config(self, config: AppConfig) -> None:
        """Populate all form fields from an AppConfig."""
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
        
        idx = self._lang_combo.findData(config.language)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        if config.llm_backend == "gemini":
            self._tabs.setCurrentIndex(1)
        else:
            self._tabs.setCurrentIndex(0)

    def collect_config(self) -> AppConfig:
        """Read all form fields and return an updated AppConfig."""
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
            language=self._lang_combo.currentData(),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_universe_meta_async(self) -> None:
        self._univ_db_worker = DbWorker(self._db_path)
        self._univ_db_worker.universe_meta_loaded.connect(self._on_meta_loaded)
        self._univ_db_worker.load_universe_meta()

    @Slot(dict)
    def _on_meta_loaded(self, meta: dict) -> None:
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
        self._db_worker = DbWorker(str(GLOBAL_DB_FILE))
        self._db_worker.personas_loaded.connect(self._persona_editor.populate)
        self._db_worker.load_global_personas()

    def _save_personas_async(self) -> None:
        personas = self._persona_editor.collect_data()
        self._save_worker = DbWorker(str(GLOBAL_DB_FILE))
        self._save_worker.save_global_personas(personas)
        
        if self._db_path:
            self._save_worker.save_complete.connect(self._save_universe_meta_async)
        else:
            self._save_worker.save_complete.connect(self.accept)
            
        self._save_worker.error_occurred.connect(
            lambda msg: QMessageBox.critical(self, tr("error"), msg)
        )

    def _save_universe_meta_async(self) -> None:
        meta = {
            "llm_temperature": str(self._temp_spin.value()),
            "llm_top_p": str(self._top_p_spin.value()),
        }
        self._univ_save_worker = DbWorker(self._db_path)
        self._univ_save_worker.save_universe_meta(meta)
        self._univ_save_worker.save_complete.connect(self.accept)
        self._univ_save_worker.error_occurred.connect(
            lambda msg: QMessageBox.critical(self, tr("error"), msg)
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_save(self) -> None:
        config = self.collect_config()
        try:
            save_config(config)
            self._config = config
        except OSError as exc:
            QMessageBox.critical(self, tr("error"), f"Could not save settings:\n{exc}")
            return

        self._save_personas_async()

    @Slot()
    def _test_universal(self) -> None:
        self._univ_status.setText(tr("testing"))
        self._univ_test_btn.setEnabled(False)
        cfg = self.collect_config()
        cfg.llm_backend = "universal"
        try:
            llm = build_llm_from_config(cfg)
        except ValueError as exc:
            self._univ_status.setText(f"{tr('failed')} {exc}")
            self._univ_test_btn.setEnabled(True)
            return
        self._test_worker = ConnectionTestWorker(llm)
        self._test_worker.result_ready.connect(
            lambda ok, msg: self._on_test_result(ok, msg, self._univ_status, self._univ_test_btn)
        )
        self._test_worker.start()

    @Slot()
    def _test_gemini(self) -> None:
        self._gemini_status.setText(tr("testing"))
        self._gemini_test_btn.setEnabled(False)
        cfg = self.collect_config()
        cfg.llm_backend = "gemini"
        try:
            llm = build_llm_from_config(cfg)
        except ValueError as exc:
            self._gemini_status.setText(f"{tr('failed')} {exc}")
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
        color = "#27ae60" if ok else "#c0392b"
        status_label.setText(f'<span style="color:{color};">{msg}</span>')
        test_btn.setEnabled(True)
