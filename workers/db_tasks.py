"""
workers/db_tasks.py

Atomic, stateless database tasks for AIRPG using QRunnable and QThreadPool.
This eliminates the DbWorker state-overwriting anti-pattern.
"""

from __future__ import annotations

import json
import re
import sqlite3
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from database.event_sourcing import EventSourcer
from database.checkpoint import CheckpointManager
from database.schema import get_connection


class TaskSignals(QObject):
    """Signals for QRunnable tasks."""
    result = Signal(object)
    error = Signal(str)
    status = Signal(str)
    finished = Signal()


class BaseDbTask(QRunnable):
    """Base class for all stateless DB tasks."""
    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.execute()
            self.signals.result.emit(result)
        except Exception as exc:
            print(f"DB Task Error: {exc}\n{traceback.format_exc()}")
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()

    def execute(self) -> Any:
        raise NotImplementedError("Subclasses must implement execute()")


# ---------------------------------------------------------------------------
# Task Implementations
# ---------------------------------------------------------------------------

class LoadStatsTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> list[dict]:
        self.signals.status.emit("Loading stats...")
        with get_connection(self.db_path) as conn:
            entity_rows = conn.execute(
                "SELECT e.entity_id, e.name, e.entity_type "
                "FROM Entities e WHERE e.is_active = 1;"
            ).fetchall()

        es = EventSourcer(self.db_path)
        snapshots: list[dict] = []
        for row in entity_rows:
            entity_id = row[0]
            stats = es.get_current_stats(self.save_id, entity_id)
            snapshots.append({
                "entity_id": entity_id,
                "name": row[1],
                "entity_type": row[2],
                "stats": stats,
            })
        return snapshots


class LoadCheckpointsTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> list[int]:
        self.signals.status.emit("Loading checkpoints...")
        cm = CheckpointManager(self.db_path)
        return cm.list_checkpoints(self.save_id)


class RewindTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str, target_turn_id: int):
        super().__init__(db_path)
        self.save_id = save_id
        self.target_turn_id = target_turn_id

    def execute(self) -> dict:
        self.signals.status.emit(f"Rewinding to turn {self.target_turn_id}...")
        
        # Fail-safe: Create an auto-backup before destructive rewind
        from database.backup_manager import create_auto_backup
        create_auto_backup(self.db_path, f"rewind_to_turn_{self.target_turn_id}")
        
        cm = CheckpointManager(self.db_path)
        return cm.rewind(self.save_id, self.target_turn_id)


class SnapshotTask(BaseDbTask):
    """Background task to take a state snapshot without blocking the main flow."""
    def __init__(self, db_path: str, save_id: str, turn_id: int):
        super().__init__(db_path)
        self.save_id = save_id
        self.turn_id = turn_id

    def execute(self) -> bool:
        self.signals.status.emit(f"Background snapshotting turn {self.turn_id}...")
        es = EventSourcer(self.db_path)
        es.take_snapshot(self.save_id, self.turn_id)
        return True


class AppendEventTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str, turn_id: int, etype: str, target: str, payload: Any):
        super().__init__(db_path)
        self.save_id = save_id
        self.turn_id = turn_id
        self.etype = etype
        self.target = target
        self.payload = payload

    def execute(self) -> int:
        es = EventSourcer(self.db_path)
        event_id = es.append_event(
            self.save_id, self.turn_id, self.etype, self.target, self.payload
        )
        return event_id


class LoadSessionHistoryTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> tuple[list[dict], int, str]:
        with get_connection(self.db_path) as conn:
            # Fetch difficulty
            row = conn.execute("SELECT difficulty FROM Saves WHERE save_id = ?;", (self.save_id,)).fetchone()
            difficulty = row[0] if row else "Normal"

            rows = conn.execute(
                "SELECT turn_id, event_type, payload FROM Event_Log "
                "WHERE save_id = ? AND event_type IN ('user_input', 'narrative_text', 'hero_intent') "
                "ORDER BY event_id ASC;",
                (self.save_id,)
            ).fetchall()

        history: list[dict] = []
        max_turn_id = 0
        for row in rows:
            turn_id = row[0]
            max_turn_id = max(max_turn_id, turn_id)
            history.append({
                "turn_id": turn_id,
                "event_type": row[1],
                "payload": json.loads(row[2])
            })
        return history, max_turn_id, difficulty


class UpdateVariantTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str, turn_id: int, index: int):
        super().__init__(db_path)
        self.save_id = save_id
        self.turn_id = turn_id
        self.index = index

    def execute(self) -> str:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM Event_Log "
                "WHERE save_id = ? AND turn_id = ? AND event_type = 'narrative_text';",
                (self.save_id, self.turn_id)
            ).fetchone()
            
            if not row:
                raise ValueError("Event not found for variant update.")
            
            payload_data = json.loads(row[0])
            if not isinstance(payload_data, dict) or "variants" not in payload_data:
                text = payload_data.get("text", "") if isinstance(payload_data, dict) else str(payload_data)
                payload_data = {"active": 0, "variants": [text]}
            
            payload_data["active"] = self.index
            new_text = payload_data["variants"][self.index]
            
            conn.execute(
                "UPDATE Event_Log SET payload = ? "
                "WHERE save_id = ? AND turn_id = ? AND event_type = 'narrative_text';",
                (json.dumps(payload_data), self.save_id, self.turn_id)
            )
            conn.commit()
        return new_text


class DeleteSaveTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> bool:
        from pathlib import Path
        import shutil
        self.signals.status.emit("Deleting save...")
        
        # 1. Delete from SQLite (cascades to Event_Log, State_Cache)
        with get_connection(self.db_path) as conn:
            conn.execute("DELETE FROM Saves WHERE save_id = ?;", (self.save_id,))
            conn.commit()

        # 2. Delete Vector Memory directory if it exists
        from core.paths import VECTOR_DIR
        vector_dir = VECTOR_DIR / self.save_id
        if vector_dir.exists():
            shutil.rmtree(str(vector_dir))

        self.signals.status.emit("Save deleted.")
        return True


class TickModifiersTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str, elapsed_minutes: int):
        super().__init__(db_path)
        self.save_id = save_id
        self.elapsed_minutes = elapsed_minutes

    def execute(self) -> list[str]:
        from database.modifier_processor import ModifierProcessor
        mp = ModifierProcessor(self.db_path)
        return mp.tick_modifiers(self.save_id, self.elapsed_minutes)


class PopulateMetaTask(BaseDbTask):
    """AI-driven metadata refinement (Name, Global Lore, First Message)."""
    def __init__(self, db_path: str, mode: str = "auto", custom_text: str | None = None):
        super().__init__(db_path)
        self.mode = mode
        self.custom_text = custom_text

    def execute(self) -> bool:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_meta_prompt
        
        self.signals.status.emit("Initializing AI backend...")
        cfg = load_config()
        try:
            llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
        except Exception as e:
            print(f"[POPULATE_META] Failed to build LLM backend: {e}")
            return False
            
        with get_connection(self.db_path) as conn:
            meta_rows = conn.execute("SELECT key, value FROM Universe_Meta;").fetchall()
            current_meta = {r[0]: r[1] for r in meta_rows}

        self.signals.status.emit("Refining universe metadata...")
        prompt = build_populate_meta_prompt(current_meta, 
                                            custom_instruction=self.custom_text if self.mode == "custom" else None)
        
        resp = llm.complete(prompt, response_format="json")
        data = resp.tool_call if isinstance(resp.tool_call, dict) else {}
        
        if data:
            with get_connection(self.db_path) as conn:
                if "universe_name" in data:
                    conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES ('universe_name', ?);", (data["universe_name"],))
                if "global_lore" in data:
                    conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES ('global_lore', ?);", (data["global_lore"],))
                if "system_prompt" in data:
                    conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES ('system_prompt', ?);", (data["system_prompt"],))
                if "first_message" in data:
                    conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES ('first_message', ?);", (data["first_message"],))
                conn.commit()
            self.signals.status.emit("Metadata refinement complete.")
            return True
    
        return False

