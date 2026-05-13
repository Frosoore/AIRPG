# Changelog — Axiom AI

All notable changes to this project are documented here.
Format: `[PHASE X | DATE] — Description`

---

## [PHASE 1 | 2026-03-10] — Foundation & Event Sourcing (Complete)

### Initialization
- Initialized repository directory structure: `core/`, `database/`, `llm_engine/`, `tests/`, `universes/`
- Created Python package markers (`__init__.py`) for all source modules
- Created `Changelog.md` and `Task.md` tracker files

### database/schema.py
- Implemented `create_universe_db()` — provisions all 8 SQLite tables in a single transaction
- Tables: `Universe_Meta`, `Entities`, `Entity_Stats`, `Rules`, `Active_Modifiers`, `Saves`, `Event_Log`, `State_Cache`
- WAL journal mode and FK enforcement enabled on every connection
- `get_connection()` helper with `sqlite3.Row` factory

### database/event_sourcing.py
- `EventSourcer` class: `append_event`, `get_events`, `rebuild_state_cache`, `get_current_stats`
- `_apply_event` pure function handles `entity_create`, `stat_change`, `stat_set`; ignores narrative events
- Integer display normalisation (no trailing `.0` for whole numbers)

### database/checkpoint.py
- `CheckpointManager` class: `rewind`, `list_checkpoints`, `delete_save`
- `rewind()` atomically deletes future Event_Log rows and rebuilds State_Cache
- `delete_save()` probes for file locks before irrevocable filesystem deletion (Hardcore mode)

### core/rules_engine.py
- `RulesEngine` class: `evaluate`, `apply_actions`, `_evaluate_conditions`, `_compare`
- Supports nested AND/OR condition trees, priority-ordered rule evaluation
- Type-safe comparisons: numeric (6 operators) and string (== / !=)
- `apply_actions` is a pure function; original stats never mutated

### database/modifier_processor.py
- `ModifierProcessor` class: `add_modifier`, `apply_modifiers`, `tick_modifiers`
- Turn-countdown expiry; non-numeric stats safely skipped during overlay
- Save-scoped tick via State_Cache join

### Test Suite
- 108 unit tests across 5 test files — **0 failures**

---

## [PHASE 2 | 2026-03-10] — LLM Integration & Dual Agents (Complete)

### llm_engine/base.py
- `LLMMessage` TypedDict, `LLMResponse` dataclass, `LLMConnectionError`, `LLMParseError`
- `LLMBackend` ABC with `complete`, `stream_tokens`, `is_available`
- Shared `parse_tool_call()` using `~~~json` / `~~~` fence delimiter

### llm_engine/ollama_client.py
- `OllamaClient` targeting Ollama REST API (`/api/chat`, `/api/tags`)
- NDJSON streaming, 120s timeout, full error propagation

### llm_engine/gemini_client.py
- `GeminiClient` using `google.genai` SDK (migrated from deprecated `google.generativeai`)
- `_translate_messages` handles system_instruction extraction and subsequent system injection
- Streaming via `generate_content_stream`

### llm_engine/prompt_builder.py
- Pure functions: `build_narrative_prompt`, `build_chronicler_prompt`, `build_mini_dico_prompt`, `format_entity_stats_block`
- `HISTORY_TURN_CAP = 20`; pending correction injected before final user turn
- World tension threshold 0.5 for mundane/dramatic guidance split

### llm_engine/vector_memory.py
- `VectorMemory` wrapping ChromaDB PersistentClient + `all-MiniLM-L6-v2` sentence-transformers
- `embed_chunk` with `{save_id, turn_id, chunk_type}` metadata; `query` with save-scoped filter
- `rollback` uses ChromaDB `$gt` metadata filter; returns deleted count

### core/arbitrator.py
- `Arbitrator` 13-step `process_turn` pipeline
- `_validate_change` against full entity stats dict; resource sufficiency enforcement
- `_pending_correction` Correction Loop: injected next turn, cleared immediately after
- `ArbitratorResult` dataclass with applied/rejected/triggered breakdown

