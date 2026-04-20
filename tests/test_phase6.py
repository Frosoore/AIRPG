"""
tests/test_phase6.py

Unit tests for Phase 6: Bug Fixes & Lore Book Expansion.

Covers:
  - Lore_Book table provisioned by create_universe_db
  - migrate_lore_book_table() is idempotent
  - _format_lore_book_block() grouping and formatting
  - build_narrative_prompt / build_mini_dico_prompt accept lore_book
  - DbWorker.save_full_universe atomicity (single connection, all data saved)
  - ChatDisplayWidget JSON fence filtering (_flush_token_buffer)
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from database.schema import create_universe_db, migrate_lore_book_table
from llm_engine.prompt_builder import (
    _format_lore_book_block,
    build_mini_dico_prompt,
    build_narrative_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    """Return path to a freshly provisioned universe database."""
    db = str(tmp_path / "test.db")
    create_universe_db(db)
    return db


# ---------------------------------------------------------------------------
# 6.3 — Lore_Book schema
# ---------------------------------------------------------------------------

class TestLoreBookSchema:
    def test_lore_book_table_created(self, tmp_db: str) -> None:
        """create_universe_db must provision Lore_Book."""
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='Lore_Book';"
            ).fetchone()
        assert row is not None, "Lore_Book table must exist after create_universe_db"

    def test_lore_book_columns(self, tmp_db: str) -> None:
        """Lore_Book must have entry_id, category, name, content columns."""
        with sqlite3.connect(tmp_db) as conn:
            info = conn.execute("PRAGMA table_info(Lore_Book);").fetchall()
        col_names = {row[1] for row in info}
        assert {"entry_id", "category", "name", "content"} <= col_names

    def test_migrate_lore_book_idempotent(self, tmp_db: str) -> None:
        """migrate_lore_book_table must succeed even if table already exists."""
        migrate_lore_book_table(tmp_db)
        migrate_lore_book_table(tmp_db)  # second call must not raise

    def test_migrate_lore_book_creates_table_on_old_db(self, tmp_path: Path) -> None:
        """migrate_lore_book_table creates the table if it was absent."""
        db = str(tmp_path / "old.db")
        # Provision without Lore_Book (simulate old database)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE Universe_Meta (key TEXT PRIMARY KEY, value TEXT);")
        migrate_lore_book_table(db)
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='Lore_Book';"
            ).fetchone()
        assert row is not None

    def test_insert_and_read_lore_book_entry(self, tmp_db: str) -> None:
        """Lore_Book accepts valid inserts and returns them."""
        with sqlite3.connect(tmp_db) as conn:
            conn.execute(
                "INSERT INTO Lore_Book (entry_id, category, name, content) "
                "VALUES (?, ?, ?, ?);",
                ("e1", "Faction", "Red Guard", "Elite soldiers of the Empire."),
            )
            conn.commit()
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute(
                "SELECT category, name, content FROM Lore_Book WHERE entry_id='e1';"
            ).fetchone()
        assert row == ("Faction", "Red Guard", "Elite soldiers of the Empire.")


# ---------------------------------------------------------------------------
# 6.5 — Lore Book prompt formatting
# ---------------------------------------------------------------------------

class TestFormatLoreBookBlock:
    def test_empty_returns_empty_string(self) -> None:
        assert _format_lore_book_block([]) == ""

    def test_single_entry_formatted(self) -> None:
        entries = [
            {"entry_id": "e1", "category": "Magic", "name": "Arcane Flame", "content": "Burns eternally."}
        ]
        result = _format_lore_book_block(entries)
        assert "### Category: Magic" in result
        assert "#### Arcane Flame" in result
        assert "Burns eternally." in result

    def test_multiple_entries_grouped_by_category(self) -> None:
        entries = [
            {"entry_id": "e1", "category": "Faction", "name": "Red Guard", "content": "Soldiers."},
            {"entry_id": "e2", "category": "Faction", "name": "Blue Fleet", "content": "Sailors."},
            {"entry_id": "e3", "category": "Location", "name": "The Keep", "content": "A fortress."},
        ]
        result = _format_lore_book_block(entries)
        assert result.count("### Category: Faction") == 1
        assert "#### Red Guard" in result
        assert "#### Blue Fleet" in result
        assert "### Category: Location" in result

    def test_missing_category_defaults_to_general(self) -> None:
        entries = [{"entry_id": "e1", "category": "", "name": "Mystery", "content": "Unknown."}]
        result = _format_lore_book_block(entries)
        assert "### Category: General" in result

    def test_lore_book_section_header_present(self) -> None:
        entries = [{"entry_id": "e1", "category": "X", "name": "Y", "content": "Z"}]
        result = _format_lore_book_block(entries)
        assert result.startswith("=== LORE BOOK ===")


class TestBuildNarrativePromptLoreBook:
    def test_lore_book_injected_into_system_message(self) -> None:
        entries = [{"entry_id": "e1", "category": "Faction", "name": "Guard", "content": "Soldiers."}]
        msgs = build_narrative_prompt(
            universe_system_prompt="You are narrator.",
            entity_stats_block="(no entities)",
            rag_chunks=[],
            history=[],
            user_message="Hello",
            lore_book=entries,
        )
        system_content = msgs[0]["content"]
        assert "=== LORE BOOK ===" in system_content
        assert "Faction" in system_content

    def test_empty_lore_book_not_injected(self) -> None:
        msgs = build_narrative_prompt(
            universe_system_prompt="Narrator.",
            entity_stats_block="(no entities)",
            rag_chunks=[],
            history=[],
            user_message="Hi",
            lore_book=[],
        )
        assert "=== LORE BOOK ===" not in msgs[0]["content"]

    def test_none_lore_book_not_injected(self) -> None:
        msgs = build_narrative_prompt(
            universe_system_prompt="Narrator.",
            entity_stats_block="(no entities)",
            rag_chunks=[],
            history=[],
            user_message="Hi",
            lore_book=None,
        )
        assert "=== LORE BOOK ===" not in msgs[0]["content"]


class TestBuildMiniDicoPromptLoreBook:
    def test_lore_book_included_in_user_message(self) -> None:
        entries = [{"entry_id": "e1", "category": "Magic", "name": "Fireball", "content": "Hot."}]
        msgs = build_mini_dico_prompt("What is Fireball?", [], lore_book=entries)
        user_content = msgs[1]["content"]
        assert "=== LORE BOOK ===" in user_content
        assert "Fireball" in user_content

    def test_no_lore_book_still_works(self) -> None:
        msgs = build_mini_dico_prompt("What is magic?", ["Magic is power."])
        assert len(msgs) == 2
        assert "Magic is power." in msgs[1]["content"]


# ---------------------------------------------------------------------------
# 6.2 — save_full_universe atomicity
# ---------------------------------------------------------------------------

class TestSaveFullUniverse:
    def test_entities_rules_meta_lore_book_saved_atomically(
        self, tmp_db: str, tmp_path: Path
    ) -> None:
        """save_full_universe must persist all four data groups in one pass."""
        from workers.db_worker import DbWorker

        entities = [
            {"entity_id": "hero", "entity_type": "player", "name": "Aria",
             "stats": {"HP": "100", "Gold": "50"}},
        ]
        rules: list[dict] = []
        meta = {"universe_name": "TestWorld", "global_lore": "Ancient magic rules."}
        lore_book = [
            {"entry_id": "lb1", "category": "Faction", "name": "Empire",
             "content": "The ruling power."},
        ]

        # Provision a Saves row so FK constraints are satisfied if needed
        with sqlite3.connect(tmp_db) as conn:
            conn.execute(
                "INSERT INTO Saves (save_id, player_name, difficulty, last_updated) "
                "VALUES ('s1', 'Aria', 'Normal', '2026-01-01T00:00:00');"
            )

        worker = DbWorker(tmp_db)
        from PySide6.QtCore import QCoreApplication, Qt
        import time
        done = []
        worker.save_complete.connect(lambda: done.append(True), Qt.QueuedConnection)
        worker.save_full_universe(entities, rules, meta, lore_book)
        errors: list[str] = []
        worker.error_occurred.connect(errors.append)

        start = time.time()
        while not done and not errors and time.time() - start < 5:
            QCoreApplication.processEvents()
            time.sleep(0.01)

        assert errors == [], f"save_full_universe emitted error: {errors}"

        with sqlite3.connect(tmp_db) as conn:
            # Entity persisted
            row = conn.execute(
                "SELECT name FROM Entities WHERE entity_id='hero';"
            ).fetchone()
            assert row is not None and row[0] == "Aria"

            # Stats persisted
            hp = conn.execute(
                "SELECT stat_value FROM Entity_Stats WHERE entity_id='hero' AND stat_key='HP';"
            ).fetchone()
            assert hp is not None and hp[0] == "100"

            # Meta persisted
            name = conn.execute(
                "SELECT value FROM Universe_Meta WHERE key='universe_name';"
            ).fetchone()
            assert name is not None and name[0] == "TestWorld"

            # Lore Book persisted
            lb = conn.execute(
                "SELECT name FROM Lore_Book WHERE entry_id='lb1';"
            ).fetchone()
            assert lb is not None and lb[0] == "Empire"


# ---------------------------------------------------------------------------
# 6.6 — JSON fence filtering in ChatDisplayWidget
# ---------------------------------------------------------------------------

class TestJsonFenceFiltering:
    """Tests for the _flush_token_buffer fence-detection logic.

    We instantiate a bare ChatDisplayWidget-like object to avoid needing
    a live QApplication.  Instead we test the pure buffer logic by calling
    _flush_token_buffer directly after setting up _token_buf / _in_json_fence.
    """

    class _FakeFlusher:
        """Minimal stand-in exposing just the fence-filtering logic."""
        _JSON_OPEN = "~~~json"
        _JSON_CLOSE = "~~~"

        def __init__(self):
            self._token_buf = ""
            self._in_json_fence = False

        def feed(self, token: str) -> str:
            self._token_buf += token
            from ui.widgets.chat_display import ChatDisplayWidget
            # Borrow the method directly
            return ChatDisplayWidget._flush_token_buffer(self)  # type: ignore[arg-type]

    def _make(self):
        return self._FakeFlusher()

    def test_plain_text_eventually_passes_through(self) -> None:
        """Plain text is visible once enough chars arrive to clear the watch window."""
        f = self._make()
        # Feed enough text so the safe_len guard passes content through.
        # Guard is len("~~~json")-1 = 6 chars held back.
        result = f.feed("Hello world — long enough to flush!")
        assert "Hello" in result

    def test_json_block_fully_suppressed(self) -> None:
        f = self._make()
        text = "Narrative text.\n~~~json\n{\"foo\":1}\n~~~\nMore text. Extra suffix here."
        result = ""
        for ch in text:
            result += f.feed(ch)
        assert "~~~json" not in result
        assert "foo" not in result
        assert "Narrative text." in result

    def test_text_after_fence_visible(self) -> None:
        """Text after a closed fence becomes visible once the guard window clears."""
        f = self._make()
        # Payload ends with > 6 extra chars so the guard releases "After."
        payload = "Before.\n~~~json\n{}\n~~~\nAfter. And more padding here."
        result = ""
        for ch in payload:
            result += f.feed(ch)
        assert "After." in result
        assert "{}" not in result

    def test_no_fence_text_unchanged(self) -> None:
        f = self._make()
        result = ""
        for ch in "Pure narrative, no JSON here at all!":
            result += f.feed(ch)
        assert "Pure narrative" in result

    def test_partial_open_fence_not_emitted_prematurely(self) -> None:
        """Tilde chars that could be a fence opener must not be emitted early."""
        f = self._make()
        r1 = f.feed("~")
        r2 = f.feed("~")
        r3 = f.feed("~")
        assert "~~~" not in (r1 + r2 + r3)


# ---------------------------------------------------------------------------
# 6.7 — UI Form Synchronization
# ---------------------------------------------------------------------------

class TestEntityEditorSync:
    """collect_data() must capture the currently visible form before returning."""

    def _make_widget(self):
        """Instantiate EntityEditorWidget without a live QApplication."""
        # Import here so import errors surface as test errors, not collection errors
        from ui.widgets.entity_editor import EntityEditorWidget
        return EntityEditorWidget.__new__(EntityEditorWidget)

    def test_collect_data_flushes_active_form(self) -> None:
        """After adding an entity and editing its name, collect_data returns the edit."""
        from ui.widgets.entity_editor import EntityEditorWidget

        w = EntityEditorWidget.__new__(EntityEditorWidget)
        # Directly simulate the in-memory state that would exist after the user
        # clicked "Add Entity", which appended a new dict and set _selected_row
        w._entities_data = [
            {"entity_id": "hero", "entity_type": "player", "name": "Old Name", "stats": {}}
        ]
        w._selected_row = 0

        # Simulate the user having typed "Gojo" in the name field by monkey-patching
        # _sync_current_form to verify it's called and returns the right data
        synced = []

        original_sync = EntityEditorWidget._sync_current_form

        def fake_sync(self_inner):
            # Write "Gojo" as if the form QLineEdit contained it
            row = self_inner._selected_row
            if 0 <= row < len(self_inner._entities_data):
                self_inner._entities_data[row]["name"] = "Gojo"
            synced.append(row)

        EntityEditorWidget._sync_current_form = fake_sync
        try:
            result = w.collect_data()
        finally:
            EntityEditorWidget._sync_current_form = original_sync

        assert synced, "collect_data() must call _sync_current_form()"
        assert result[0]["name"] == "Gojo"

    def test_on_entity_selected_flushes_previous_row(self) -> None:
        """Selecting a new entity must flush the form data for the PREVIOUS row."""
        from ui.widgets.entity_editor import EntityEditorWidget

        w = EntityEditorWidget.__new__(EntityEditorWidget)
        w._entities_data = [
            {"entity_id": "e0", "entity_type": "npc", "name": "Entity0", "stats": {}},
            {"entity_id": "e1", "entity_type": "npc", "name": "Entity1", "stats": {}},
        ]
        w._selected_row = 0  # Row 0 is currently displayed

        flushed_rows = []
        original_sync = EntityEditorWidget._sync_current_form

        def fake_sync(self_inner):
            flushed_rows.append(self_inner._selected_row)

        EntityEditorWidget._sync_current_form = fake_sync
        try:
            # Simulate selecting row 1 without a live Qt widget
            w._on_entity_selected(1)
        except Exception:
            pass  # AttributeError for missing Qt widgets is OK here
        finally:
            EntityEditorWidget._sync_current_form = original_sync

        assert 0 in flushed_rows, (
            "_on_entity_selected must flush row 0 (previous) before loading row 1"
        )

    def test_selected_row_advances_after_selection(self) -> None:
        """_selected_row must be updated to the new row after _on_entity_selected."""
        from ui.widgets.entity_editor import EntityEditorWidget

        w = EntityEditorWidget.__new__(EntityEditorWidget)
        w._entities_data = [
            {"entity_id": "e0", "entity_type": "npc", "name": "A", "stats": {}},
            {"entity_id": "e1", "entity_type": "npc", "name": "B", "stats": {}},
        ]
        w._selected_row = 0

        original_sync = EntityEditorWidget._sync_current_form
        EntityEditorWidget._sync_current_form = lambda s: None
        try:
            w._on_entity_selected(1)
        except Exception:
            pass  # Qt widget methods will fail without QApplication — that's fine
        finally:
            EntityEditorWidget._sync_current_form = original_sync

        assert w._selected_row == 1


class TestRuleEditorSync:
    """collect_data() and navigation must correctly target _selected_row."""

    def test_on_rule_selected_flushes_previous_row(self) -> None:
        """Selecting a new rule must flush the form for the PREVIOUS row, not the new one."""
        from ui.widgets.rule_editor import RuleEditorWidget

        w = RuleEditorWidget.__new__(RuleEditorWidget)
        w._rules_data = [
            {"rule_id": "r0", "priority": 0, "target_entity": "*",
             "conditions": {"operator": "AND", "clauses": []}, "actions": []},
            {"rule_id": "r1", "priority": 1, "target_entity": "*",
             "conditions": {"operator": "AND", "clauses": []}, "actions": []},
        ]
        w._selected_row = 0
        w._condition_rows = []
        w._action_rows = []

        flushed_rows = []
        original_sync = RuleEditorWidget._sync_current_form

        def fake_sync(self_inner):
            flushed_rows.append(self_inner._selected_row)

        RuleEditorWidget._sync_current_form = fake_sync
        try:
            w._on_rule_selected(1)
        except Exception:
            pass
        finally:
            RuleEditorWidget._sync_current_form = original_sync

        assert 0 in flushed_rows, (
            "_on_rule_selected must flush row 0 (previous) before loading row 1"
        )

    def test_selected_row_advances_after_selection(self) -> None:
        from ui.widgets.rule_editor import RuleEditorWidget

        w = RuleEditorWidget.__new__(RuleEditorWidget)
        w._rules_data = [
            {"rule_id": "r0", "priority": 0, "target_entity": "*",
             "conditions": {}, "actions": []},
            {"rule_id": "r1", "priority": 1, "target_entity": "*",
             "conditions": {}, "actions": []},
        ]
        w._selected_row = 0
        w._condition_rows = []
        w._action_rows = []

        original_sync = RuleEditorWidget._sync_current_form
        RuleEditorWidget._sync_current_form = lambda s: None
        try:
            w._on_rule_selected(1)
        except Exception:
            pass
        finally:
            RuleEditorWidget._sync_current_form = original_sync

        assert w._selected_row == 1

    def test_collect_data_calls_sync(self) -> None:
        from ui.widgets.rule_editor import RuleEditorWidget

        w = RuleEditorWidget.__new__(RuleEditorWidget)
        w._rules_data = [
            {"rule_id": "r0", "priority": 0, "target_entity": "*",
             "conditions": {"operator": "AND", "clauses": []}, "actions": []},
        ]
        w._selected_row = 0

        synced = []
        original_sync = RuleEditorWidget._sync_current_form

        def fake_sync(self_inner):
            synced.append(self_inner._selected_row)

        RuleEditorWidget._sync_current_form = fake_sync
        try:
            w.collect_data()
        finally:
            RuleEditorWidget._sync_current_form = original_sync

        assert synced, "collect_data() must call _sync_current_form()"
        assert 0 in synced