class PopulateStatsTask(BaseDbTask):
    """AI-driven stat definitions generation."""
    def __init__(self, db_path: str, mode: str = "auto", custom_text: str | None = None):
        super().__init__(db_path)
        self.mode = mode
        self.custom_text = custom_text

    def execute(self) -> int:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_stats_prompt
        
        cfg = load_config()
        llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
            
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT value FROM Universe_Meta WHERE key = 'global_lore';").fetchone()
            global_lore = row[0] if row else ""
            st_rows = conn.execute("SELECT name FROM Stat_Definitions;").fetchall()
            existing_stats = [r[0] for r in st_rows]

        self.signals.status.emit("Generating stat definitions...")
        prompt = build_populate_stats_prompt(global_lore, existing_stats, 
                                             custom_instruction=self.custom_text if self.mode == "custom" else None)
        
        resp = llm.complete(prompt, response_format="json")
        data = resp.tool_call
        
        # Heuristic: support both wrapped and raw lists
        batch = []
        if isinstance(data, list):
            batch = data
        elif isinstance(data, dict):
            batch = data.get("stats", [])
        
        inserted = 0
        if batch:
            import uuid
            with get_connection(self.db_path) as conn:
                for s in batch:
                    name = s.get("name")
                    if name and name not in existing_stats:
                        stat_id = re.sub(r'[^a-z0-9]', '_', name.lower()).strip('_')
                        if not stat_id: stat_id = uuid.uuid4().hex[:8]
                        
                        conn.execute(
                            "INSERT INTO Stat_Definitions (stat_id, name, description, value_type, parameters) VALUES (?, ?, ?, ?, ?);",
                            (stat_id, name, s.get("description", ""), s.get("value_type", "numeric"), json.dumps(s.get("parameters", {})))
                        )
                        inserted += 1
                conn.commit()
            self.signals.status.emit(f"Stats generation complete: {inserted} added.")
            return inserted
        
        return 0

class PopulateRulesTask(BaseDbTask):
    """AI-driven rule generation."""
    def __init__(self, db_path: str, mode: str = "auto", custom_text: str | None = None):
        super().__init__(db_path)
        self.mode = mode
        self.custom_text = custom_text

    def execute(self) -> int:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_rules_prompt
        
        cfg = load_config()
        llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
            
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT value FROM Universe_Meta WHERE key = 'global_lore';").fetchone()
            global_lore = row[0] if row else ""
            st_rows = conn.execute("SELECT name FROM Stat_Definitions;").fetchall()
            stat_names = [r[0] for r in st_rows]
            rl_rows = conn.execute("SELECT rule_id FROM Rules;").fetchall()
            existing_rules = [r[0] for r in rl_rows]

        self.signals.status.emit("Generating game rules...")
        prompt = build_populate_rules_prompt(global_lore, stat_names, existing_rules, 
                                              custom_instruction=self.custom_text if self.mode == "custom" else None)
        
        resp = llm.complete(prompt, response_format="json")
        data = resp.tool_call
        
        batch = []
        if isinstance(data, list): batch = data
        elif isinstance(data, dict):
            batch = data.get("rules", [])
        
        inserted = 0
        if batch:
            import uuid
            with get_connection(self.db_path) as conn:
                for r in batch:
                    rule_id = r.get("rule_id")
                    if not rule_id: rule_id = uuid.uuid4().hex[:8]
                    
                    if rule_id not in existing_rules:
                        conn.execute(
                            "INSERT INTO Rules (rule_id, priority, conditions, actions, target_entity) VALUES (?, ?, ?, ?, ?);",
                            (rule_id, r.get("priority", 0), json.dumps(r.get("conditions", {})), json.dumps(r.get("actions", [])), r.get("target_entity", "*"))
                        )
                        inserted += 1
                conn.commit()
            return inserted
        return 0