### core/chronicler.py
- `ChroniclerEngine` with configurable `trigger_interval` (default 50)
- `should_trigger` pure function; `run` / `force_trigger` for time-skip
- Malformed LLM responses silently return empty result — never raise
- Player entity excluded from off-screen snapshot

### Test Suite
- **266/266 total tests passed** (108 Phase 1 + 158 Phase 2), **0 failures**
- All LLM/HTTP/SDK interactions mocked; no real network calls

---

## [PHASE 3 | 2026-03-10] — The UI Skeletons (PySide6) (Complete)

### New files (21 total)
- `main.py` — QApplication entry point, zero logic
- `ui/main_window.py` — QMainWindow + QStackedWidget, session state, navigation
- `ui/hub_view.py` — Library grid, Import/Create/Play/Export controls
- `ui/creator_studio_view.py` — Entity + Rule builder screen
- `ui/constants_sidebar.py` — Live entity stats panel (refresh() slot)
- `ui/mini_dico_panel.py` — Encyclopedic lore lookup, siloed from narrative
- `ui/tabletop_view.py` — Gameplay coordinator: chat + sidebar + mini-dico
- `ui/checkpoint_dialog.py` — Rewind turn-selection dialog
- `ui/widgets/universe_card.py` — Universe card for hub grid
- `ui/widgets/chat_display.py` — Narrative display + player input
- `ui/widgets/entity_editor.py` — Visual entity/stat form
- `ui/widgets/rule_editor.py` — Visual AND/OR rule builder
- `workers/narrative_worker.py` — QThread: Arbitrator.process_turn(), token signals
- `workers/chronicler_worker.py` — QThread: ChroniclerEngine.run()
- `workers/db_worker.py` — QThread: all SQLite reads/writes (6 task types)
- `workers/vector_worker.py` — QThread: VectorMemory.rollback() on rewind
- `workers/mini_dico_worker.py` — QThread: siloed Mini-Dico LLM call
- `workers/import_export_worker.py` — QThread: .axiom pack/unpack
- `workers/db_helpers.py` — Sync helper functions for lightweight main-thread reads

### Threading architecture
- 6 QThread workers cover ALL LLM, SQLite, VectorDB, and archive I/O
- Zero SQL string literals in any `ui/` file (all SQL in `workers/` and `database/`)
- All backend imports (database/, core/, llm_engine/) excluded from ui/ files
- Signal/Slot is the exclusive communication channel between workers and UI
- `NarrativeWorker.token_received(str)` → `ChatDisplayWidget.append_token` = typewriter mechanism
- `MiniDicoWorker` uses a completely separate LLM call with zero narrative context
- `DbWorker` task-parameter dispatch pattern handles all 6 UI-triggered DB operations

### Phase 3 verification
- `python3 main.py` launches successfully (QApplication + MainWindow)
- All 3 screens navigable without crash: Hub → Creator Studio, Hub → Tabletop
- QStatusBar reflects worker lifecycle messages
- CheckpointDialog lists turns for rewind selection
- No file exceeds 500 lines
- **266/266 backend tests still passing (0 regressions)**

---

## [PHASE 4 | 2026-03-10] — Assembly & Refinement (Complete)

### core/config.py
- `AppConfig` dataclass with full LLM backend configuration
- `load_config()` / `save_config()` — JSON persistence at `~/.config/axiom_ai/settings.json`; never raises on missing/malformed file
- `build_llm_from_config()` — factory that returns Ollama or Gemini backend from config

### ui/settings_dialog.py + workers/connection_test_worker.py
- Settings dialog with Ollama and Gemini tabs, "Test Connection" buttons, Chronicler interval spinner
- `ConnectionTestWorker` calls `is_available()` off the main thread
- `MainWindow` wired with `File → Settings (Ctrl+,)` menu action
- `TabletopView` now loads LLM from config with fallback to Ollama defaults

