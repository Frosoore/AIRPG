Phase 5: UX/UI Overhaul & Lore Integration

5.1 — Universe Meta & Lore Integration (ui/creator_studio_view.py)

The engine already has a Universe_Meta table, but the UI lacks a way to edit it.

[ ] Add a third tab to the QTabWidget in CreatorStudioView named "Lore & Settings".

[ ] This tab must contain:

QPlainTextEdit for "Global Universe Lore" (Key: global_lore).

QPlainTextEdit for "System Prompt Override" (Key: system_prompt).

QSlider (Horizontal) or QSpinBox for "World Tension Level" (Key: world_tension_level, range 0.0 to 1.0).

[ ] Connect this new tab to DbWorker: When load_universe runs, populate these fields from the universe_meta_loaded signal. When on_save_clicked runs, gather these three values and add a new DbWorker task to persist them to the Universe_Meta table.

[ ] Ensure llm_engine/prompt_builder.py is actively reading global_lore and system_prompt from the database to inject into the LLM context.

5.2 — Player Persona & Save Management (database/schema.py & ui/hub_view.py)

The player needs a persona, and the app must allow resuming saves.

[ ] Schema Update: Modify database/schema.py to add a player_persona TEXT column to the Saves table. Write an ALTER TABLE migration fallback if the column doesn't exist so existing databases aren't broken.

[ ] Hub Play Flow: Modify the on_card_play_requested slot. Instead of immediately creating a new game, open a SessionManagerDialog (a new QDialog).

[ ] SessionManagerDialog:

Must query the Saves table for the selected db_path.

Display a QListWidget of existing saves (showing Player Name, Last Played, and Difficulty).

Include a "Resume Selected Save" button.

Include a "New Game" section below with: QLineEdit (Player Name), QComboBox (Difficulty), and a QPlainTextEdit (Player Persona/Background).

Include a "Start New Game" button.

[ ] Ensure the player_persona is injected into the initial build_narrative_prompt so the AI knows who the player is when the game starts.

5.3 — Hub Universe Management (ui/widgets/universe_card.py)

[ ] Add "Edit" and "Delete" buttons to the UniverseCard layout.

[ ] "Edit" must emit a signal that tells MainWindow to show_creator_studio(db_path).

[ ] "Delete" must prompt a QMessageBox.warning for confirmation. If confirmed, use os.remove(db_path) and call refresh_library().

5.4 — Dynamic Settings Reload (ui/tabletop_view.py)

[ ] When SettingsDialog is saved, it updates settings.json. The MainWindow must emit a custom signal or directly call a method on TabletopView to dynamically rebuild its _llm instance using build_llm_from_config() without requiring an app restart.

[ ] The MiniDicoWorker must also fetch this updated _llm instance on its next run.

5.5 — Aesthetic Polish (QSS)

The application currently uses raw OS-native styling, which is functionally sound but visually sterile.

[ ] In main.py, apply a global Qt StyleSheet (QSS) to the QApplication.