class PopulateEventsTask(BaseDbTask):
    """AI-driven event scheduling."""
    def __init__(self, db_path: str, mode: str = "auto", custom_text: str | None = None):
        super().__init__(db_path)
        self.mode = mode
        self.custom_text = custom_text

    def execute(self) -> int:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_events_prompt
        
        cfg = load_config()
        llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
            
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT value FROM Universe_Meta WHERE key = 'global_lore';").fetchone()
            global_lore = row[0] if row else ""
            ev_rows = conn.execute("SELECT title FROM Scheduled_Events;").fetchall()
            existing_events = [r[0] for r in ev_rows]

        self.signals.status.emit("Scheduling world events...")
        prompt = build_populate_events_prompt(global_lore, existing_events, 
                                              custom_instruction=self.custom_text if self.mode == "custom" else None)
        
        resp = llm.complete(prompt, response_format="json")
        data = resp.tool_call
        
        batch = []
        if isinstance(data, list): batch = data
        elif isinstance(data, dict):
            batch = data.get("events", [])
        
        inserted = 0
        if batch:
            import uuid
            with get_connection(self.db_path) as conn:
                for ev in batch:
                    event_id = ev.get("event_id")
                    if not event_id:
                        title = ev.get("title", "event")
                        event_id = re.sub(r'[^a-z0-9]', '_', title.lower()).strip('_')
                        if not event_id: event_id = uuid.uuid4().hex[:8]
                    
                    conn.execute(
                        "INSERT INTO Scheduled_Events (event_id, title, description, trigger_minute) VALUES (?, ?, ?, ?);",
                        (event_id, ev.get("title", "Event"), ev.get("description", ""), ev.get("trigger_minute", 0))
                    )
                    inserted += 1
                conn.commit()
            return inserted
        return 0