### core/arbitrator.py — True Streaming
- Added `stream_token_callback: Callable[[str], None] | None = None` parameter to `process_turn()`
- When provided: calls `llm.stream_tokens()`, passes each token to callback, assembles full text for `parse_tool_call()`
- When `None` (default): identical behaviour to Phase 2 — all 266 existing tests pass unchanged
- `NarrativeWorker` now passes `self.token_received.emit` as the callback → genuine per-token display

### Hardcore Mode (full safe deletion sequence)
- `workers/hardcore_worker.py`: receives paths only (no live objects)
  1. WAL checkpoint + `PRAGMA journal_mode=DELETE` to release sidecar locks
  2. Explicit save row + Event_Log + State_Cache deletion
  3. File-lock probe with 3 retries at 200ms intervals
  4. VectorMemory directory deletion (`shutil.rmtree`)
  5. `.db` deletion if no remaining saves
- `ui/tabletop_hardcore.py`: `HardcoreMixin` with `_check_for_player_death`, `_start_hardcore_deletion`, and completion/failure handlers
- `TabletopView` inherits `HardcoreMixin`; `_start_hardcore_deletion()` stops all workers, sets references to `None`, calls `gc.collect()`, then starts `HardcoreWorker`

### Signal/Slot wiring completion
- `_on_turn_complete`: surfaces rejected_changes count in status bar (4 seconds)
- `_on_turn_complete`: calls `_check_for_player_death` for Hardcore detection
- Save label shows `"▶ {universe_name} — {player_name} [{difficulty}]"`
- `ConstantsSidebar.refresh()` defensive guard against `None` stats

### Partial chat rewind
- `ChatDisplayWidget.begin_turn(turn_id)` inserts invisible `\x00TURN:N\x00` markers
- `clear_after_turn_id(turn_id)` searches for marker N+1 and removes only future content; full clear as fallback

### Error handling
- `MainWindow._check_first_run()`: welcome dialog on first launch
- `TabletopView._on_worker_error()`: rich Ollama guidance when LLM is unreachable
- `main.py` global `sys.excepthook`: writes crash log to `~/.cache/AxiomAI/crash.log`

### Packaging
- `requirements.txt` (runtime) and `requirements-dev.txt` (testing)
- `run.sh` — venv bootstrap + pip install + launch in one command
- `README.md` — prerequisites, quick start, configuration, architecture overview

### Test Suite
- **290/290 total tests passed** (108 Phase 1 + 158 Phase 2 + 24 Phase 4), **0 failures**
- New: `tests/test_config.py` (14), `tests/test_hardcore_worker.py` (7), streaming tests in `test_arbitrator.py` (3)

---

## [PHASE 5 | 2026-03-10] — UX/UI Overhaul & Lore Integration (Complete)

### 5.1 — Universe Meta & Lore Integration
- `ui/creator_studio_view.py`: added "Lore & Settings" third tab with `QPlainTextEdit` for `global_lore`, `QPlainTextEdit` for `system_prompt`, and `QDoubleSpinBox` (0.0–1.0) for `world_tension_level`
- `_on_meta_loaded`: now populates all three Lore & Settings fields from the loaded meta dict
- `_on_save_clicked`: launches a second `DbWorker` to persist meta fields alongside entities/rules
- `workers/db_worker.py`: new `save_universe_meta(meta: dict)` task + `_task_save_universe_meta` handler — upserts arbitrary key/value pairs into `Universe_Meta`
- `llm_engine/prompt_builder.py`: `build_narrative_prompt` now accepts optional `global_lore` and `player_persona` parameters; they are injected as labelled sections in the system message before the world state block
- `ui/tabletop_view.py`: `_on_meta_loaded` captures `global_lore`; `_build_combined_system_prompt()` concatenates system_prompt + lore + persona for the NarrativeWorker

