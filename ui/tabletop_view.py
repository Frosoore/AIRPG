"""
ui/tabletop_view.py

Tabletop screen - the main gameplay interface for AIRPG.

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

from ui.checkpoint_dialog import CheckpointDialog
from ui.constants_sidebar import ConstantsSidebar
from ui.mini_dico_panel import MiniDicoPanel
from ui.tabletop_hardcore import HardcoreMixin
from ui.widgets.chat_display import ChatDisplayWidget
from workers.db_helpers import get_max_turn_id, load_rules_for_session, load_saves, get_current_time
from workers.db_worker import DbWorker
from workers.hardcore_worker import HardcoreWorker
from workers.vector_worker import VectorWorker
from workers.timekeeper_worker import TimekeeperWorker
from core.logger import logger

if TYPE_CHECKING:
    from ui.main_window import MainWindow


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
        self._universe_system_prompt: str = "You are the narrator of this world."
        self._global_lore: str = ""
        self._first_message: str = ""
        self._first_message_shown: bool = False
        self._player_persona: str = ""
        self._history: list = []
        self._lore_book: list[dict] = []
        self._llm_temperature: float = 0.7
        self._llm_top_p: float = 1.0
        self._llm_verbosity: str = "balanced"
        self._arbitrator = None
        self._chronicler = None
        self._vector_memory = None
        self._llm = None
        self._narrative_worker: "NarrativeWorker | None" = None
        self._chronicler_worker: "ChroniclerWorker | None" = None
        self._db_worker: DbWorker | None = None
        self._lore_worker: DbWorker | None = None
        self._vector_worker: VectorWorker | None = None
        self._hardcore_worker: HardcoreWorker | None = None

        # Multi-player Queue System
        self._arbitrator_worker: ArbitratorWorker | None = None

        # Loading state tracking
        self._db_loaded: bool = False
        self._lore_loaded: bool = False
        self._history_loaded: bool = False

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
        self._save_label = QLabel("No session loaded")
        self._save_label.setStyleSheet("font-weight: bold; color: #aaa;")
        self._turn_label = QLabel("Turn: 0")
        self._time_label = QLabel("Day 1, 00:00")
        self._time_label.setStyleSheet("color: #4CAF50; font-family: monospace; font-size: 14px;")
        
        left_layout.addWidget(self._save_label)
        left_layout.addWidget(QLabel(" | "))
        left_layout.addWidget(self._turn_label)
        left_layout.addWidget(QLabel(" | "))
        left_layout.addWidget(self._time_label)
        top_bar.addLayout(left_layout)

        # 2. Player Selector (NEW Phase 11)
        player_layout = QHBoxLayout()
        player_layout.setSpacing(5)
        player_layout.addWidget(QLabel("Active Player:"))
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
        verb_label = QLabel("AI Verbosity:")
        verb_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed) # Compact label
        right_layout.addWidget(verb_label)
        
        self._verbosity_slider = QSlider(Qt.Horizontal)
        self._verbosity_slider.setRange(0, 2)
        self._verbosity_slider.setValue(1)
        self._verbosity_slider.setFixedWidth(70) # Keep slider compact
        self._verbosity_slider.valueChanged.connect(self._on_verbosity_changed)
        right_layout.addWidget(self._verbosity_slider)
        
        self._verbosity_label = QLabel("Balanced")
        self._verbosity_label.setFixedWidth(60)
        right_layout.addWidget(self._verbosity_label)
        
        # Small fixed spacing between verbosity and buttons
        right_layout.addSpacing(15)
        
        # Buttons (Dynamic size based on content)
        rewind_btn = QPushButton("Rewind")
        hub_btn = QPushButton("Hub")
        rewind_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        hub_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        right_layout.addWidget(rewind_btn)
        right_layout.addWidget(hub_btn)
        
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
        rewind_btn.clicked.connect(self._on_rewind_clicked)
        hub_btn.clicked.connect(self._on_hub_clicked)
        self._chat.message_submitted.connect(self._on_send_message)
        self._chat.variant_requested.connect(self._on_variant_requested)
        self._chat.regenerate_requested.connect(self._on_regenerate_requested)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_session(
        self,
        db_path: str,
        save_id: str,
        player_persona: str = "",
    ) -> None:
        """Initialise the tabletop session; constructs workers, never blocks the UI."""
        self._db_path = db_path
        self._save_id = save_id
        # We no longer reset _turn_id and _history to 0/empty here; 
        # the DB task load_session_history will provide them.
        self._last_chronicle_time = 0
        self._player_persona = player_persona
        self._global_lore = ""
        self._lore_book = []
        self._first_message_shown = False

        # Reset loading state
        self._db_loaded = False
        self._lore_loaded = False
        self._history_loaded = False

        self._chat.set_send_enabled(False)
        self._save_label.setText("Loading...")
        self._turn_label.setText("Turn: 0")

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
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self.loading_status.emit)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        
        # Trigger background integrity check
        self._db_worker.validate_integrity(self._save_id)
        
        # Phase 1: Asynchronous VectorMemory Init (loads heavy model)
        from workers.vector_worker import VectorInitWorker
        vector_dir = str(Path.home() / "AIRPG" / "vector" / self._save_id)
        self._vector_init_worker = VectorInitWorker(vector_dir)
        self._vector_init_worker.ready.connect(self._on_vector_memory_ready)
        self._vector_init_worker.error_occurred.connect(self._on_worker_error)
        self._vector_init_worker.status_update.connect(self.loading_status.emit)
        self._vector_init_worker.start()

    @Slot(object)
    def _on_vector_memory_ready(self, vector_memory: object) -> None:
        """Phase 2: Finish backend creation once VectorMemory is ready."""
        self._vector_memory = vector_memory
        self._build_backend_objects_post_vector()

        self._mini_dico.configure(
            self._llm, self._vector_memory, self._save_id, lore_book=[], global_lore=""
        )

        # Single atomic load task for EVERYTHING
        self._db_worker.load_full_universe(save_id=self._save_id)

        self._resume_turn_id()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_send_message(self, user_text: str) -> None:
        """Queue player input into the ArbitratorWorker."""
        if self._arbitrator_worker is None:
            QMessageBox.warning(self, "Session", "No active session. Return to Hub.")
            return

        # Phase 11: Multi-player Queue.
        player_id = self._player_selector.currentText() or "player_1"

        # 1. Local feedback: display immediately
        self._chat.append_user_message(f"[{player_id}] {user_text}")
        
        # 2. Add to history with name for multi-player context
        self._history.append({"role": "user", "content": user_text, "name": player_id})

        # 3. Create action object and enqueue
        self._turn_id += 1 # Pre-emptive turn_id increment
        action = PlayerAction(
            player_id=player_id,
            text=user_text,
            save_id=self._save_id,
            turn_id=self._turn_id,
            universe_system_prompt=self._build_combined_system_prompt(),
            history=self._history[:-1], # Context up to this message
            temperature=self._llm_temperature,
            top_p=self._llm_top_p,
            verbosity_level=self._llm_verbosity
        )
        
        self._arbitrator_worker.enqueue(action)
        
        # 4. Locking: disable input for this specific player
        # (For now, we just disable the main chat input)
        self._chat.set_send_enabled(False)

    def _on_queue_token(self, token: str, player_id: str) -> None:
        """Typewriter effect for the specific player whose turn is resolving."""
        # Note: If multiple players are active, ChatDisplayWidget might need
        # to know which message bubble to append to. For now, it appends to latest.
        self._chat.append_token(token)

    def _on_queue_turn_complete(self, result: object, player_id: str) -> None:
        """Handle completion of a queued turn."""
        self._on_turn_complete(result)
        # Re-enable input once processed
        self._chat.set_send_enabled(True)

    def _on_queue_error(self, message: str, player_id: str) -> None:
        """Handle errors in the queue."""
        self._on_worker_error(message)
        self._chat.set_send_enabled(True)

    @Slot(int)
    def _on_regenerate_requested(self, turn_id: int) -> None:
        """Generate a new variant for the given turn."""
        if turn_id < self._turn_id:
            QMessageBox.warning(
                self,
                "Temporal Warning",
                "You can only regenerate the most recent turn. "
                "To regenerate this turn, you must rewind to it first."
            )
            return

        if self._narrative_worker and self._narrative_worker.isRunning():
            self._main_window.on_status_update("Already generating - please wait.")
            return

        # Disable UI during generation
        self._chat.set_send_enabled(False)
        self._chat.append_assistant_separator()
        self._chat.begin_turn(turn_id)

        # Extract the user message for this turn from the local history
        user_message = ""
        last_user_idx = -1
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i]["role"] == "user":
                last_user_idx = i
                break
                
        if last_user_idx != -1:
            user_message = self._history[last_user_idx]["content"]
            worker_history = self._history[:last_user_idx]
        else:
            worker_history = []
            
        system_prompt = self._build_combined_system_prompt()

        from workers.regenerate_worker import RegenerateWorker
        self._regenerate_worker = RegenerateWorker(
            llm=self._llm,
            db_path=self._db_path,
            save_id=self._save_id,
            turn_id=turn_id,
            history=worker_history,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=self._llm_temperature,
            top_p=self._llm_top_p,
            verbosity_level=self._llm_verbosity,
        )
        self._regenerate_worker.token_received.connect(self._chat.append_token)
        self._regenerate_worker.regenerate_complete.connect(self._on_regenerate_complete)
        self._regenerate_worker.error_occurred.connect(self._on_worker_error)
        self._regenerate_worker.status_update.connect(self._main_window.on_status_update)
        self._regenerate_worker.start()

    @Slot(str)
    def _on_regenerate_complete(self, text: str) -> None:
        """Handle completion of regeneration."""
        self._chat.flush_final_buffer()
        self._main_window.on_status_update("Regeneration complete.")
        
        # Update our local history with the new text
        if self._history and self._history[-1]["role"] == "assistant":
            self._history[-1]["content"] = text
        else:
            self._history.append({"role": "assistant", "content": text})
            
        # Full refresh to properly show the new variants nav
        self._refresh_after_variant_switch()

    @Slot(bool, dict)
    def _on_integrity_validated(self, passed: bool, mismatches: dict) -> None:
        """Handle results of the background state integrity check."""
        if not passed:
            count = sum(len(m) for m in mismatches.values())
            logger.warning(f"INTEGRITY FAILURE: {count} stat mismatches detected in State_Cache.")
            QMessageBox.warning(
                self,
                "Data Integrity Warning",
                "<b>Minor data corruption detected in the state cache.</b><br><br>"
                f"The system found {count} inconsistencies between your history and current stats.<br><br>"
                "<b>Recommendation:</b> Use 'Rewind' to return to a previous turn, "
                "which will automatically rebuild and fix the cache.",
            )

    @Slot(object)
    def _on_turn_complete(self, result: object) -> None:
        """Post-turn cleanup: re-enable UI, refresh stats, check Chronicler."""
        from workers.chronicler_worker import ChroniclerWorker
        from core.chronicler import ChroniclerEngine

        # Phase 8 Audit: Force-flush the typewriter buffer once turn logic finishes
        self._chat.flush_final_buffer()

        narrative_text = getattr(result, "narrative_text", "")
        self._history.append({"role": "assistant", "content": narrative_text})

        # Update Audio Ambiance
        game_state_tag = getattr(result, "game_state_tag", "exploration")
        self._main_window.update_audio_ambiance(game_state_tag)

        rejected = getattr(result, "rejected_changes", [])
        if rejected:
            n = len(rejected)
            self._main_window._status_bar.showMessage(
                f"[{n} action{'s' if n != 1 else ''} rejected by game rules]",
                4000,
            )

        self._check_for_player_death(result)
        self._turn_label.setText(f"Turn: {self._turn_id}")

        # Phase 11: Display variant navigation (even if only 1 variant exists for now)
        # Note: ChatDisplayWidget.append_variants_nav only shows UI if total > 1.
        self._chat.append_variants_nav(self._turn_id, 0, 1, is_latest=True)

        # Refresh stats and trigger background snapshot if needed
        self._db_worker = DbWorker(self._db_path)
        self._db_worker.stats_loaded.connect(self._sidebar.refresh)
        self._db_worker.inventory_loaded.connect(self._sidebar.refresh_inventory)
        self._db_worker.timeline_loaded.connect(self._sidebar.refresh_timeline)
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        self._db_worker.load_full_game_state(self._save_id)

        # Periodically snapshot (every 20 turns) - Decoupled from append_event for performance
        if self._turn_id > 0 and self._turn_id % 20 == 0:
            self._db_worker.take_snapshot_async(self._save_id, self._turn_id)

        # Launch Timekeeper
        if narrative_text.strip():
            if not (hasattr(self, "_timekeeper_worker") and self._timekeeper_worker.isRunning()):
                self._timekeeper_worker = TimekeeperWorker(
                    llm_backend=self._llm,
                    db_path=self._db_path,
                    save_id=self._save_id,
                    turn_id=self._turn_id,
                    narrative_text=narrative_text
                )
                self._timekeeper_worker.finished.connect(self._on_timekeeper_complete)
                self._timekeeper_worker.error.connect(lambda msg: print(f"Timekeeper Error: {msg}"))
                self._timekeeper_worker.start()

    @Slot(object)
    def _on_chronicle_complete(self, result: object) -> None:
        """Post-Chronicler: update last chronicle time and refresh sidebar."""
        from workers.db_helpers import get_current_time
        self._last_chronicle_time = get_current_time(self._db_path, self._save_id)
        
        self._db_worker = DbWorker(self._db_path)
        self._db_worker.stats_loaded.connect(self._sidebar.refresh)
        self._db_worker.inventory_loaded.connect(self._sidebar.refresh_inventory)
        self._db_worker.timeline_loaded.connect(self._sidebar.refresh_timeline)
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        self._db_worker.load_full_game_state(self._save_id)

    @Slot(int)
    def _on_verbosity_changed(self, value: int) -> None:
        """Update verbosity level and save to DB."""
        v_map = {0: "short", 1: "balanced", 2: "talkative"}
        self._llm_verbosity = v_map.get(value, "balanced")
        self._verbosity_label.setText(self._llm_verbosity.capitalize())
        
        # Save to DB asynchronously
        if self._db_path:
            meta = {"llm_verbosity": self._llm_verbosity}
            worker = DbWorker(self._db_path)
            worker.save_universe_meta(meta)

    @Slot()
    def _on_rewind_clicked(self) -> None:
        """Load checkpoints via DbWorker, then show CheckpointDialog."""
        if not self._save_id:
            return
        worker = DbWorker(self._db_path)
        worker.checkpoints_loaded.connect(self._on_checkpoints_loaded)
        worker.error_occurred.connect(self._on_worker_error)
        worker.load_checkpoints(self._save_id)
        # Keep reference alive until the signal fires
        self._checkpoint_list_worker = worker

    @Slot(list)
    def _on_checkpoints_loaded(self, checkpoints: list) -> None:
        """Open CheckpointDialog with the available turn IDs."""
        if not checkpoints:
            QMessageBox.information(
                self, "Rewind", "No checkpoints available yet."
            )
            return
        dialog = CheckpointDialog(checkpoints, parent=self)
        if dialog.exec() == QDialog.Accepted:
            target = dialog.selected_turn_id()
            if target is not None:
                self._execute_rewind(target)

    def _execute_rewind(self, target_turn_id: int) -> None:
        """Start DB rewind worker, then chain VectorMemory rollback."""
        self._chat.set_send_enabled(False)
        rewind_worker = DbWorker(self._db_path)
        rewind_worker.rewind_complete.connect(
            lambda summary: self._on_rewind_complete(summary, target_turn_id)
        )
        rewind_worker.error_occurred.connect(self._on_worker_error)
        rewind_worker.status_update.connect(self._main_window.on_status_update)
        rewind_worker.execute_rewind(self._save_id, target_turn_id)
        self._rewind_db_worker = rewind_worker

    def _on_rewind_complete(self, summary: dict, target_turn_id: int) -> None:
        """After DB rewind: trigger VectorMemory rollback."""
        if self._vector_memory is None:
            self._finalise_rewind(target_turn_id)
            return

        self._vector_worker = VectorWorker(
            vector_memory=self._vector_memory,
            save_id=self._save_id,
            target_turn_id=target_turn_id,
        )
        self._vector_worker.rollback_complete.connect(
            lambda count: self._finalise_rewind(target_turn_id)
        )
        self._vector_worker.error_occurred.connect(self._on_worker_error)
        self._vector_worker.status_update.connect(self._main_window.on_status_update)
        self._vector_worker.start()

    def _finalise_rewind(self, target_turn_id: int) -> None:
        """Update session state and UI after a completed rewind."""
        self._turn_id = target_turn_id
        self._turn_label.setText(f"Turn: {self._turn_id}")
        self._chat.set_send_enabled(True)

        # Rebuild history and stats asynchronously
        self._db_worker = DbWorker(self._db_path)
        self._db_worker.history_loaded.connect(self._on_history_loaded)
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        self._db_worker.load_session_history(self._save_id)
        
        self._stats_worker = DbWorker(self._db_path)
        self._stats_worker.stats_loaded.connect(self._sidebar.refresh)
        self._stats_worker.inventory_loaded.connect(self._sidebar.refresh_inventory)
        self._stats_worker.timeline_loaded.connect(self._sidebar.refresh_timeline)
        self._stats_worker.error_occurred.connect(self._on_worker_error)
        self._stats_worker.load_full_game_state(self._save_id)

    @Slot(int, int)
    def _on_variant_requested(self, turn_id: int, index: int) -> None:
        """Temporal Enforcer: Handle variant switch with optional timeline rewind."""
        if turn_id < self._turn_id:
            reply = QMessageBox.warning(
                self,
                "Temporal Warning",
                f"Changing a past message from turn {turn_id} will rewind the timeline and "
                "DELETE all subsequent turns. Proceed?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
            
            # Execute rewind first
            self._execute_rewind_for_variant(turn_id, index)
        else:
            # For the current turn, we still want to update VectorMemory
            # We must first clear the existing chunk for this turn in VectorMemory
            self._rollback_vector_for_variant(turn_id, index)

    def _execute_rewind_for_variant(self, target_turn_id: int, index: int) -> None:
        """Start DB rewind worker, then chain variant update."""
        self._chat.set_send_enabled(False)
        self._db_worker = DbWorker(self._db_path)
        # Chain into vector rollback before variant update
        self._db_worker.rewind_complete.connect(
            lambda summary: self._rollback_vector_for_variant(target_turn_id, index)
        )
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        self._db_worker.execute_rewind(self._save_id, target_turn_id)

    def _rollback_vector_for_variant(self, target_turn_id: int, index: int) -> None:
        if self._vector_memory is None:
            self._execute_variant_switch(target_turn_id, index)
            return

        from workers.vector_worker import VectorWorker
        # We rollback to target_turn_id - 1 so that we can re-embed the new variant of target_turn_id
        self._vector_variant_worker = VectorWorker(
            vector_memory=self._vector_memory,
            save_id=self._save_id,
            target_turn_id=target_turn_id - 1,
        )
        self._vector_variant_worker.rollback_complete.connect(
            lambda count: self._execute_variant_switch(target_turn_id, index)
        )
        self._vector_variant_worker.error_occurred.connect(self._on_worker_error)
        self._vector_variant_worker.status_update.connect(self._main_window.on_status_update)
        self._vector_variant_worker.start()

    def _execute_variant_switch(self, turn_id: int, index: int) -> None:
        """Update the active index in DB and rebuild UI."""
        self._turn_id = turn_id 
        self._turn_label.setText(f"Turn: {self._turn_id}")

        self._db_worker = DbWorker(self._db_path)
        self._db_worker.variant_updated.connect(
            lambda text: self._reembed_variant(turn_id, text)
        )
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        self._db_worker.update_narrative_variant(self._save_id, turn_id, index)

    def _reembed_variant(self, turn_id: int, text: str) -> None:
        """After variant update in DB, update VectorMemory if it exists."""
        if self._vector_memory is None:
            self._refresh_after_variant_switch()
            return

        from workers.vector_worker import VectorEmbedWorker
        self._vector_embed_worker = VectorEmbedWorker(
            vector_memory=self._vector_memory,
            save_id=self._save_id,
            turn_id=turn_id,
            text=text
        )
        self._vector_embed_worker.embed_complete.connect(
            lambda _: self._refresh_after_variant_switch()
        )
        self._vector_embed_worker.error_occurred.connect(self._on_worker_error)
        self._vector_embed_worker.status_update.connect(self._main_window.on_status_update)
        self._vector_embed_worker.start()

    def _refresh_after_variant_switch(self) -> None:
        """Reload history and refresh UI after variant update."""
        self._db_worker = DbWorker(self._db_path)
        self._db_worker.history_loaded.connect(self._on_history_loaded)
        self._db_worker.error_occurred.connect(self._on_worker_error)
        self._db_worker.status_update.connect(self._main_window.on_status_update)
        self._db_worker.load_session_history(self._save_id)

        self._stats_worker = DbWorker(self._db_path)
        self._stats_worker.stats_loaded.connect(self._sidebar.refresh)
        self._stats_worker.inventory_loaded.connect(self._sidebar.refresh_inventory)
        self._stats_worker.timeline_loaded.connect(self._sidebar.refresh_timeline)
        self._stats_worker.error_occurred.connect(self._on_worker_error)
        self._stats_worker.load_full_game_state(self._save_id)
    @Slot(str, str)
    def _on_queue_error(self, message: str, player_id: str) -> None:
        """Handle errors from the background ArbitratorWorker queue."""
        logger.error(f"Queue Error for {player_id}: {message}")
        self._on_worker_error(message)

    @Slot()
    def _on_hub_clicked(self) -> None:
        """Navigate back to the Hub screen."""
        if self._arbitrator_worker:
            self._arbitrator_worker.stop()
            self._arbitrator_worker.wait()
            
        self._main_window.update_audio_ambiance("") # Stop audio
        self._main_window.show_hub()

    @Slot(list)
    def _on_entities_loaded(self, entities: list[dict]) -> None:
        """Populate the player selector with entities of type 'player'."""
        self._player_selector.clear()
        player_entities = [e for e in entities if e.get("entity_type") == "player"]
        
        if not player_entities:
            self._player_selector.addItem("player_1")
        else:
            for p in player_entities:
                self._player_selector.addItem(p["entity_id"])

    @Slot(list)
    def _on_lore_book_loaded(self, lore_book: list) -> None:
        """Store the loaded Lore Book and push it to MiniDicoPanel."""
        self._lore_book = lore_book
        self._mini_dico.configure(
            self._llm,
            self._vector_memory,
            self._save_id,
            lore_book=lore_book,
            global_lore=self._global_lore,
            temperature=self._llm_temperature,
            top_p=self._llm_top_p,
        )
        self._lore_loaded = True
        self._check_loading_complete()

    @Slot(dict)
    def _on_meta_loaded(self, meta: dict) -> None:
        """Extract system prompt, global lore, and update the save label."""
        self._universe_system_prompt = meta.get(
            "system_prompt",
            "You are the narrator of this world.",
        )
        self._global_lore = meta.get("global_lore", "")
        self._first_message = meta.get("first_message", "")
        
        try:
            self._llm_temperature = float(meta.get("llm_temperature", "0.7"))
        except ValueError:
            self._llm_temperature = 0.7
            
        try:
            self._llm_top_p = float(meta.get("llm_top_p", "1.0"))
        except ValueError:
            self._llm_top_p = 1.0
            
        self._llm_verbosity = meta.get("llm_verbosity", "balanced")
        v_map = {"short": 0, "balanced": 1, "talkative": 2}
        self._verbosity_slider.setValue(v_map.get(self._llm_verbosity, 1))
        self._verbosity_label.setText(self._llm_verbosity.capitalize())

        # Push global_lore to MiniDicoPanel immediately
        self._mini_dico.configure(
            self._llm,
            self._vector_memory,
            self._save_id,
            lore_book=self._lore_book,
            global_lore=self._global_lore,
            temperature=self._llm_temperature,
            top_p=self._llm_top_p,
        )

        universe_name = meta.get("universe_name", "Universe")
        saves = load_saves(self._db_path)
        save_info = next((s for s in saves if s["save_id"] == self._save_id), None)
        if save_info:
            player = save_info.get("player_name", "Hero")
            diff = save_info.get("difficulty", "Normal")
            self._save_label.setText(f"{universe_name} - {player} [{diff}]")
        else:
            self._save_label.setText(universe_name)

        self._db_loaded = True
        self._check_loading_complete()

    @Slot(list, int)
    def _on_history_loaded(self, history: list[dict], max_turn_id: int) -> None:
        """Process historical events to rebuild chat and LLM history."""
        temp_history = []
        # Convert internal DB format to LLMMessage list format
        for event in history:
            etype = event["event_type"]
            payload = event["payload"]
            
            text = ""
            if isinstance(payload, dict):
                if "variants" in payload:
                    active_idx = payload.get("active", 0)
                    variants = payload.get("variants", [])
                    if 0 <= active_idx < len(variants):
                        text = variants[active_idx]
                else:
                    text = payload.get("text", "")
            else:
                text = str(payload)

            if etype == "user_input":
                name = payload.get("player_id", "player_1") if isinstance(payload, dict) else "player_1"
                temp_history.append({"role": "user", "content": text, "name": name})
            elif etype == "narrative_text":
                temp_history.append({"role": "assistant", "content": text})

        # Logic to preserve the First Message if it was just shown but not yet in DB
        if not temp_history and self._first_message_shown:
            # Re-read it from memory since DB hasn't committed yet
            if self._history and self._history[0]["role"] == "assistant":
                temp_history = [self._history[0]]

        self._history = temp_history
        self._turn_id = max_turn_id
        self._turn_label.setText(f"Turn: {self._turn_id}")
        
        # Rebuild visual chat display
        self._chat.rebuild_from_history(history)
        
        # If we had a shown first message not in history, re-inject it into chat display
        if self._first_message_shown and not any(h.get("turn_id") == 0 for h in history):

            # Since rebuild_from_history wiped it, we manually re-add it to chat UI.
            if self._history and self._history[0]["role"] == "assistant":
                text = self._history[0]["content"]
                
                # Recover variants metadata if possible
                active_idx = 0
                total_vars = 1
                if hasattr(self, "_first_msg_payload") and isinstance(self._first_msg_payload, dict):
                    active_idx = self._first_msg_payload.get("active", 0)
                    total_vars = len(self._first_msg_payload.get("variants", []))

                self._chat.append_assistant_separator()
                self._chat._insert_instant_parsed_text(text)
                self._chat.append_variants_nav(0, active_idx, total_vars, is_latest=(max_turn_id == 0))
                self._chat.flush_final_buffer()

        self._history_loaded = True
        self._check_loading_complete()

    def _check_loading_complete(self) -> None:
        """Emit session_loaded once all critical DB tasks are finished."""
        if self._db_loaded and self._lore_loaded and self._history_loaded:
            # If this is a brand new save (no history yet), show and LOG the First Message
            if not self._history and self._first_message and not self._first_message_shown:
                import json
                self._first_message_shown = True

                payload_dict = {}
                text_to_show = self._first_message
                active_idx = 0
                total_vars = 1

                try:
                    payload_dict = json.loads(self._first_message)
                    if isinstance(payload_dict, dict) and "variants" in payload_dict:
                        variants = payload_dict["variants"]
                        active_idx = payload_dict.get("active", 0)
                        total_vars = len(variants)
                        if 0 <= active_idx < total_vars:
                            text_to_show = variants[active_idx]
                except Exception:
                    payload_dict = {"text": self._first_message}
                
                # Store payload for re-injection if history reloads before DB commit
                self._first_msg_payload = payload_dict

                self._chat.append_assistant_separator()

                # Render using the correct variant
                self._chat._insert_instant_parsed_text(text_to_show)
                self._chat.append_variants_nav(0, active_idx, total_vars, is_latest=True)
                self._chat.flush_final_buffer()

                self._history.append({"role": "assistant", "content": text_to_show})

                # Persist it so it's there next time we resume
                worker = DbWorker(self._db_path)
                worker.append_event(
                    self._save_id, 0, "narrative_text", "player",
                    payload_dict
                )
                # Keep reference to avoid GC
                self._first_msg_worker = worker

            self._chat.set_send_enabled(True)
            self.session_loaded.emit()
    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        """Show a critical error with LLM-specific guidance when appropriate."""
        self.loading_failed.emit()
        if "LLM unreachable" in message or "Cannot connect to Ollama" in message:
            from core.config import load_config
            cfg = load_config()
            url = cfg.ollama_base_url
            QMessageBox.critical(
                self,
                "LLM Unreachable",
                f"<b>The LLM server is not responding.</b><br><br>"
                f"Configured URL: <code>{url}</code><br><br>"
                "<b>To start Ollama:</b><br>"
                "1. Open a terminal<br>"
                "2. Run: <code>ollama serve</code><br>"
                "3. Retry your message.<br><br>"
                "Or switch to Gemini Cloud in <b>File → Settings</b>.",
            )
        else:
            QMessageBox.critical(self, "Error", message)
        self._chat.set_send_enabled(True)
        self._main_window.on_status_update("Error.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def reload_llm(self) -> None:
        """Rebuild LLM from saved config; push to arbitrator/chronicler/mini_dico."""
        if not self._db_path:
            return
        try:
            from core.config import load_config, build_llm_from_config
            cfg = load_config()
            new_llm = build_llm_from_config(cfg)
        except Exception:
            return

        self._llm = new_llm
        if self._arbitrator is not None:
            self._arbitrator._llm = new_llm
        if self._chronicler is not None:
            self._chronicler._llm = new_llm
            
        # Also reload meta to reflect any parameter changes (temp, top_p)
        if self._db_worker is None:
            self._db_worker = DbWorker(self._db_path)
            self._db_worker.universe_meta_loaded.connect(self._on_meta_loaded)
        self._db_worker.load_universe_meta()

        if self._save_id:
            self._mini_dico.configure(
                new_llm,
                self._vector_memory,
                self._save_id,
                lore_book=self._lore_book,
                global_lore=self._global_lore,
                temperature=self._llm_temperature,
                top_p=self._llm_top_p,
            )
        self._main_window.on_status_update("LLM backend reloaded.")

    def reload_ui_settings(self) -> None:
        """Update UI elements that depend on AppConfig."""
        from core.config import load_config
        cfg = load_config()
        self._chat.update_font_size(cfg.ui_font_size)

    def _build_backend_objects_post_vector(self) -> None:
        """Construct Arbitrator, ChroniclerEngine, LLM.

        Called after VectorMemory is ready.
        """
        from core.arbitrator import Arbitrator
        from core.chronicler import ChroniclerEngine
        from core.config import load_config, build_llm_from_config
        from core.rules_engine import RulesEngine
        from database.event_sourcing import EventSourcer
        from database.modifier_processor import ModifierProcessor
        from llm_engine.universal_client import UniversalClient

        try:
            cfg = load_config()
            self._llm = build_llm_from_config(cfg)
            self._chronicler_interval = cfg.chronicler_interval
        except (ValueError, Exception):
            # Fallback to a generic local OpenAI-compatible endpoint (like Ollama/Kobold default)
            self._llm = UniversalClient(
                base_url="http://localhost:11434/v1",
                api_key="",
                model_name="llama3.2"
            )
            self._chronicler_interval = 50

        es = EventSourcer(self._db_path)
        mp = ModifierProcessor(self._db_path)
        rules = self._load_rules()
        re = RulesEngine(rules)

        self._arbitrator = Arbitrator(
            llm=self._llm,
            event_sourcer=es,
            modifier_processor=mp,
            rules_engine=re,
            vector_memory=self._vector_memory,
            db_path=self._db_path,
        )

        # Start the background sequential worker for multi-player
        self._arbitrator_worker = ArbitratorWorker(self._arbitrator)
        self._arbitrator_worker.signals.token_received.connect(self._on_queue_token)
        self._arbitrator_worker.signals.turn_complete.connect(self._on_queue_turn_complete)
        self._arbitrator_worker.signals.error_occurred.connect(self._on_queue_error)
        self._arbitrator_worker.signals.status_update.connect(self._main_window.on_status_update)
        self._arbitrator_worker.start()

        self._chronicler = ChroniclerEngine(
            llm=self._llm,
            event_sourcer=es,
            db_path=self._db_path,
            trigger_interval=getattr(self, "_chronicler_interval", 50),
        )

    def _load_rules(self) -> list[dict]:
        """Read rules for session init (lightweight, main-thread ok)."""
        return load_rules_for_session(self._db_path)

    def _load_stats_after_meta(self) -> None:
        """Start a DbWorker to load initial entity stats after meta loads."""
        stats_worker = DbWorker(self._db_path)
        stats_worker.stats_loaded.connect(self._sidebar.refresh)
        stats_worker.inventory_loaded.connect(self._sidebar.refresh_inventory)
        stats_worker.timeline_loaded.connect(self._sidebar.refresh_timeline)
        stats_worker.stats_loaded.connect(lambda _: self._chat.set_send_enabled(True))
        stats_worker.error_occurred.connect(self._on_worker_error)
        stats_worker.status_update.connect(self._main_window.on_status_update)
        stats_worker.load_full_game_state(self._save_id)
        self._initial_stats_worker = stats_worker

    def _build_combined_system_prompt(self) -> str:
        """Return system_prompt combined with global_lore and player_persona."""
        parts = [self._universe_system_prompt]
        if self._global_lore:
            parts.append(f"=== WORLD LORE ===\n{self._global_lore}")
        if self._player_persona:
            parts.append(f"=== PLAYER BACKGROUND ===\n{self._player_persona}")
        return "\n\n".join(parts)

    def _resume_turn_id(self) -> None:
        """Read the highest existing turn_id from Event_Log to resume saves."""
        turn_id = get_max_turn_id(self._db_path, self._save_id)
        if turn_id > 0:
            self._turn_id = turn_id
            self._turn_label.setText(f"Turn: {self._turn_id}")

        current_time = get_current_time(self._db_path, self._save_id)
        self._time_label.setText(self._format_time(current_time))
        self._current_time = current_time
        self._last_chronicle_time = current_time

    def _format_time(self, total_minutes: int) -> str:
        """Format total minutes into 'Day X, HH:MM'."""
        days = (total_minutes // 1440) + 1
        hours = (total_minutes % 1440) // 60
        mins = total_minutes % 60
        return f"Day {days}, {hours:02d}:{mins:02d}"

    @Slot(int)
    def _on_timekeeper_complete(self, new_time: int) -> None:
        """Update the time label and check if Chronicler should trigger."""
        self._time_label.setText(self._format_time(new_time))
        
        # Advance modifiers based on elapsed time
        elapsed = new_time - self._current_time
        if elapsed > 0:
            worker = DbWorker(self._db_path)
            worker.modifiers_ticked.connect(self._sidebar.refresh)
            worker.tick_modifiers(self._save_id, elapsed)
            # We don't need to keep worker reference as DbWorker handles its own pool
        
        self._current_time = new_time

        # Check if Chronicler should trigger based on in-game time
        from workers.chronicler_worker import ChroniclerWorker
        if (
            self._chronicler is not None
            and self._chronicler.should_trigger(new_time, self._last_chronicle_time)
        ):
            if not (self._chronicler_worker and self._chronicler_worker.isRunning()):
                self._chronicler_worker = ChroniclerWorker(
                    chronicler=self._chronicler,
                    save_id=self._save_id,
                    turn_id=self._turn_id,
                    temperature=self._llm_temperature,
                    top_p=self._llm_top_p,
                )
                self._chronicler_worker.chronicle_complete.connect(
                    self._on_chronicle_complete
                )
                self._chronicler_worker.error_occurred.connect(self._on_worker_error)
                self._chronicler_worker.status_update.connect(
                    self._main_window.on_status_update
                )
                self._chronicler_worker.start()