class PopulateEntitiesTask(BaseDbTask):
    """Asynchronous entity generation using LLM.
    
    Reads world context or custom prompt, and inserts new
    entities into the database idempotently.
    """
    def __init__(self, db_path: str, mode: str = "auto", custom_text: str | None = None):
        super().__init__(db_path)
        self.mode = mode
        self.custom_text = custom_text

    def execute(self) -> int:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_prompt
        
        self.signals.status.emit("Initializing AI backend...")
        cfg = load_config()
        llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
        
        # 1. Gather context
        self.signals.status.emit("Gathering context...")
        with get_connection(self.db_path) as conn:
            # Universe Meta
            meta_rows = conn.execute("SELECT key, value FROM Universe_Meta;").fetchall()
            meta = {row[0]: row[1] for row in meta_rows}
            
            # Lore Book
            lore_rows = conn.execute("SELECT name, content, category FROM Lore_Book;").fetchall()
            
            # Stat Definitions
            stat_rows = conn.execute("SELECT name, description, value_type, parameters FROM Stat_Definitions;").fetchall()
            stat_defs = []
            for r in stat_rows:
                try:
                    params = json.loads(r[3]) if r[3] else {}
                except:
                    params = {}
                stat_defs.append({
                    "name": r[0],
                    "description": r[1],
                    "value_type": r[2],
                    "parameters": params
                })

            # Existing entities for idempotence
            ent_rows = conn.execute("SELECT entity_id, name FROM Entities;").fetchall()
            existing_ids = {str(row[0]).lower() for row in ent_rows}
            existing_names = [str(row[1]) for row in ent_rows if row[1]]

        # 2. Prepare chunks
        chunks = []
        if self.mode == "custom" and self.custom_text:
            chunks.append(self.custom_text)
        else:
            # Always include Global Lore as a distinct chunk if it exists
            global_lore = meta.get("global_lore", "").strip()
            if global_lore:
                chunks.append(f"=== GLOBAL WORLD LORE ===\n{global_lore}")

            # Each lore entry becomes its own individual chunk
            for name, content, cat in lore_rows:
                cat = cat or "General"
                chunks.append(f"=== CATEGORY: {cat} ===\n### Name: {name}\n{content}")

        if not chunks:
            chunks = ["(No context found)"]

        # 3. Process each chunk
        new_entities_found = []
        
        for i, chunk in enumerate(chunks):
            self.signals.status.emit(f"Processing chunk {i+1}/{len(chunks)}...")
            
            prompt = build_populate_prompt(chunk, existing_names, stat_defs,
                                           custom_instruction=self.custom_text if self.mode == "custom" else None)
            
            # Force JSON format at the API level
            resp = llm.complete(prompt, response_format="json")
            
            # Resilient JSON parsing
            data = resp.tool_call
            
            batch = []
            if isinstance(data, list):
                batch = data
            elif isinstance(data, dict):
                if "entities" in data:
                    batch = data["entities"]
                else:
                    # Fallback for single object return
                    batch = [data]
            
            if isinstance(batch, list):
                # Filter stats to ensure only defined ones are kept
                allowed_stats = {s["name"].lower() for s in stat_defs}
                for ent in batch:
                    if "stats" in ent and isinstance(ent["stats"], dict):
                        valid_stats = {}
                        stat_name_map = {s["name"].lower(): s["name"] for s in stat_defs}
                        for k, v in ent["stats"].items():
                            if k.lower() in allowed_stats:
                                valid_stats[stat_name_map[k.lower()]] = v
                        ent["stats"] = valid_stats
                new_entities_found.extend(batch)

        # 4. Filter and Insert
        self.signals.status.emit("Finalizing new entities...")
        inserted_count = 0
        valid_stat_names = {s["name"].lower(): s["name"] for s in stat_defs}
        
        with get_connection(self.db_path) as conn:
            for ent in new_entities_found:
                name = ent.get("name", "").strip()
                etype = str(ent.get("entity_type", "npc")).lower()
                description = ent.get("description", "").strip()
                stats_dict = ent.get("stats", {})
                
                if not name: continue
                
                eid = re.sub(r'[^a-z0-9]', '_', name.lower())
                eid = re.sub(r'_+', '_', eid).strip('_')
                if not eid: continue
                if etype not in ("npc", "faction"): etype = "npc"
                if eid in existing_ids: continue
                
                conn.execute(
                    "INSERT INTO Entities (entity_id, name, entity_type, description, is_active) VALUES (?, ?, ?, ?, 1);",
                    (eid, name, etype, description)
                )
                existing_ids.add(eid)
                existing_names.append(name)
                
                if isinstance(stats_dict, dict):
                    for skey, sval in stats_dict.items():
                        lower_key = skey.lower()
                        if lower_key in valid_stat_names:
                            real_name = valid_stat_names[lower_key]
                            conn.execute(
                                "INSERT INTO Entity_Stats (entity_id, stat_key, stat_value) VALUES (?, ?, ?);",
                                (eid, real_name, str(sval))
                            )
                inserted_count += 1
            conn.commit()
        
        return inserted_count

class PopulateLoreTask(BaseDbTask):
    """Asynchronous lore expansion using LLM."""
    def __init__(self, db_path: str, mode: str = "auto", custom_text: str | None = None):
        super().__init__(db_path)
        self.mode = mode
        self.custom_text = custom_text

    def execute(self) -> int:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_lore_prompt
        
        self.signals.status.emit("Initializing AI backend...")
        cfg = load_config()
        llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
            
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT value FROM Universe_Meta WHERE key = 'global_lore';").fetchone()
            global_lore = row[0] if row else ""
            ent_rows = conn.execute("SELECT name FROM Lore_Book;").fetchall()
            existing_entries = [r[0] for r in ent_rows]

        self.signals.status.emit("Generating lore expansion...")
        prompt = build_populate_lore_prompt(global_lore, existing_entries, 
                                            custom_instruction=self.custom_text if self.mode == "custom" else None)
        
        resp = llm.complete(prompt, response_format="json")
        data = resp.tool_call
        
        batch = []
        if isinstance(data, list): batch = data
        elif isinstance(data, dict):
            batch = data.get("lore_entries", [data] if "name" in data else [])
        
        inserted = 0
        if batch:
            import uuid
            with get_connection(self.db_path) as conn:
                for entry in batch:
                    name = entry.get("name")
                    if name and name not in existing_entries:
                        conn.execute(
                            "INSERT INTO Lore_Book (entry_id, category, name, content) VALUES (?, ?, ?, ?);",
                            (uuid.uuid4().hex, entry.get("category", "General"), name, entry.get("content", ""))
                        )
                        inserted += 1
                conn.commit()
            self.signals.status.emit(f"Lore expansion complete: {inserted} entries added.")
            return inserted
        
        self.signals.status.emit("Lore expansion complete: No new entries added.")
        return 0