### 5.2 — Player Persona & Save Management
- `database/schema.py`: `_DDL_SAVES` now includes `player_persona TEXT NOT NULL DEFAULT ''`; new `migrate_saves_table(db_path)` function adds the column to pre-Phase-5 databases via `ALTER TABLE … ADD COLUMN` with silent duplicate-column guard
- `workers/db_helpers.py`: `create_new_save` accepts optional `player_persona`; calls `migrate_saves_table` for safety; `load_saves` includes `player_persona` in returned dicts and also calls migration
- `ui/hub_view.py`: `_SaveSelectDialog` replaced by `SessionManagerDialog` — lists existing saves in a `QListWidget` (name, difficulty, last played), offers "Resume Selected Save", and a "New Game" section with player name `QLineEdit`, difficulty `QComboBox`, and player persona `QPlainTextEdit`
- `ui/main_window.py` + `ui/tabletop_view.py`: `show_tabletop` and `load_session` now accept `player_persona: str = ""`; stored as `_player_persona` and included in `_build_combined_system_prompt()`
- Test fixtures in 7 test files updated to use named-column `INSERT INTO Saves` to remain forward-compatible with new `player_persona` column

### 5.3 — Hub Universe Management
- `ui/widgets/universe_card.py`: new `edit_requested(str)` and `delete_requested(str)` signals; "✎ Edit" and "🗑 Delete" buttons added below existing Play/Export row
- `ui/hub_view.py`: `refresh_library` connects both new signals; `_on_card_edit_requested` calls `show_creator_studio`; `_on_card_delete_requested` shows `QMessageBox.warning`, then `os.remove(db_path)` + `refresh_library()`

### 5.4 — Dynamic Settings Reload
- `ui/tabletop_view.py`: `reload_llm()` method rebuilds the LLM via `build_llm_from_config()` and propagates the new instance to `_arbitrator._llm`, `_chronicler._llm`, and `MiniDicoPanel.configure()` — no app restart required
- `ui/main_window.py`: `_show_settings()` calls `_tabletop_view.reload_llm()` when `SettingsDialog` is accepted

### 5.5 — Aesthetic Polish (QSS)
- `main.py`: `_DARK_QSS` constant (~230 lines) applied via `app.setStyleSheet()` at startup
- Theme: `#1e1e1e` background, `#d4d4d4` text, `#094771` button accent, `#007acc` status bar
- Full coverage: `QPushButton`, `QLineEdit`/`QTextEdit`/`QPlainTextEdit`, `QTabWidget`, `QScrollBar`, `QSplitter`, `QStatusBar`, `QMenuBar`, `QGroupBox`, `QListWidget`, `QComboBox`, `QSpinBox`/`QDoubleSpinBox`, `QProgressBar`
- `ChatDisplayWidget QTextEdit`: `border: none`, `padding: 8px 12px`, `font-size: 12pt`

### Test Suite
- **290/290 total tests passed, 0 failures** (no regressions)
- All 7 affected test fixtures updated to named-column `INSERT INTO Saves`
- No file exceeds 500 lines

---

## [PHASE 6 | 2026-03-11] — Bug Fixes & Lore Book Expansion (Complete)

### 6.1 — Bug Fix: Startup Hub Refresh
- `ui/main_window.py`: added `self.show_hub()` at the end of `__init__` — library grid now populates on launch without requiring a manual navigation action.

### 6.2 — Bug Fix: Save Race Condition (Critical Architecture Fix)
- `workers/db_worker.py`: eliminated the dual-worker concurrent-write pattern. `save_entities_and_rules` and `save_universe_meta` removed entirely. Replaced by the atomic `save_full_universe(entities, rules, meta, lore_book)` task that opens **one** SQLite connection and executes all writes in a single `BEGIN/COMMIT` transaction — no more WAL lock collisions.
- `ui/creator_studio_view.py`: `_on_save_clicked` now collects all four data groups (entities, rules, meta, lore book) and launches **exactly one** `DbWorker` with `save_full_universe`. The stale `_meta_worker` field removed.