[ ] The theme must be a sleek, dark mode interface. Use dark grays (e.g., #1e1e1e), light text (#d4d4d4), and subtle accent colors (e.g., #094771 for buttons).

[ ] Add padding to ChatDisplayWidget, make the QTextEdit borders invisible, and ensure the font size is appropriately readable (e.g., 11pt or 12pt).


Phase 6: Bug Fixes & Lore Book Expansion

6.1 — Bug Fix: Startup Hub Refresh

[ ] ui/main_window.py: Ensure self.show_hub() (which implicitly or explicitly calls HubView.refresh_library()) is called at the very end of MainWindow.__init__ (or immediately after the app starts) so existing universes appear instantly on launch.

6.2 — Bug Fix: The Save Race Condition & Typo

[ ] ui/creator_studio_view.py: Fix the typo in the tab name from "Lore_Settings" to "Lore & Settings".

[ ] Critical Architecture Fix: The disappearing entities are caused by launching two concurrent DbWorker threads on the same SQLite file during save, causing a silent WAL lock failure.

[ ] workers/db_worker.py: Remove save_universe_meta and save_entities_and_rules as separate tasks. Create a single, atomic task: save_full_universe(entities: list, rules: list, meta: dict, lore_book: list). This method MUST open exactly ONE database connection, execute all writes sequentially within a single transaction, commit, and then emit save_complete.

[ ] ui/creator_studio_view.py: Update _on_save_clicked to collect data from ALL tabs (Entities, Rules, Lore/Meta, and the new Lore Book) and launch exactly ONE DbWorker instance with the new save_full_universe task.

6.3 — Feature: The Lore Book (Database Schema)

To prevent cluttering the global lore, we need a dedicated table for structured world-building.

[ ] database/schema.py: Update create_universe_db to include a new table: CREATE TABLE IF NOT EXISTS Lore_Book (entry_id TEXT PRIMARY KEY, category TEXT, name TEXT, content TEXT).

[ ] Create a migration function migrate_lore_book_table(db_path: str) that safely adds this table if it does not exist (using CREATE TABLE IF NOT EXISTS).

[ ] workers/db_helpers.py: Call migrate_lore_book_table inside load_saves() and create_new_save() to ensure older databases are automatically upgraded.

6.4 — Feature: The Lore Book (UI)

[ ] ui/widgets/lore_book_editor.py: Create a new visual widget LoreBookEditorWidget(QWidget) using the same QSplitter layout paradigm as EntityEditorWidget.

[ ] Left panel: QListWidget for entries + "Add Entry" and "Delete Entry" buttons.

[ ] Right panel (Form): QLineEdit for category (e.g., "Magic System", "Faction"), QLineEdit for name (e.g., "The Dark Arts"), and a large QPlainTextEdit for content.

[ ] Implement populate(entries: list[dict]) and collect_data() -> list[dict].

[ ] ui/creator_studio_view.py: Add a 4th tab named "Lore Book" hosting this new widget. Update the DbWorker load task to also fetch Lore_Book rows and emit them to populate this tab.

6.5 — Feature: Lore Book LLM Injection

The Arbitrator and the Mini-Dico must be aware of this new structured knowledge.

[ ] llm_engine/prompt_builder.py: Add a lore_book: list[dict] parameter to build_narrative_prompt and build_mini_dico_prompt.

[ ] Inside these prompt functions, convert the Lore Book list into a highly readable, category-grouped text block (e.g., ### Category: Faction\n#### Name: The Red Guard\nContent...).

[ ] Inject this formatted Lore Book text directly underneath the global_lore section in the final system prompt.

[ ] Update TabletopView and MiniDicoPanel to fetch the Lore Book from the database on session load, store it, and pass it to the prompt builders via their respective workers.

6.6 — Bug Fix: Hide JSON blocks in Chat UI

[ ] ui/widgets/chat_display.py: Modify the text rendering logic (in append_token or wherever the text stream is received) to dynamically filter out and hide the ~~~json ... ~~~ block. The player must ONLY see the narrative text, preserving the immersion completely.

6.7 — Bug Fix: UI Form Synchronization (Despawning Data)

The user is experiencing silent data loss when clicking "Save Changes" immediately after editing an entity, rule, or lore book entry. This is a classic UI state synchronization bug.

The Issue: The collect_data() methods in EntityEditorWidget, RuleEditorWidget, and LoreBookEditorWidget are returning the internal state list (self._entities, self._rules, etc.) without first forcibly saving the currently active/visible form data back into that internal list. If the user edits a text box and clicks "Save" without changing the selected row in the QListWidget, their current edits are lost.

The Fix: 1. In ui/widgets/entity_editor.py, open the collect_data(self) method. Before doing anything else, explicitly call the method that saves the current right-panel form data into the currently selected item in self._entities (e.g., self._save_current_form_state() or whatever internal logic updates the dictionary).
2. Apply the exact same fix to collect_data(self) in ui/widgets/rule_editor.py.
3. Apply the exact same fix to collect_data(self) in ui/widgets/lore_book_editor.py.

Validation: After fixing this, if a user clicks "Add Entity", types "Gojo", and immediately clicks "Save Changes" without clicking anywhere else, the entity MUST be collected and saved to the SQLite database successfully.