class PopulateMapTask(BaseDbTask):
    """AI-driven map generation (Locations & Connections)."""
    def __init__(self, db_path: str, mode: str = "auto", custom_text: str | None = None):
        super().__init__(db_path)
        self.mode = mode
        self.custom_text = custom_text

    def execute(self) -> dict:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_map_prompt
        
        self.signals.status.emit("Initializing AI backend...")
        cfg = load_config()
        llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
            
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT value FROM Universe_Meta WHERE key = 'global_lore';").fetchone()
            global_lore = row[0] if row else ""
            loc_rows = conn.execute("SELECT location_id, name, scale FROM Locations;").fetchall()
            existing_locs = [dict(r) for r in loc_rows]

        self.signals.status.emit("Generating world map expansion...")
        prompt = build_populate_map_prompt(global_lore, existing_locs, 
                                           custom_instruction=self.custom_text if self.mode == "custom" else None)
        
        resp = llm.complete(prompt, response_format="json")
        data = resp.tool_call
        
        # Extremely robust parsing: search for the first dictionary if a list is returned
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    data = item
                    break
        
        if not isinstance(data, dict):
            print(f"[POPULATE_MAP] Invalid response format (expected dict or list containing dict, got {type(data)}): {data}")
            return {"added_locs": 0, "added_conns": 0}

        new_locs = data.get("locations", [])
        new_conns = data.get("connections", [])
        
        added_locs = 0
        added_conns = 0
        
        with get_connection(self.db_path) as conn:
            # Pre-fetch existing IDs to avoid redundant queries in loops
            existing_ids_rows = conn.execute("SELECT location_id FROM Locations;").fetchall()
            existing_ids = {str(r[0]) for r in existing_ids_rows}

            # 1. Insert Locations
            for l in new_locs:
                lid = l.get("location_id")
                if not lid: continue
                if lid in existing_ids: continue
                
                # Default name to scale if missing
                name = l.get("name", "").strip()
                scale = str(l.get("scale", "zone")).lower()
                if not name:
                    name = scale.capitalize()
                
                # Handle 'none'/'null' strings for parent_id
                pid = l.get("parent_id")
                if isinstance(pid, str) and pid.lower() in ("none", "null", ""):
                    pid = None
                
                conn.execute(
                    "INSERT INTO Locations (location_id, name, scale, parent_id, description, x, y) VALUES (?, ?, ?, ?, ?, ?, ?);",
                    (lid, name, scale, pid, l.get("description", ""), l.get("x", 0), l.get("y", 0))
                )
                existing_ids.add(lid)
                added_locs += 1
                
            # 2. Insert Connections
            for c in new_conns:
                src = c.get("source_id")
                tgt = c.get("target_id")
                if not src or not tgt: continue
                if src not in existing_ids or tgt not in existing_ids:
                    # Skip connections to non-existent nodes (safety)
                    continue
                
                # Bi-directional insert
                try:
                    dist = int(c.get("distance_km", 10))
                    conn.execute(
                        "INSERT OR IGNORE INTO Location_Connections (source_id, target_id, distance_km) VALUES (?, ?, ?);",
                        (src, tgt, dist)
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO Location_Connections (source_id, target_id, distance_km) VALUES (?, ?, ?);",
                        (tgt, src, dist)
                    )
                    added_conns += 1
                except:
                    pass
                    
            conn.commit()
            
        self.signals.status.emit(f"Map generation complete: {added_locs} locations, {added_conns} connections added.")
        return {"added_locs": added_locs, "added_conns": added_conns}