### 6.3 — Feature: Lore Book Schema
- `database/schema.py`: `_DDL_LORE_BOOK` constant + table added to `_ALL_DDL` and `EXPECTED_TABLES`.
- `database/schema.py`: `migrate_lore_book_table(db_path)` — idempotent `CREATE TABLE IF NOT EXISTS` migration for pre-Phase-6 databases.
- `workers/db_helpers.py`: `create_new_save` and `load_saves` both call `migrate_lore_book_table` for automatic upgrade of existing databases.

### 6.4 — Feature: Lore Book UI
- New file `ui/widgets/lore_book_editor.py` — `LoreBookEditorWidget` (257 lines): two-panel `QSplitter` layout matching the EntityEditorWidget paradigm. Left: `QListWidget` + Add/Delete buttons. Right: category `QLineEdit`, name `QLineEdit`, content `QPlainTextEdit`. Real-time label sync; `populate()` and `collect_data()` public API.
- `ui/creator_studio_view.py`: 4th "Lore Book" tab added hosting the new widget; `_db_worker.lore_book_loaded` connected to `populate()`.
- `workers/db_worker.py`: new `lore_book_loaded(list)` signal; `_task_load_entities_and_rules` now also queries `Lore_Book` rows and emits them; dedicated `load_lore_book` task added for tabletop session load.

### 6.5 — Feature: Lore Book LLM Injection
- `llm_engine/prompt_builder.py`: `_format_lore_book_block()` pure function — converts entry list to a category-grouped `### Category / #### Name / content` block. Optional `lore_book` parameter added to both `build_narrative_prompt` (injected under `global_lore`) and `build_mini_dico_prompt`.
- `ui/tabletop_view.py`: `_lore_book: list[dict]` field; separate `load_lore_book` worker fires on session start; `_on_lore_book_loaded` slot stores the list and pushes it to `MiniDicoPanel.configure()`.
- `ui/mini_dico_panel.py`: `configure()` accepts `lore_book: list[dict] | None`; stored as `_lore_book`; passed to `MiniDicoWorker` on each query.
- `workers/mini_dico_worker.py`: `lore_book` parameter added; forwarded to `build_mini_dico_prompt`.

### 6.6 — Bug Fix: Hide JSON Blocks in Chat UI
- `ui/widgets/chat_display.py`: added `_token_buf`, `_in_json_fence` state fields. `append_token` now routes through `_flush_token_buffer()` which scans for `~~~json` openers and suppresses all text up to and including the matching `~~~` closer. A 6-character partial-match watch window prevents premature emission of tilde sequences. `begin_turn()` calls `_reset_fence_state()` before each new assistant response.

### Test Suite
- New `tests/test_phase6.py` — 21 tests covering: Lore_Book schema/migration, `_format_lore_book_block`, `build_narrative_prompt`/`build_mini_dico_prompt` with lore_book, `save_full_universe` atomicity, JSON fence filtering.
- **311/311 total tests passed, 0 failures**
- No file exceeds 500 lines

---

## [PHASE 6.7 | 2026-03-11] — Bug Fix: UI Form Synchronization

### Root cause
`_sync_current_form()` in both `EntityEditorWidget` and `RuleEditorWidget` read `currentRow()` / `currentRow()` to find the slot to write to. By the time Qt emits `currentRowChanged` and the slot fires, the selection model has already advanced to the **new** row — so every call to `_sync_current_form()` inside `_on_entity_selected` / `_on_rule_selected` was writing the old form data into the **new** item's slot, silently corrupting it. `LoreBookEditorWidget` was unaffected because it tracks its own `_current_index` and advances it **after** calling `_flush_form()`.

