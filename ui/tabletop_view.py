"""
ui/tabletop_view.py

Tabletop screen - the main gameplay interface for Axiom AI.

Coordinates the three sub-panels (ConstantsSidebar, ChatDisplayWidget,
MiniDicoPanel) and owns all worker instances for the active session.

THREADING RULE: No LLM, SQLite, or VectorMemory calls on the main thread.
Every I/O operation is delegated to a worker.  The main thread only
handles signal routing and UI state management.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from PySide6.QtCore import Qt, Signal, Slot, QUrl, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QSlider,
    QSizePolicy,
    QComboBox,
)

from core.multiplayer_queue import ArbitratorWorker, PlayerAction
from core.arbitrator import ArbitratorEngine, ArbitratorResult

from ui.checkpoint_dialog import CheckpointDialog
from ui.constants_sidebar import ConstantsSidebar
from ui.mini_dico_panel import MiniDicoPanel
from ui.tabletop_hardcore import HardcoreMixin
from ui.widgets.chat_display import ChatDisplayWidget
from workers.db_helpers import get_max_turn_id, load_rules_for_session, load_saves, get_current_time
from workers.db_worker import DbWorker
from workers.hardcore_worker import HardcoreWorker
from workers.vector_worker import VectorWorker, VectorInitWorker
from workers.timekeeper_worker import TimekeeperWorker
from core.config import load_config, build_llm_from_config
from core.time_system import TimeSystem, CalendarConfig
from core.logger import logger
from core.localization import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from llm_engine.vector_memory import VectorMemory


class TabletopView(HardcoreMixin, QWidget):
    """Main gameplay screen: chat, world-state sidebar, and lore reference.

    Owns the Arbitrator, ChroniclerEngine, and VectorMemory for the active
    session.  All I/O is delegated to workers.

    Signals:
        session_loaded():   Emitted when both meta and lore book are finished loading.
        loading_status(str): Progress message during initialisation.

    Args:
        main_window: Reference to MainWindow for navigation and status updates.
        parent:      Optional Qt parent widget.
    """

    session_loaded = Signal()
    loading_status = Signal(str)
    loading_failed = Signal()

    def __init__(self, main_window: "MainWindow", parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window

        self._db_path: str = ""
        self._save_id: str = ""
        self._turn_id: int = 0
        self._current_time: int = 0
        self._last_chronicle_time: int = 0
        self._time_system = TimeSystem()
        self._universe_system_prompt: str = "You are the narrator of this world."
        self._global_lore: str = ""
        self._first_message: str = ""
        self._first_message_shown: bool = False
        self._player_persona: str = ""
        self._setup_answers: dict[str, str] = {}
        self._history: list = []
        self._mode: str = "Normal"
        self._entities: list[dict] = []
        self._lore_book: list[dict] = []
        self._llm_temperature: float = 0.7
        self._llm_top_p: float = 1.0
        self._llm_verbosity: str = "balanced"
        self._active_session_name: str = ""
        self._arbitrator = None
        self._chronicler = None
        self._vector_memory = None
        self._llm = None
        self._narrative_worker: "NarrativeWorker | None" = None
        self._chronicler_worker: "ChroniclerWorker | None" = None
        self._db_worker: DbWorker | None = None
        self._lore_worker: DbWorker | None = None
        self._vector_worker: VectorWorker | None = None
        self._vector_init_worker: VectorInitWorker | None = None
        self._hardcore_worker: HardcoreWorker | None = None

        # Multi-player Queue System
        self._arbitrator_worker: ArbitratorWorker | None = None

        # Loading state tracking
        self._db_loaded: bool = False
        self._lore_loaded: bool = False
        self._history_loaded: bool = False
        self._vector_loaded: bool = False

        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        
        # --- Top Bar ---
        top_bar_container = QWidget()
        top_bar_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top_bar = QHBoxLayout(top_bar_container)
        top_bar.setContentsMargins(10, 5, 10, 5)

        # 1. Left Section
        left_layout = QHBoxLayout()
        self._save_label = QLabel(tr("no_sessions"))
        self._save_label.setStyleSheet("font-weight: bold; color: #aaa;")
        self._turn_label = QLabel(tr("turn_fmt", count=0))
        self._time_label = QLabel(tr("day_fmt", count=1) + ", 00:00")
        self._time_label.setStyleSheet("color: #4CAF50; font-family: monospace; font-size: 14px;")
        
        left_layout.addWidget(self._save_label)
        self._left_sep1 = QLabel(" | ")
        left_layout.addWidget(self._left_sep1)
        left_layout.addWidget(self._turn_label)
        self._left_sep2 = QLabel(" | ")
        left_layout.addWidget(self._left_sep2)
        left_layout.addWidget(self._time_label)
        top_bar.addLayout(left_layout)

        # 2. Player Selector (NEW Phase 11)
        player_layout = QHBoxLayout()
        player_layout.setSpacing(5)
        self._active_player_label = QLabel(tr("active_player"))
        player_layout.addWidget(self._active_player_label)
        self._player_selector = QComboBox()
        self._player_selector.setFixedWidth(120)
        self._player_selector.addItem("player_1") # Fallback
        player_layout.addWidget(self._player_selector)
        top_bar.addSpacing(20)
        top_bar.addLayout(player_layout)

        # 3. Spacer (Pushes everything to the right)
        top_bar.addStretch()

        # 3. Right Section
        right_layout = QHBoxLayout()
        right_layout.setSpacing(10)
        
        # Align content to the far right to keep it compact
        right_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # Verbosity
        self._verb_label = QLabel(tr("verbosity"))
        self._verb_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed) # Compact label
        right_layout.addWidget(self._verb_label)
        
        self._verbosity_slider = QSlider(Qt.Horizontal)
        self._verbosity_slider.setRange(0, 2)
        self._verbosity_slider.setValue(1)
        self._verbosity_slider.setFixedWidth(70) # Keep slider compact
        self._verbosity_slider.valueChanged.connect(self._on_verbosity_changed)
        right_layout.addWidget(self._verbosity_slider)
        
        self._verbosity_status_label = QLabel(tr("balanced"))
        self._verbosity_status_label.setFixedWidth(60)
        right_layout.addWidget(self._verbosity_status_label)
        
        # Small fixed spacing between verbosity and buttons
        right_layout.addSpacing(15)
        
        # Buttons (Dynamic size based on content)
        self._rewind_btn = QPushButton(tr("rewind"))
        self._rewind_btn.setToolTip("Go back to a previous checkpoint in time.")
        self._hub_btn = QPushButton(tr("hub"))
        self._hub_btn.setToolTip("Return to the main menu (saves automatically).")
        self._rewind_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._hub_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        right_layout.addWidget(self._rewind_btn)
        right_layout.addWidget(self._hub_btn)
        
        top_bar.addLayout(right_layout)
        layout.addWidget(top_bar_container)
        
        # --- Splitter (Main Content) ---
        self._splitter = QSplitter(Qt.Horizontal)
        self._sidebar = ConstantsSidebar()
        self._chat = ChatDisplayWidget()
        self._mini_dico = MiniDicoPanel()
        
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._chat)
        self._splitter.addWidget(self._mini_dico)
        self._splitter.setSizes([220, 660, 260])
        layout.addWidget(self._splitter, 1)

        # --- Connections ---
        self._rewind_btn.clicked.connect(self._on_rewind_clicked)
        self._hub_btn.clicked.connect(self._on_hub_clicked)
        self._chat.message_submitted.connect(self._on_send_message)
        self._chat.variant_requested.connect(self._on_variant_requested)
        self._chat.regenerate_requested.connect(self._on_regenerate_requested)

        # Shortcuts
        from PySide6.QtGui import QShortcut, QKeySequence
        self._undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._undo_shortcut.activated.connect(self._on_rewind_clicked)
        self._redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._redo_shortcut.activated.connect(self._on_rewind_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Refresh all UI text for the current language."""
        if not self._db_path:
            self._save_label.setText(tr("no_sessions"))
        else:
            self._save_label.setText(self._active_session_name)

        self._turn_label.setText(tr("turn_fmt", count=self._turn_id))
        self._time_label.setText(self._format_time(self._current_time))
        self._active_player_label.setText(tr("active_player"))
        self._verb_label.setText(tr("verbosity"))
        self._verbosity_status_label.setText(tr(self._llm_verbosity).capitalize())
        self._rewind_btn.setText(tr("rewind"))
        self._rewind_btn.setToolTip(f"{tr('rewind')} (Ctrl+Z)")
        self._hub_btn.setText(tr("hub"))

        # Sub-widgets
        if hasattr(self._sidebar, "retranslate_ui"): self._sidebar.retranslate_ui()
        if hasattr(self._chat, "retranslate_ui"): self._chat.retranslate_ui()
        if hasattr(self._mini_dico, "retranslate_ui"): self._mini_dico.retranslate_ui()

    def load_session(
        self,
        db_path: str,
        save_id: str,
        player_persona: str = "",
        setup_answers: dict[str, str] | None = None,
    ) -> None:
        """Initialise the tabletop session; constructs workers, never blocks the UI."""
        self._db_path = db_path
        self._save_id = save_id
        # We no longer reset _turn_id and _history to 0/empty here;
        # the DB task load_session_history will provide them.
        self._last_chronicle_time = 0
        self._player_persona = player_persona
        self._setup_answers = setup_answers or {}
        self._global_lore = ""
        self._lore_book = []
        self._first_message_shown = False

        # Synchronise time from DB BEFORE other async loads
        self._resume_turn_id()

        # Reset loading state
        self._db_loaded = False
        self._lore_loaded = False
        self._history_loaded = False
        self._vector_loaded = False

        self._chat.set_send_enabled(False)
        self._save_label.setText(tr("loading_universe"))
        self._turn_label.setText(tr("turn_fmt", count=0))

        # Start Vector Memory Init
        from core.paths import VECTOR_DIR
        vector_dir = str(VECTOR_DIR / self._save_id)
        self._vector_init_worker = VectorInitWorker(vector_dir)
        self._vector_init_worker.ready.connect(self._on_vector_ready)
        self._vector_init_worker.error_occurred.connect(lambda msg: QMessageBox.critical(self, tr("error"), msg))
        self._vector_init_worker.status_update.connect(self.loading_status.emit)
        self._vector_init_worker.start()

        # Start History Load immediately
        self._db_worker = DbWorker(self._db_path)
        self._db_worker.history_loaded.connect(self._on_history_loaded)
        self._db_worker.universe_meta_loaded.connect(self._on_meta_loaded)
        self._db_worker.stats_loaded.connect(self._sidebar.refresh)
        self._db_worker.inventory_loaded.connect(self._sidebar.refresh_inventory)
        self._db_worker.timeline_loaded.connect(self._sidebar.refresh_timeline)
        self._db_worker.entities_loaded.connect(self._on_entities_loaded)
        self._db_worker.lore_book_loaded.connect(self._on_lore_book_loaded)
        self._db_worker.integrity_validated.connect(self._on_integrity_validated)
        self._db_worker.save_complete.connect(self._refresh_after_variant_switch)
        
        self._db_worker.load_session_history(save_id)
        self._db_worker.load_full_universe() # Fetch lore_book + entities
        
    def reload_llm(self) -> None:
        """Construct a fresh LLM instance from the latest settings.json."""
        if not self._db_path:
            return

        cfg = load_config()
        self._llm = build_llm_from_config(cfg)
        
        # Update MiniDico's references immediately
        self._mini_dico.configure(
            self._llm, 
            self._vector_memory, 
            self._save_id,
            lore_book=self._lore_book,
            global_lore=self._global_lore,
            temperature=self._llm_temperature,
            top_p=self._llm_top_p
        )
        
        # Update NarrativeWorker if it exists
        if self._narrative_worker:
            self._narrative_worker.llm = self._llm

    def reload_ui_settings(self) -> None:
        """Update font size and other UI preferences without a full reload."""
        cfg = load_config()
        self._chat.update_font_size(cfg.ui_font_size)

    # ------------------------------------------------------------------
    # Slots (Initialisation)
    # ------------------------------------------------------------------

    @Slot(list, int, str)
    def _on_history_loaded(self, history: list, turn_id: int, difficulty: str) -> None:
        """Background history fetch finished; display it and check for 1st msg."""
        self._history = history
        self._turn_id = turn_id
        self._mode = difficulty
        self._history_loaded = True
        self._turn_label.setText(tr("turn_fmt", count=turn_id))
        self._chat.rebuild_from_history(history)
        self._check_all_loaded()

    @Slot(dict)
    def _on_meta_loaded(self, meta: dict) -> None:
        """Metadata fetch finished; store rules and prompts."""
        self._universe_system_prompt = meta.get("system_prompt", "")
        self._global_lore = meta.get("global_lore", "")
        self._first_message = meta.get("first_message", "")
        
        # Load Calendar
        cal_str = meta.get("calendar_config", "{}")
        self._time_system = TimeSystem(CalendarConfig.from_json(cal_str))
        
        # Refresh UI time label with potentially new calendar config
        self._time_label.setText(self._format_time(self._current_time))
        
        try:
            self._llm_temperature = float(meta.get("llm_temperature", "0.7"))
        except ValueError:
            self._llm_temperature = 0.7
            
        try:
            self._llm_top_p = float(meta.get("llm_top_p", "1.0"))
        except ValueError:
            self._llm_top_p = 1.0

        self._llm_verbosity = meta.get("llm_verbosity", "balanced")
        v_idx = {"short": 0, "balanced": 1, "talkative": 2}.get(self._llm_verbosity, 1)
        self._verbosity_slider.setValue(v_idx)
        self._verbosity_status_label.setText(tr(self._llm_verbosity).capitalize())

        # Update Audio Ambiance Initial State
        self._main_window.update_audio_ambiance("exploration")

        self._db_loaded = True
        self._check_all_loaded()

    @Slot(list)
    def _on_lore_book_loaded(self, lore_book: list[dict]) -> None:
        """Lore book fetch finished."""
        self._lore_book = lore_book
        self._lore_loaded = True
        self._check_all_loaded()

    @Slot(list)
    def _on_entities_loaded(self, entities: list[dict]) -> None:
        """Entities fetch finished; populate player selector."""
        self._entities = entities
        self._player_selector.blockSignals(True)
        self._player_selector.clear()
        players = [e for e in entities if e.get("entity_type") == "player"]
        for p in players:
            self._player_selector.addItem(p["name"], p["entity_id"])
        
        # If no players defined, add a fallback so the UI isn't empty
        if self._player_selector.count() == 0:
            self._player_selector.addItem("Hero", "player_1")
            
        self._player_selector.blockSignals(False)

    @Slot(object)
    def _on_vector_ready(self, vm: "VectorMemory") -> None:
        """Vector memory initialisation finished."""
        self._vector_memory = vm
        self._vector_loaded = True
        self._check_all_loaded()

    def _check_all_loaded(self) -> None:
        """Check if all four background fetches are complete."""
        if self._db_loaded and self._lore_loaded and self._history_loaded and self._vector_loaded:
            # Re-read name from DB path
            self._active_session_name = Path(self._db_path).stem.replace("_", " ").title()
            self._save_label.setText(self._active_session_name)
            self._chat.set_send_enabled(True)

            # Finalize backend objects (LLM)
            cfg = load_config()
            self._llm = build_llm_from_config(cfg)
            
            # Re-configure MiniDico
            self._mini_dico.configure(
                self._llm, 
                self._vector_memory, 
                self._save_id,
                lore_book=self._lore_book,
                global_lore=self._global_lore,
                temperature=self._llm_temperature,
                top_p=self._llm_top_p
            )

            # Show first message if history is empty
            if not self._history and self._first_message and not self._first_message_shown:
                self._first_message_shown = True
                self._show_initial_narrative()

            self.session_loaded.emit()

    def _show_initial_narrative(self) -> None:
        """Display a random variant of the universe's first message."""
        import random
        import re
        
        # Handle variants separated by ---VARIANT--- (case-insensitive, optional spaces)
        if not self._first_message:
            return
            
        variants = [v.strip() for v in re.split(r'\s*---VARIANT---\s*', self._first_message, flags=re.IGNORECASE) if v.strip()]
        
        if not variants:
            variants = [self._first_message.strip()]
            
        # Phase 11: Story Setup Tag Replacement (Case-insensitive, all variants)
        if self._setup_answers:
            for i in range(len(variants)):
                v = variants[i]
                for key, val in self._setup_answers.items():
                    # Case-insensitive replacement of @id
                    pattern = re.compile(f"@{re.escape(key)}", re.IGNORECASE)
                    v = pattern.sub(val, v)
                variants[i] = v

        active_idx = random.randint(0, len(variants) - 1)
        chosen = variants[active_idx]
        
        payload = {
            "active": active_idx,
            "variants": variants
        }
        
        self._chat.append_assistant_separator()
        self._chat.append_token(chosen)
        self._chat.flush_final_buffer()
        self._chat.append_variants_nav(0, active_idx, len(variants), is_latest=True)
        
        # Add to local history (as dict for ChatDisplay)
        self._history.append({
            "turn_id": 0,
            "event_type": "narrative_text",
            "payload": payload
        })
        
        # Persist to Event_Log
        self._db_worker.append_event(
            self._save_id, 0, "narrative_text", "world", payload
        )

    # ------------------------------------------------------------------
    # Slots (Turn Logic)
    # ------------------------------------------------------------------

    @Slot()
    def _on_send_message(self, text: str) -> None:
        """Handle user input: send to Arbitrator, then trigger NarrativeWorker."""
        if not text:
            return

        self._chat.set_send_enabled(False)
        self._chat.append_user_message(text)
        self._history.append({
            "turn_id": self._turn_id,
            "event_type": "user_input",
            "payload": text
        })
        
        # Advance turn count
        self._turn_id += 1
        self._turn_label.setText(tr("turn_fmt", count=self._turn_id))

        # Advance game time (base 15 min per action)
        self._current_time += 15
        self._time_label.setText(self._format_time(self._current_time))

        # 1. Arbitrator Phase
        rules = load_rules_for_session(self._db_path)
        self._arbitrator = ArbitratorEngine(self._db_path, rules)

        player_id = self._player_selector.currentData() or "player_1"
        action = PlayerAction(
            player_id=player_id, 
            text=text,
            save_id=self._save_id,
            turn_id=self._turn_id,
            universe_system_prompt=self._universe_system_prompt,
            history=self._history,
            temperature=self._llm_temperature,
            top_p=self._llm_top_p,
            verbosity_level=self._llm_verbosity
        )

        from workers.narrative_worker import NarrativeWorker
        self._narrative_worker = NarrativeWorker(
            llm=self._llm,
            arbitrator=self._arbitrator,
            vector_memory=self._vector_memory,
            save_id=self._save_id,
            turn_id=self._turn_id,
            action=action,
            history=self._history,
            system_prompt=self._universe_system_prompt,
            global_lore=self._global_lore,
            temperature=self._llm_temperature,
            top_p=self._llm_top_p,
            verbosity=self._llm_verbosity,
            current_time=self._current_time,
            mode=self._mode,
            entities=self._entities
        )
        self._narrative_worker.hero_decision_received.connect(self._chat.append_hero_intent)
        self._narrative_worker.token_received.connect(self._chat.append_token)
        self._narrative_worker.turn_complete.connect(self._on_turn_complete)
        self._narrative_worker.error_occurred.connect(self._on_worker_error)
        self._narrative_worker.status_update.connect(self._main_window.on_status_update)
        self._narrative_worker.start()

    @Slot(object)
    def _on_turn_complete(self, result: object) -> None:
        """Post-turn cleanup: re-enable UI, refresh stats, check Chronicler."""
        from workers.chronicler_worker import ChroniclerWorker
        from core.chronicler import ChroniclerEngine

        # Phase 8 Audit: Force-flush the typewriter buffer once turn logic finishes
        self._chat.flush_final_buffer()

        narrative_text = getattr(result, "narrative_text", "")
        payload = {
            "active": 0,
            "variants": [narrative_text]
        }
        self._history.append({
            "turn_id": self._turn_id,
            "event_type": "narrative_text",
            "payload": payload
        })
        
        # Show variant navigation (Regenerate button)
        self._chat.append_variants_nav(self._turn_id, 0, 1, is_latest=True)

        # Update Audio Ambiance
        game_state_tag = getattr(result, "game_state_tag", "exploration")
        self._main_window.update_audio_ambiance(game_state_tag)

        rejected = getattr(result, "rejected_changes", [])
        if rejected:
            n = len(rejected)
            self._main_window._status_bar.showMessage(
                f"[{n} {tr('actions').lower()} {tr('warning').lower()}]",
                4000,
            )

        self._check_for_player_death(result)
        self._turn_label.setText(tr("turn_fmt", count=self._turn_id))

        # 2. Chronicler Phase (World Simulation)
        cfg = load_config()
        if (self._turn_id - self._main_window._last_chronicle_turn) >= cfg.chronicler_interval:
            self._main_window._last_chronicle_turn = self._turn_id
            
            self._chronicler = ChroniclerEngine(self._db_path)
            self._chronicler_worker = ChroniclerWorker(
                self._chronicler, 
                self._llm, 
                self._save_id, 
                self._turn_id
            )
            self._chronicler_worker.error_occurred.connect(self._on_worker_error)
            self._chronicler_worker.status_update.connect(
                self._main_window.on_status_update
            )
            self._chronicler_worker.start()

        self._chat.set_send_enabled(True)
        
        # Force a DB sync of the sidebar
        self._db_worker.load_full_game_state(self._save_id)

    @Slot(int, int)
    def _on_variant_requested(self, turn_id: int, variant_index: int) -> None:
        """Switch the active narrative variant in the DB and rebuild chat."""
        self._chat.set_send_enabled(False)
        self._db_worker.switch_narrative_variant(self._save_id, turn_id, variant_index)
        # On completion, _refresh_after_variant_switch will be called

    @Slot()
    def _refresh_after_variant_switch(self) -> None:
        """Reload history and rebuild display after a variant switch."""
        self._db_worker.load_session_history(self._save_id)

    @Slot(int)
    def _on_regenerate_requested(self, turn_id: int) -> None:
        """Generate a new alternative response for an existing turn."""
        if not self._history or not self._db_path:
            return
            
        self._chat.set_send_enabled(False)
        self._main_window.on_status_update(tr("generating"))
        
        # 1. Fetch the user action for this turn from history (Event-sourced format)
        user_action_text = ""
        sub_history = []
        
        # Search for the user input that triggered this turn
        for event in self._history:
            if event.get("turn_id") == turn_id and event.get("event_type") == "user_input":
                payload = event.get("payload", "")
                user_action_text = payload.get("text", str(payload)) if isinstance(payload, dict) else str(payload)
            
            # Sub-history is everything BEFORE this turn
            if event.get("turn_id") < turn_id:
                sub_history.append(event)
                 
        if not user_action_text:
             user_action_text = "..." 

        # 2. Run a special regenerate worker
        from workers.regenerate_worker import RegenerateWorker
        rules = load_rules_for_session(self._db_path)
        self._arbitrator = ArbitratorEngine(self._db_path, rules)
        
        player_id = self._player_selector.currentData() or "player_1"
        action = PlayerAction(
            player_id=player_id, 
            text=user_action_text,
            save_id=self._save_id,
            turn_id=turn_id,
            universe_system_prompt=self._universe_system_prompt,
            history=sub_history,
            temperature=self._llm_temperature,
            top_p=self._llm_top_p,
            verbosity_level=self._llm_verbosity
        )

        self._regen_worker = RegenerateWorker(
            llm=self._llm,
            db_path=self._db_path,
            save_id=self._save_id,
            turn_id=turn_id,
            history=sub_history,
            system_prompt=self._universe_system_prompt,
            user_message=action.text,
            temperature=self._llm_temperature + 0.1,
            top_p=self._llm_top_p,
            verbosity_level=self._llm_verbosity
        )
        self._regen_worker.token_received.connect(self._chat.append_token)
        self._regen_worker.regenerate_complete.connect(self._refresh_after_variant_switch)
        self._regen_worker.error_occurred.connect(self._on_worker_error)
        self._regen_worker.start()

    # ------------------------------------------------------------------
    # Slots (Toolbar)
    # ------------------------------------------------------------------

    @Slot()
    def _on_rewind_clicked(self) -> None:
        """Open CheckpointDialog and trigger RewindWorker."""
        self._db_worker.load_checkpoints(self._save_id)
        self._db_worker.checkpoints_loaded.connect(self._show_rewind_dialog)

    @Slot(list)
    def _show_rewind_dialog(self, turn_ids: list[int]) -> None:
        """Open the dialog now that turn IDs are fetched."""
        self._db_worker.checkpoints_loaded.disconnect(self._show_rewind_dialog)
        
        if not turn_ids:
            QMessageBox.information(self, tr("rewind"), tr("no_checkpoints"))
            return

        dialog = CheckpointDialog(turn_ids, parent=self)
        if dialog.exec() == QDialog.Accepted:
            target_id = dialog.selected_turn_id()
            if target_id is not None:
                self._chat.set_send_enabled(False)
                self._main_window.on_status_update(f"{tr('rewind')}...")
                self._db_worker.rewind_to_checkpoint(self._save_id, target_id)
                self._db_worker.rewind_complete.connect(self._on_rewind_done)

    @Slot()
    def _on_rewind_done(self) -> None:
        """Reload state after a successful rewind."""
        self._db_worker.rewind_complete.disconnect(self._on_rewind_done)
        self._resume_turn_id()
        self._db_worker.load_session_history(self._save_id)
        self._db_worker.load_stats(self._save_id)
        self._chat.set_send_enabled(True)
        self._main_window.on_status_update(tr("ready"))

    @Slot()
    def _on_hub_clicked(self) -> None:
        """Stop all workers and return to HubView."""
        self._chat.set_send_enabled(False)
        self._main_window.show_hub()

    # ------------------------------------------------------------------
    # Error Handling
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        """Display background error to the user."""
        self._chat.set_send_enabled(True)
        self._main_window.on_status_update(tr("error") + ": " + message)
        
        if "connection" in message.lower() or "404" in message:
            QMessageBox.critical(
                self, 
                tr("error"),
                f"{tr('llm_unreachable')}\n\n{tr('ollama_guide')}"
            )

    @Slot(bool)
    def _on_integrity_validated(self, ok: bool) -> None:
        if not ok:
            QMessageBox.warning(self, tr("integrity_warning"), tr("integrity_mismatch"))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_verbosity_changed(self, value: int) -> None:
        """Update verbosity level and save to DB."""
        v_map = {0: "short", 1: "balanced", 2: "talkative"}
        self._llm_verbosity = v_map.get(value, "balanced")
        self._verbosity_status_label.setText(tr(self._llm_verbosity).capitalize())
        
        # Persist to universe meta
        meta = {"llm_verbosity": self._llm_verbosity}
        self._db_worker.save_universe_meta(meta)

    def _resume_turn_id(self) -> None:
        """Read the highest existing turn_id from Event_Log to resume saves."""
        turn_id = get_max_turn_id(self._db_path, self._save_id)
        if turn_id > 0:
            self._turn_id = turn_id
            self._turn_label.setText(tr("turn_fmt", count=self._turn_id))

        current_time = get_current_time(self._db_path, self._save_id)
        self._time_label.setText(self._format_time(current_time))
        self._current_time = current_time
        self._last_chronicle_time = current_time

    def _format_time(self, total_minutes: int) -> str:
        """Format total minutes into localized custom calendar string."""
        return self._time_system.get_time_string(total_minutes)