class CreatePlayerEntityTask(BaseDbTask):
    """Creates a new entity of type 'player' with initial stats."""
    def __init__(self, db_path: str, name: str, description: str = ""):
        super().__init__(db_path)
        self.name = name
        self.description = description

    def execute(self) -> str:
        self.signals.status.emit(f"Creating player entity '{self.name}'...")
        import re
        from datetime import datetime
        # 1. Generate safe ID
        eid = re.sub(r'[^a-z0-9]', '_', self.name.lower()).strip('_')
        if not eid:
            eid = f"player_{int(datetime.now().timestamp())}"
            
        with get_connection(self.db_path) as conn:
            # Check for collision
            row = conn.execute("SELECT 1 FROM Entities WHERE entity_id = ?;", (eid,)).fetchone()
            if row:
                eid = f"{eid}_{int(datetime.now().timestamp() % 1000)}"

            # Insert Entity
            conn.execute(
                "INSERT INTO Entities (entity_id, name, entity_type, description, is_active) "
                "VALUES (?, ?, 'player', ?, 1);",
                (eid, self.name, self.description)
            )
            
            # 2. Assign default stats if definitions exist
            stat_rows = conn.execute("SELECT name FROM Stat_Definitions;").fetchall()
            for r in stat_rows:
                stat_name = r[0]
                conn.execute(
                    "INSERT INTO Entity_Stats (entity_id, stat_key, stat_value) VALUES (?, ?, ?);",
                    (eid, stat_name, "10") 
                )
            
            conn.commit()
            
        self.signals.status.emit(f"Player {eid} created.")
        return eid
    """Creates a new entity of type 'player' with initial stats."""
    def __init__(self, db_path: str, name: str, description: str = ""):
        super().__init__(db_path)
        self.name = name
        self.description = description

    def execute(self) -> str:
        self.signals.status.emit(f"Creating player entity '{self.name}'...")
        # 1. Generate safe ID
        eid = re.sub(r'[^a-z0-9]', '_', self.name.lower()).strip('_')
        if not eid:
            eid = f"player_{int(datetime.now().timestamp())}"
            
        with get_connection(self.db_path) as conn:
            # Check for collision
            row = conn.execute("SELECT 1 FROM Entities WHERE entity_id = ?;", (eid,)).fetchone()
            if row:
                eid = f"{eid}_{int(datetime.now().timestamp() % 1000)}"

            # Insert Entity
            conn.execute(
                "INSERT INTO Entities (entity_id, name, entity_type, description, is_active) "
                "VALUES (?, ?, 'player', ?, 1);",
                (eid, self.name, self.description)
            )
            
            # 2. Assign default stats if definitions exist
            stat_rows = conn.execute("SELECT name FROM Stat_Definitions;").fetchall()
            for r in stat_rows:
                stat_name = r[0]
                # Default numeric stats to 10, categorical to 'Normal' or similar
                # In a more advanced version, we could use the 'parameters' field from Stat_Definitions
                conn.execute(
                    "INSERT INTO Entity_Stats (entity_id, stat_key, stat_value) VALUES (?, ?, ?);",
                    (eid, stat_name, "10") 
                )
            
            conn.commit()
            
        self.signals.status.emit(f"Player {eid} created.")
        return eid


class LoadInventoryTask(BaseDbTask):
    """Fetch inventory for all active entities."""
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> dict:
        from workers.db_helpers import get_inventory
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT entity_id FROM Entities WHERE is_active = 1;"
            ).fetchall()
        
        inventory_map = {}
        for row in rows:
            eid = row[0]
            inv = get_inventory(self.db_path, self.save_id, eid)
            if inv:
                inventory_map[eid] = inv
        return inventory_map