### Fix
- **`ui/widgets/entity_editor.py`**: added `_selected_row: int = -1` field. `_sync_current_form()` now reads `self._selected_row` (the row whose data is currently displayed) instead of `currentRow()`. `_on_entity_selected(row)` flushes against `_selected_row` first, then sets `_selected_row = row`, then loads the new entity. `populate()` resets `_selected_row = -1`. `_on_delete_entity` uses `_selected_row` and resets it after deletion.
- **`ui/widgets/rule_editor.py`**: identical `_selected_row` tracking added. `_on_rule_selected(row)` already called `_sync_current_form()` at the start, but it was targeting the wrong slot; now it flushes the previous slot correctly. `populate()` and `_on_delete_rule` updated consistently.
- **`ui/widgets/lore_book_editor.py`**: no changes — already implemented correctly.

### Validation
The specific scenario from the spec — "click Add Entity, type 'Gojo', click Save Changes without clicking elsewhere" — is now guaranteed to persist "Gojo". Additionally, the harder multi-entity navigation case (edit Entity A → click Entity B → click Save) now correctly preserves Entity A's edits.

### Tests
- 6 new regression tests added to `tests/test_phase6.py` across `TestEntityEditorSync` and `TestRuleEditorSync`
- **317/317 total tests passed, 0 failures**

---

## [PHASE 7 | 2026-03-11] — Absolute Persistence Protocol (Complete)

### 7.1 — UI Synchronization & List Refresh
- `EntityEditorWidget`, `RuleEditorWidget`, `LoreBookEditorWidget`: `collect_data()` now calls form sync/flush at the very beginning to ensure the absolute latest edits are captured.
- List items in the left panel now update their text immediately when form fields change, providing instant visual feedback.

### 7.2 — SQLite Serialization & Atomic Load
- `workers/db_worker.py`: `save_full_universe` now explicitly calls `json.dumps()` on rule conditions/actions and includes an explicit `conn.commit()` to ensure zero data loss.
- `workers/db_worker.py`: New `load_full_universe` task combines meta, entities, rules, and lore book into a single atomic pass.
- `ui/creator_studio_view.py`: `load_universe` updated to use `load_full_universe`, eliminating task-overwriting bugs where meta would overwrite entities/rules during startup.

### 7.3 — Error Wiring
- `ui/creator_studio_view.py`: `_save_worker` is now a persistent instance variable to prevent GC mid-flight.
- `error_occurred` signal connected to `QMessageBox.critical` across all editors to ensure database errors are never silent.

---

## [PHASE 9 | 2026-03-11] — UI Polish & Transition UX (Complete)

### 9.1 — Loading Screen
- `ui/loading_view.py`: Implemented a new indeterminate progress screen to mask backend initialisation latency.
- `ui/main_window.py`: Integrated `LoadingView` into the `QStackedWidget` navigation lifecycle.
- `ui/tabletop_view.py`: Implemented `session_loaded` signal to precisely track when metadata and lore book are ready, ensuring a smooth transition out of the loading state.

### 9.2 — Aesthetic Standardisation
- System-wide removal of emojis (`⬇`, `✚`, `▶`, `⏪`, `←`, `✔`, `🔍`, `🗑`, `✎`) from buttons, labels, and status messages.
- Replaced all typography symbols (`…`, `—`, `⎯`) with standard ASCII equivalents (`...`, `-`, `-`) for a cleaner, more professional CLI-inspired aesthetic.

---

## [PHASE 10 | 2026-03-20] — Performance & Resilience (Optimisations)

### 10.1 — Scalability & Performance
- **Event Sourcing Snapshots**: Implemented 20-turn snapshots in `Snapshots` table. `rebuild_state_cache` now starts from the nearest snapshot, significantly reducing replay time for long games.
- **Async Hub Loading**: `HubView` now uses `DbWorker` for library scanning and metadata reading. Implementation of a diffing mechanism for `UniverseCard` widgets (only changed cards are updated).
- **Bulk Database Writes**: Optimized `State_Cache` updates using `executemany()` for improved performance during large state reconstructions.

