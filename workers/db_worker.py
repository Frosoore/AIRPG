"""
workers/db_worker.py

Stateless Database Task Dispatcher for AIRPG.

Uses QThreadPool and QRunnable (from workers.db_tasks) to execute database
operations without the state-overwriting risks of a single QThread.
"""

from __future__ import annotations

import sqlite3
import json
from typing import Any

from PySide6.QtCore import QObject, Signal, QThreadPool

from database.schema import (
    get_connection,
    migrate_lore_book_table,
    migrate_stat_definitions_table,
    migrate_entities_table,
    migrate_scheduled_events_table,
    migrate_timeline_table
)
from workers.db_tasks import (
    LoadStatsTask, LoadCheckpointsTask, RewindTask, AppendEventTask,
    LoadSessionHistoryTask, UpdateVariantTask, SnapshotTask, DeleteSaveTask,
    PopulateEntitiesTask, TickModifiersTask, CreatePlayerEntityTask, DeleteEntityTask,
    LoadInventoryTask, LoadTimelineTask
)


class DbWorker(QObject):
    """Dispatches DB tasks to a QThreadPool.
    
    This replaces the old QThread-based DbWorker to prevent race conditions
    where multiple task setups would overwrite each other's parameters.
    """

    stats_loaded = Signal(list)
    inventory_loaded = Signal(dict)
    timeline_loaded = Signal(list)
    checkpoints_loaded = Signal(list)
    rewind_complete = Signal(dict)
    universe_meta_loaded = Signal(dict)
    stat_definitions_loaded = Signal(list)
    entities_loaded = Signal(list)
    rules_loaded = Signal(list)
    lore_book_loaded = Signal(list)
    scheduled_events_loaded = Signal(list)
    personas_loaded = Signal(list)
    library_loaded = Signal(list)
    saves_loaded = Signal(list)
    history_loaded = Signal(list, int)
    full_universe_loaded = Signal(dict)
    modifiers_ticked = Signal(list)
    variant_updated = Signal(str)
    integrity_validated = Signal(bool, dict)
    save_complete = Signal()
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(self, db_path: str) -> None:
        super().__init__()
        self._db_path = db_path
        self._pool = QThreadPool.globalInstance()
        self._active_tasks: set[Any] = set()

    def _setup_task(self, task):
        """Connect task signals to worker signals and start it."""
        task.signals.status.connect(self.status_update.emit)
        task.signals.error.connect(self.error_occurred.emit)
        
        # Prevent GC of the task object
        self._active_tasks.add(task)
        task.signals.finished.connect(lambda: self._active_tasks.discard(task))
        
        self._pool.start(task)
        return task

    # ------------------------------------------------------------------
    # Dispatched Tasks
    # ------------------------------------------------------------------

    def load_stats(self, save_id: str) -> None:
        task = LoadStatsTask(self._db_path, save_id)
        task.signals.result.connect(self.stats_loaded.emit)
        self._setup_task(task)

    def load_inventory(self, save_id: str) -> None:
        task = LoadInventoryTask(self._db_path, save_id)
        task.signals.result.connect(self.inventory_loaded.emit)
        self._setup_task(task)

    def load_timeline(self, save_id: str) -> None:
        task = LoadTimelineTask(self._db_path, save_id)
        task.signals.result.connect(self.timeline_loaded.emit)
        self._setup_task(task)

    def load_stats_and_inventory(self, save_id: str) -> None:
        """Fetch both stats and inventory for all active entities."""
        from workers.db_tasks import LoadStatsAndInventoryTask
        task = LoadStatsAndInventoryTask(self._db_path, save_id)
        task.signals.result.connect(lambda res: (self.stats_loaded.emit(res[0]), self.inventory_loaded.emit(res[1])))
        self._setup_task(task)

    def load_full_game_state(self, save_id: str) -> None:
        """Fetch stats, inventory, and timeline in one go."""
        from workers.db_tasks import LoadFullGameStateTask
        task = LoadFullGameStateTask(self._db_path, save_id)
        task.signals.result.connect(lambda res: (
            self.stats_loaded.emit(res[0]), 
            self.inventory_loaded.emit(res[1]),
            self.timeline_loaded.emit(res[2])
        ))
        self._setup_task(task)

    def load_checkpoints(self, save_id: str) -> None:
        task = LoadCheckpointsTask(self._db_path, save_id)
        task.signals.result.connect(self.checkpoints_loaded.emit)
        self._setup_task(task)

    def validate_integrity(self, save_id: str) -> None:
        from workers.db_tasks import ValidateIntegrityTask
        task = ValidateIntegrityTask(self._db_path, save_id)
        task.signals.result.connect(lambda res: self.integrity_validated.emit(res[0], res[1]))
        self._setup_task(task)

    def execute_rewind(self, save_id: str, target_turn_id: int) -> None:
        task = RewindTask(self._db_path, save_id, target_turn_id)
        task.signals.result.connect(self.rewind_complete.emit)
        self._setup_task(task)

    def append_event(self, save_id: str, turn_id: int, etype: str, target: str, payload: Any) -> None:
        task = AppendEventTask(self._db_path, save_id, turn_id, etype, target, payload)
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def load_session_history(self, save_id: str) -> None:
        task = LoadSessionHistoryTask(self._db_path, save_id)
        task.signals.result.connect(lambda res: self.history_loaded.emit(res[0], res[1]))
        self._setup_task(task)

    def switch_narrative_variant(self, save_id: str, turn_id: int, index: int) -> None:
        task = UpdateVariantTask(self._db_path, save_id, turn_id, index)
        task.signals.result.connect(self.variant_updated.emit)
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def delete_save(self, save_id: str) -> None:
        task = DeleteSaveTask(self._db_path, save_id)
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def tick_modifiers(self, save_id: str, elapsed_minutes: int) -> None:
        task = TickModifiersTask(self._db_path, save_id, elapsed_minutes)
        task.signals.result.connect(self.modifiers_ticked.emit)
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def create_player_entity(self, name: str, description: str = "") -> None:
        task = CreatePlayerEntityTask(self._db_path, name, description)
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def delete_entity(self, entity_id: str) -> None:
        task = DeleteEntityTask(self._db_path, entity_id)
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def take_snapshot_async(self, save_id: str, turn_id: int) -> None:
        """Periodic background snapshot to keep Event Sourcing performance high."""
        task = SnapshotTask(self._db_path, save_id, turn_id)
        self._setup_task(task)

    def populate_entities(self, mode: str = "auto", custom_text: str | None = None) -> None:
        """AI-driven entity generation (asynchronous)."""
        task = PopulateEntitiesTask(self._db_path, mode, custom_text)
        task.signals.result.connect(lambda _: self.load_full_universe())
        self._setup_task(task)

    def populate_lore(self, mode: str = "auto", custom_text: str | None = None) -> None:
        """AI-driven lore book generation (asynchronous)."""
        from workers.db_tasks import PopulateLoreTask
        task = PopulateLoreTask(self._db_path, mode, custom_text)
        task.signals.result.connect(lambda _: self.load_full_universe())
        self._setup_task(task)

    def populate_meta(self, mode: str = "auto", custom_text: str | None = None) -> None:
        from workers.db_tasks import PopulateMetaTask
        task = PopulateMetaTask(self._db_path, mode, custom_text)
        task.signals.result.connect(lambda _: self.load_full_universe())
        self._setup_task(task)

    def populate_stats(self, mode: str = "auto", custom_text: str | None = None) -> None:
        from workers.db_tasks import PopulateStatsTask
        task = PopulateStatsTask(self._db_path, mode, custom_text)
        task.signals.result.connect(lambda _: self.load_full_universe())
        self._setup_task(task)

    def populate_rules(self, mode: str = "auto", custom_text: str | None = None) -> None:
        from workers.db_tasks import PopulateRulesTask
        task = PopulateRulesTask(self._db_path, mode, custom_text)
        task.signals.result.connect(lambda _: self.load_full_universe())
        self._setup_task(task)

    def populate_events(self, mode: str = "auto", custom_text: str | None = None) -> None:
        from workers.db_tasks import PopulateEventsTask
        task = PopulateEventsTask(self._db_path, mode, custom_text)
        task.signals.result.connect(lambda _: self.load_full_universe())
        self._setup_task(task)

    # ------------------------------------------------------------------
    # Legacy/Remaining tasks (to be refactored into db_tasks.py later if needed)
    # For now, we run them synchronously in a wrapper task for compatibility
    # ------------------------------------------------------------------

    def load_universe_meta(self) -> None:
        class TempTask(LoadStatsTask):
            def execute(self) -> dict:
                with get_connection(self.db_path) as conn:
                    rows = conn.execute("SELECT key, value FROM Universe_Meta;").fetchall()
                return {row[0]: row[1] for row in rows}
        
        task = TempTask(self._db_path, "")
        task.signals.result.connect(self.universe_meta_loaded.emit)
        self._setup_task(task)

    def load_entities_and_rules(self) -> None:
        class TempTask(LoadStatsTask):
            def execute(self) -> tuple:
                migrate_lore_book_table(self.db_path)
                migrate_stat_definitions_table(self.db_path)
                migrate_entities_table(self.db_path)
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    e_rows = conn.execute("SELECT entity_id, entity_type, name, description FROM Entities WHERE is_active = 1;").fetchall()
                    entities = []
                    for r in e_rows:
                        eid = r["entity_id"]
                        stats = {s["stat_key"]: s["stat_value"] for s in conn.execute("SELECT stat_key, stat_value FROM Entity_Stats WHERE entity_id = ?;", (eid,))}
                        entities.append({
                            "entity_id": eid,
                            "entity_type": r["entity_type"],
                            "name": r["name"],
                            "description": r["description"],
                            "stats": stats
                        })
                    
                    rules = []
                    r_rows = conn.execute("SELECT rule_id, priority, conditions, actions, target_entity FROM Rules;").fetchall()
                    for r in r_rows:
                        rules.append({
                            "rule_id": r["rule_id"], "priority": r["priority"],
                            "conditions": json.loads(r["conditions"]) if r["conditions"] else {},
                            "actions": json.loads(r["actions"]) if r["actions"] else [],
                            "target_entity": r["target_entity"]
                        })
                    
                    lb_rows = conn.execute("SELECT entry_id, category, name, content FROM Lore_Book;").fetchall()
                    lore = [{"entry_id": r["entry_id"], "category": r["category"], "name": r["name"], "content": r["content"]} for r in lb_rows]

                    sd_rows = conn.execute("SELECT stat_id, name, description, value_type, parameters FROM Stat_Definitions;").fetchall()
                    stat_defs = []
                    for r in sd_rows:
                        stat_defs.append({
                            "stat_id": r["stat_id"], "name": r["name"], "description": r["description"],
                            "value_type": r["value_type"], "parameters": json.loads(r["parameters"])
                        })
                return entities, rules, lore, stat_defs

        task = TempTask(self._db_path, "")
        task.signals.result.connect(lambda res: (
            self.entities_loaded.emit(res[0]),
            self.rules_loaded.emit(res[1]),
            self.lore_book_loaded.emit(res[2]),
            self.stat_definitions_loaded.emit(res[3])
        ))
        self._setup_task(task)

    def save_universe_meta(self, meta: dict) -> None:
        """Atomic update of multiple keys in Universe_Meta."""
        class TempTask(LoadStatsTask):
            def execute(self) -> bool:
                with sqlite3.connect(self.db_path) as conn:
                    for k, v in meta.items():
                        conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES (?, ?);", (k, str(v)))
                    conn.commit()
                return True
        task = TempTask(self._db_path, "")
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def save_full_universe(self, entities, rules, meta, lore_book, stat_definitions=None, scheduled_events=None, story_setup=None) -> None:
        class TempTask(LoadStatsTask):
            def execute(self) -> bool:
                from database.schema import migrate_story_setup_table
                migrate_lore_book_table(self.db_path)
                migrate_stat_definitions_table(self.db_path)
                migrate_entities_table(self.db_path)
                migrate_scheduled_events_table(self.db_path)
                migrate_story_setup_table(self.db_path)
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("PRAGMA foreign_keys=ON;")
                    conn.execute("DELETE FROM Entity_Stats;")
                    conn.execute("DELETE FROM Entities;")
                    for e in entities:
                        eid = e.get("entity_id", "").strip()
                        if not eid: continue
                        conn.execute("INSERT INTO Entities (entity_id, entity_type, name, description, is_active) VALUES (?, ?, ?, ?, 1);",
                                   (eid, e.get("entity_type", "npc"), e.get("name", ""), e.get("description", "")))
                        for sk, sv in e.get("stats", {}).items():
                            conn.execute("INSERT INTO Entity_Stats (entity_id, stat_key, stat_value) VALUES (?, ?, ?);", (eid, str(sk), str(sv)))
                    
                    conn.execute("DELETE FROM Rules;")
                    for r in rules:
                        conn.execute("INSERT INTO Rules (rule_id, priority, conditions, actions, target_entity) VALUES (?, ?, ?, ?, ?);",
                                   (r["rule_id"], int(r.get("priority", 0)), json.dumps(r.get("conditions", {})), json.dumps(r.get("actions", [])), r.get("target_entity", "*")))
                    
                    conn.execute("DELETE FROM Stat_Definitions;")
                    if stat_definitions:
                        for s in stat_definitions:
                            conn.execute("INSERT INTO Stat_Definitions (stat_id, name, description, value_type, parameters) VALUES (?, ?, ?, ?, ?);",
                                       (s["stat_id"], s["name"], s.get("description", ""), s["value_type"], json.dumps(s.get("parameters", {}))))

                    for k, v in meta.items():
                        conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES (?, ?);", (k, str(v)))
                    
                    conn.execute("DELETE FROM Lore_Book;")
                    for l in lore_book:
                        conn.execute("INSERT INTO Lore_Book (entry_id, category, name, content) VALUES (?, ?, ?, ?);", (l["entry_id"], l.get("category", ""), l.get("name", ""), l.get("content", "")))
                    
                    conn.execute("DELETE FROM Scheduled_Events;")
                    if scheduled_events:
                        for ev in scheduled_events:
                            conn.execute("INSERT INTO Scheduled_Events (event_id, trigger_minute, title, description) VALUES (?, ?, ?, ?);",
                                       (ev["event_id"], int(ev["trigger_minute"]), ev["title"], ev["description"]))
                    
                    conn.execute("DELETE FROM Story_Setup;")
                    if story_setup:
                        for ss in story_setup:
                            conn.execute(
                                "INSERT INTO Story_Setup (setup_id, question, type, options, max_selections, priority) VALUES (?, ?, ?, ?, ?, ?);",
                                (ss["setup_id"], ss["question"], ss["type"], json.dumps(ss.get("options", [])), ss.get("max_selections", 1), ss.get("priority", 0))
                            )
                    conn.commit()
                return True

        task = TempTask(self._db_path, "")
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)

    def load_library(self, library_dir: str) -> None:
        from pathlib import Path
        from workers.db_helpers import read_universe_card_metadata
        class TempTask(LoadStatsTask):
            def execute(self) -> list:
                db_files = sorted(Path(library_dir).glob("*.db"))
                results = []
                for fpath in db_files:
                    name, updated, difficulty = read_universe_card_metadata(str(fpath))
                    results.append({"db_path": str(fpath), "name": name, "last_updated": updated, "difficulty": difficulty})
                return results
        task = TempTask(self._db_path, "")
        task.signals.result.connect(self.library_loaded.emit)
        self._setup_task(task)

    def load_saves_async(self) -> None:
        from workers.db_helpers import load_saves
        class TempTask(LoadStatsTask):
            def execute(self) -> list:
                return load_saves(self.db_path)
        task = TempTask(self._db_path, "")
        task.signals.result.connect(self.saves_loaded.emit)
        self._setup_task(task)

    def load_full_universe(self, save_id: str = "") -> None:
        """Atomic load of entities, rules, lore book, meta, stat definitions, scheduled events, and optionally history."""
        class TempTask(LoadStatsTask):
            def execute(self) -> tuple:
                migrate_lore_book_table(self.db_path)
                migrate_stat_definitions_table(self.db_path)
                migrate_entities_table(self.db_path)
                migrate_scheduled_events_table(self.db_path)
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    # 1. Entities
                    e_rows = conn.execute("SELECT entity_id, entity_type, name, description FROM Entities WHERE is_active = 1;").fetchall()
                    entities = []
                    for r in e_rows:
                        eid = r["entity_id"]
                        stats = {s["stat_key"]: s["stat_value"] for s in conn.execute("SELECT stat_key, stat_value FROM Entity_Stats WHERE entity_id = ?;", (eid,))}
                        entities.append({
                            "entity_id": eid,
                            "entity_type": r["entity_type"],
                            "name": r["name"],
                            "description": r["description"],
                            "stats": stats
                        })
                    
                    # 2. Rules
                    rules = []
                    r_rows = conn.execute("SELECT rule_id, priority, conditions, actions, target_entity FROM Rules;").fetchall()
                    for r in r_rows:
                        rules.append({
                            "rule_id": r["rule_id"], "priority": r["priority"],
                            "conditions": json.loads(r["conditions"]) if r["conditions"] else {},
                            "actions": json.loads(r["actions"]) if r["actions"] else [],
                            "target_entity": r["target_entity"]
                        })
                    
                    # 3. Lore
                    lb_rows = conn.execute("SELECT entry_id, category, name, content FROM Lore_Book;").fetchall()
                    lore = [{"entry_id": r["entry_id"], "category": r["category"], "name": r["name"], "content": r["content"]} for r in lb_rows]
                    
                    # 4. Meta
                    m_rows = conn.execute("SELECT key, value FROM Universe_Meta;").fetchall()
                    meta = {row["key"]: row["value"] for row in m_rows}

                    # 5. Stat Definitions
                    sd_rows = conn.execute("SELECT stat_id, name, description, value_type, parameters FROM Stat_Definitions;").fetchall()
                    stat_defs = []
                    for r in sd_rows:
                        stat_defs.append({
                            "stat_id": r["stat_id"], "name": r["name"], "description": r["description"],
                            "value_type": r["value_type"], "parameters": json.loads(r["parameters"])
                        })
                    
                    # 6. Scheduled Events
                    se_rows = conn.execute("SELECT event_id, trigger_minute, title, description FROM Scheduled_Events;").fetchall()
                    scheduled_events = [{"event_id": r["event_id"], "trigger_minute": r["trigger_minute"], "title": r["title"], "description": r["description"]} for r in se_rows]

                    # 7. Story Setup
                    from database.schema import migrate_story_setup_table
                    migrate_story_setup_table(self.db_path)
                    ss_rows = conn.execute("SELECT setup_id, question, type, options, max_selections, priority FROM Story_Setup ORDER BY priority ASC;").fetchall()
                    story_setup = [{
                        "setup_id": r["setup_id"],
                        "question": r["question"],
                        "type": r["type"],
                        "options": json.loads(r["options"]),
                        "max_selections": r["max_selections"],
                        "priority": r["priority"]
                    } for r in ss_rows]

                    # 8. History
                    history = []
                    max_tid = 0
                    if save_id:
                        h_rows = conn.execute("SELECT turn_id, event_type, payload FROM Event_Log WHERE save_id = ? AND event_type IN ('user_input', 'narrative_text') ORDER BY event_id ASC;", (save_id,)).fetchall()
                        for row in h_rows:
                            max_tid = max(max_tid, row[0])
                            history.append({"turn_id": row[0], "event_type": row[1], "payload": json.loads(row[2])})
                            
                return entities, rules, lore, meta, stat_defs, scheduled_events, story_setup, history, max_tid

        task = TempTask(self._db_path, save_id)
        task.signals.result.connect(lambda res: (
            self.entities_loaded.emit(res[0]),
            self.rules_loaded.emit(res[1]),
            self.lore_book_loaded.emit(res[2]),
            self.universe_meta_loaded.emit(res[3]),
            self.stat_definitions_loaded.emit(res[4]),
            self.scheduled_events_loaded.emit(res[5]),
            self.full_universe_loaded.emit({
                "entities": res[0],
                "rules": res[1],
                "lore_book": res[2],
                "meta": res[3],
                "stat_definitions": res[4],
                "scheduled_events": res[5],
                "story_setup": res[6]
            }),
            self.history_loaded.emit(res[7], res[8]) if save_id else None
        ))
        self._setup_task(task)

    def load_global_personas(self) -> None:
        class TempTask(LoadStatsTask):
            def execute(self) -> list:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute("SELECT persona_id, name, description FROM Global_Personas;").fetchall()
                return [dict(r) for r in rows]
        task = TempTask(self._db_path, "")
        task.signals.result.connect(self.personas_loaded.emit)
        self._setup_task(task)

    def save_global_personas(self, personas: list[dict]) -> None:
        class TempTask(LoadStatsTask):
            def execute(self) -> bool:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("DELETE FROM Global_Personas;")
                    for p in personas:
                        conn.execute("INSERT INTO Global_Personas (persona_id, name, description) VALUES (?, ?, ?);", (p["persona_id"], p["name"], p["description"]))
                    conn.commit()
                return True
        task = TempTask(self._db_path, "")
        task.signals.result.connect(lambda _: self.save_complete.emit())
        self._setup_task(task)
