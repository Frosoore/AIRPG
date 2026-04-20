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

    def execute(self) -> tuple[list[dict], int]:
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT turn_id, event_type, payload FROM Event_Log "
                "WHERE save_id = ? AND event_type IN ('user_input', 'narrative_text') "
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
        return history, max_turn_id


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
        vector_dir = Path.home() / "AIRPG" / "vector" / self.save_id
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


class PopulateEntitiesTask(BaseDbTask):
    """Asynchronous entity generation using local Ollama.
    
    Reads world context, chunks large Lore_Book text, and inserts new
    entities into the database idempotently.
    """
    def __init__(self, db_path: str):
        super().__init__(db_path)

    def execute(self) -> int:
        from core.config import load_config, build_llm_from_config
        from llm_engine.prompt_builder import build_populate_prompt
        
        self.signals.status.emit("Initializing AI backend...")
        cfg = load_config()
        # Use specialized model for extraction, respecting user backend (Universal/Kobold/Gemini)
        try:
            llm = build_llm_from_config(cfg, model_override=cfg.extraction_model)
        except Exception as e:
            print(f"[POPULATE] Failed to build LLM backend: {e}")
            return 0
        
        # 1. Gather context
        self.signals.status.emit("Reading world context...")
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
        
        # Always include Global Lore as a distinct chunk if it exists
        global_lore = meta.get("global_lore", "").strip()
        if global_lore:
            chunks.append(f"=== GLOBAL WORLD LORE ===\n{global_lore}")

        # Each lore entry becomes its own individual chunk
        for name, content, cat in lore_rows:
            cat = cat or "General"
            chunks.append(f"=== CATEGORY: {cat} ===\n### Name: {name}\n{content}")

        if not chunks:
            chunks = ["(No lore found)"]

        # 3. Process each chunk
        new_entities_found = []
        
        for i, chunk in enumerate(chunks):
            self.signals.status.emit(f"Processing lore chunk {i+1}/{len(chunks)}...")
            
            prompt = build_populate_prompt(chunk, existing_names, stat_defs)
            
            try:
                # Force JSON format at the API level
                resp = llm.complete(prompt, response_format="json")
                print(f"[POPULATE DEBUG] Raw Text: {resp.narrative_text} | Tool Call: {resp.tool_call}")
                
                # Resilient JSON parsing: handle both {"entities": [...]} and [...] directly
                batch = []
                if isinstance(resp.tool_call, list):
                    batch = resp.tool_call
                elif isinstance(resp.tool_call, dict):
                    if "entities" in resp.tool_call:
                        batch = resp.tool_call["entities"]
                    else:
                        batch = [resp.tool_call]
                
                if isinstance(batch, list):
                    # Filter stats to ensure only defined ones are kept
                    allowed_stats = {s["name"].lower() for s in stat_defs}
                    for ent in batch:
                        if "stats" in ent and isinstance(ent["stats"], dict):
                            # Case-insensitive filtering while preserving original key casing if it matches
                            valid_stats = {}
                            stat_name_map = {s["name"].lower(): s["name"] for s in stat_defs}
                            
                            for k, v in ent["stats"].items():
                                if k.lower() in allowed_stats:
                                    valid_stats[stat_name_map[k.lower()]] = v
                                else:
                                    print(f"[POPULATE] Filtering out invented stat: {k} for entity {ent.get('name')}")
                            ent["stats"] = valid_stats
                            
                    new_entities_found.extend(batch)
            except Exception as e:
                print(f"[POPULATE] LLM error on chunk {i}: {e}")
                continue

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
                
                if not name:
                    continue
                
                # Python-side ID generation for robustness
                eid = re.sub(r'[^a-z0-9]', '_', name.lower())
                eid = re.sub(r'_+', '_', eid).strip('_')
                
                if not eid:
                    continue
                
                if etype not in ("npc", "faction"):
                    etype = "npc"
                
                if eid in existing_ids:
                    continue
                
                # Insert core record
                conn.execute(
                    "INSERT INTO Entities (entity_id, name, entity_type, description, is_active) VALUES (?, ?, ?, ?, 1);",
                    (eid, name, etype, description)
                )
                existing_ids.add(eid)
                existing_names.append(name)
                
                # Store dynamic stats provided by LLM if they are valid
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

        self.signals.status.emit(f"Populate complete: {inserted_count} entities added.")
        return inserted_count


class CreatePlayerEntityTask(BaseDbTask):
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