### 10.2 — Resilience & Parsing
- **Resilient JSON Extraction**: `LLMBackend.parse_tool_call` now supports multiple markdown fences (~~~json, ```json, etc.) and includes a raw regex fallback for extracting JSON objects `{...}` at the end of the response.
- **Context Filtering**: `Arbitrator` now heuristically identifies "relevant" entities based on user input, history, and RAG chunks. Only relevant stats are sent to the LLM, saving significant context window space.
- **RAG-based Lore Retrieval**: Replaced full Lore Book injection with targeted RAG lookup. Only entries matching the current narrative context are injected into the prompt.

### 10.3 — Debuggability & Integrity
- **Integrity Validator**: New `validate_integrity()` in `EventSourcer` to detect divergences between `Event_Log` and `State_Cache`.
- **Force Rebuild**: `rebuild_state_cache` now supports `force_full=True` to ignore all snapshots and repair corruption by replaying the entire history from turn 0.
- **Worker Fixes**: Corrected argument naming in `RegenerateWorker` that was causing crashes during AI text regeneration.

---

## [PHASE 11 | 2026-04-14] — Multiplayer & Temporal Foundations (In Progress)

### 11.1 — Dynamic Stop Sequences & Player Impersonation Prevention
- `Arbitrator` now dynamically builds stop sequences based on `player_entity_id` (`[player1]`, `player1:` etc.).
- Extended test coverage in `test_arbitrator.py` to ensure stop sequences are properly pushed to the LLM backend.

### 11.2 — Temporal Variants UI Navigation & Divergence Handling
- **Temporal Enforcer**: Rewriting a past variant now triggers a "Temporal Warning" and executes a timeline rewind (deleting all subsequent turns).
- **Consistent Rewind**: `CheckpointManager.rewind` now correctly cleans up `Snapshots` and `Timeline` tables for future turns.
- **Memory Coherence**: Implemented `VectorEmbedWorker` to re-embed the narrative of a turn when its active variant is changed, ensuring RAG memory stays in sync with the current timeline.
- **Stateless Vector Rollback**: Vector memory is now surgically rolled back during a variant switch to prevent "timeline bleed" from erased future turns.

### 11.3 — Multi-player Queue Logic & Player Selection
- **Sequential Queue**: Replaced `NarrativeWorker` with `ArbitratorWorker` using a FIFO queue to process multiple player turns without race conditions.
- **Player Selector UI**: Added a `QComboBox` in the Tabletop top-bar to switch the active `player_id` dynamically.
- **Dynamic Population**: The selector automatically populates based on `player` type entities found in the universe database.
- **Multi-player History**: Player inputs are now tagged with their respective IDs in the conversation history and UI (e.g., `[player_1] Hello`).

### 11.4 — Session Lobby & Player Management
- **Universe Lobby**: Replaced the old Save Selection dialog with a multi-tab `SessionLobbyDialog`.
- **Player Management**: Added a dedicated "Player Lobby" tab to create, delete, and view available player entities in the universe before starting.
- **Improved Workflow**: Simplified session launch with dedicated "Create Save" and "Launch" paths.
- **Infrastructure**: Added `CreatePlayerEntityTask` and `DeleteEntityTask` to support player management from the UI.

---

## [PHASE 14 | 2026-04-16] — Reliability & Deployment (Complete)

### 14.1 — Verbose Launch Script
- Overhauled `run.sh` to provide real-time feedback during dependency installation and model downloads.
- Added explicit checks for `python3-venv` and common Linux GUI libraries (e.g., `libxcb-cursor0`).

### 14.2 — Automated Fail-safes
- Implemented `database/backup_manager.py` to create timestamped database backups before destructive operations like Rewind or Hardcore deletion.
- Backups are stored in a dedicated `auto_backups/` directory within the save path.

### 14.3 — Background Integrity Monitoring
- Added asynchronous `validate_integrity()` check that compares the materialised `State_Cache` against a full `Event_Log` replay on session start.
- Integrated visual warnings in the UI if state divergence is detected.

### 14.4 — Sanitation & Documentation
- Cleaned the root directory and implemented a comprehensive `.gitignore`.
- Updated `README.md` with system requirements, architecture overview, and contribution guidelines for GitHub publication.

---

## [PHASE 17 | 2026-05-03] — Comeback Rework & UX Excellence (Complete)

### UI/UX: Spreadsheet-like Interaction
- **Bulk Editing:** Implemented multi-cell synchronization. Changing one cell while others are selected in the same column propagates the change to all selected items (Entities, Stats, Rules, Lore).
- **Smart Selection:** Switched all tables to `SelectItems` with `ExtendedSelection` for precise multi-cell control.
- **Smart Deletion:** `Delete` key now intelligently clears cell contents if partial rows are selected, or deletes entire records if full rows are targeted.

### Keyboard-First Workflow
- **Global Shortcuts:** Added `Ctrl+S` (Save), `Ctrl+1` through `Ctrl+7` (Tab navigation).
- **Tabular Navigation:** Full support for `Tab` / `Shift+Tab` and `Arrow` keys across all spreadsheet editors.
- **Fluid Saisie:** "Write-before-Add" pattern perfected—pressing `Enter` in input fields adds the entry and returns focus to the starting field for rapid data entry.

### Creator Studio Overhaul
- **Entity Editor:** Replaced "Add All Stats" with a `MultiStatSelectionDialog`, allowing selective bulk addition via checkboxes.
- **Rule Editor:** Strict validation via `QComboBox` for stat keys. No more free-text "stat key" fields to prevent broken rule logic.
- **Lore Book:** Added "Populate ✨" button for AI-generated lore. Implemented explicit category management with a "New Category" flow.
- **Scheduled Events:** Full "Custom Calendar" support. Users can now define custom month names and precise "Adventure Start" days. Dynamic time preview in the editor.

### Deployment & Bug Fixes
- **SVG Icon Fix:** `run.sh` now detects missing `libqt6svg6` system libraries.
- **Absolute Pathing:** Corrected icon resolution logic in `axiom_ai.desktop` for better global installation compatibility.
- **ASCII Aesthetic:** Finalized the removal of emojis and non-standard typography for a cleaner "Senior Engineer" monospaced look.

---

## [PHASE 18 | 2026-05-11] — Spatial Navigation & Hierarchical Mapping (Complete)

### World Map Editor
- **Multi-Scale Hierarchy**: New dual-pane editor in Creator Studio allowing management of locations from 'Universe' down to 'Building'.
- **Graph-Based Connections**: Implemented a graphical node-link editor (`QGraphicsScene`) for establishing distances between points.
- **Visual Editing**: Drag-and-drop node placement with automatic coordinate persistence in the database.
- **Large Distance Support**: New `ScientificDistanceEntryDialog` added, allowing input of astronomical distances using powers of 10 (e.g., 2 x 10^12 km) for sci-fi universes.
- **UI UX Improvements**: Added a dedicated 'Connect' toolbar button and 'C' keyboard shortcut. Removed confusing background context menu entries.

### Core Engine Integration
- **Spatial Prompt Optimization**: Arbitrator now fetches recursive breadcrumbs and immediate neighbors for the player's current location, injecting them as highly compressed context for the LLM.
- **Kilometer-Based Travel**: Switched from fixed minutes to **Kilometers (km)**. The Arbitrator logs the distance traveled in the timeline, allowing the LLM to interpret travel time based on the narrative context (e.g., warp drive vs walking).
- **Database Schema Expansion**: Added `Locations` and `Location_Connections` tables with automatic migration logic in `database/schema.py`.

### Technical Integrity & Maintenance
- **Test Suite Restoration**: Fixed broken `tests/test_arbitrator.py` by updating test setups to match the current `ArbitratorEngine` API and `configure()` pattern.
- **Vector DB Patching**: Exposed embedding functions in `llm_engine/vector_memory.py` to allow clean mocking in tests while maintaining lazy-loading benefits.
- **Validation**: Updated `debug/startup_check.py` to verify spatial table presence and worker readiness.