class LoadTimelineTask(BaseDbTask):
    """Fetch the event timeline."""
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> list[dict]:
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT turn_id, in_game_time, description FROM Timeline WHERE save_id = ? ORDER BY turn_id DESC;",
                (self.save_id,)
            ).fetchall()
            return [dict(r) for r in rows]


class DeleteEntityTask(BaseDbTask):
    """Permanently deletes an entity and its stats."""
    def __init__(self, db_path: str, entity_id: str):
        super().__init__(db_path)
        self.entity_id = entity_id

    def execute(self) -> bool:
        self.signals.status.emit(f"Deleting entity {self.entity_id}...")
        with get_connection(self.db_path) as conn:
            # Foreign keys ON ensures ON DELETE CASCADE for Entity_Stats
            conn.execute("DELETE FROM Entities WHERE entity_id = ?;", (self.entity_id,))
            conn.commit()
        self.signals.status.emit(f"Entity {self.entity_id} deleted.")
        return True

class LoadStatsAndInventoryTask(BaseDbTask):
    """Fetch both stats and inventory for all active entities."""
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> tuple[list[dict], dict]:
        from workers.db_helpers import get_inventory
        from database.modifier_processor import ModifierProcessor
        from database.event_sourcing import EventSourcer
        from database.schema import get_connection

        # 1. Load Stats (with modifiers)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT entity_id, name, entity_type FROM Entities WHERE is_active = 1;"
            ).fetchall()
        
        entities = [dict(r) for r in rows]
        sourcer = EventSourcer(self.db_path)
        processor = ModifierProcessor(self.db_path)
        
        stats_list = []
        inventory_map = {}
        
        for ent in entities:
            eid = ent["entity_id"]
            base_stats = sourcer.get_current_stats(self.save_id, eid)
            effective = processor.apply_modifiers(self.save_id, eid, base_stats)
            
            stats_list.append({
                "entity_id": eid,
                "name": ent["name"],
                "entity_type": ent["entity_type"],
                "stats": effective
            })
            
            # 2. Load Inventory
            inv = get_inventory(self.db_path, self.save_id, eid)
            if inv:
                inventory_map[eid] = inv
        
        return stats_list, inventory_map


class ValidateIntegrityTask(BaseDbTask):
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> tuple[bool, dict[str, Any]]:
        self.signals.status.emit("Validating state integrity...")
        es = EventSourcer(self.db_path)
        return es.validate_integrity(self.save_id)


class LoadFullGameStateTask(BaseDbTask):
    """Fetch stats, inventory, and timeline in one go."""
    def __init__(self, db_path: str, save_id: str):
        super().__init__(db_path)
        self.save_id = save_id

    def execute(self) -> tuple[list[dict], dict, list[dict]]:
        from workers.db_helpers import get_inventory
        from database.modifier_processor import ModifierProcessor
        from database.event_sourcing import EventSourcer
        from database.schema import get_connection

        # 1. Load Entities and Stats
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT entity_id, name, entity_type FROM Entities WHERE is_active = 1;"
            ).fetchall()
        
        entities = [dict(r) for r in rows]
        sourcer = EventSourcer(self.db_path)
        processor = ModifierProcessor(self.db_path)
        
        stats_list = []
        inventory_map = {}
        
        for ent in entities:
            eid = ent["entity_id"]
            base_stats = sourcer.get_current_stats(self.save_id, eid)
            effective = processor.apply_modifiers(self.save_id, eid, base_stats)
            
            stats_list.append({
                "entity_id": eid,
                "name": ent["name"],
                "entity_type": ent["entity_type"],
                "stats": effective
            })
            
            inv = get_inventory(self.db_path, self.save_id, eid)
            if inv:
                inventory_map[eid] = inv
        
        # 2. Load Timeline
        timeline_list = []
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT turn_id, in_game_time, description FROM Timeline WHERE save_id = ? ORDER BY turn_id DESC;",
                (self.save_id,)
            ).fetchall()
            timeline_list = [dict(r) for r in rows]
        
        return stats_list, inventory_map, timeline_list
