"""
workers/timekeeper_worker.py

QThread worker for the Timekeeper agent.
Analyzes narrative text to estimate elapsed in-game time and record major events
in the Timeline table.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from database.schema import get_connection
from llm_engine.prompt_builder import build_timekeeper_prompt

if TYPE_CHECKING:
    from llm_engine.base import LLMBackend


class TimekeeperWorker(QThread):
    """Worker that uses an LLM to parse time passage from narrative prose.

    Signals:
        finished(int): Emitted with the new cumulative total in-game minutes.
        error(str):    Emitted if LLM inference or database write fails.
    """

    finished = Signal(int)
    error = Signal(str)

    def __init__(
        self,
        llm_backend: LLMBackend,
        db_path: str,
        save_id: str,
        turn_id: int,
        narrative_text: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.llm_backend = llm_backend
        self.db_path = db_path
        self.save_id = save_id
        self.turn_id = turn_id
        self.narrative_text = narrative_text

    def run(self) -> None:
        try:
            # 1. Get current cumulative time for this save
            current_time = 0
            with get_connection(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT MAX(in_game_time) FROM Timeline WHERE save_id = ?",
                    (self.save_id,),
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    current_time = int(row[0])

            # 2. Build prompt and call LLM
            prompt = build_timekeeper_prompt(self.narrative_text)
            # We force a very low temperature for deterministic JSON output
            response = self.llm_backend.complete(
                prompt, max_tokens=150, temperature=0.1
            )
            
            # 3. Parse JSON response
            # Try to use the pre-parsed tool_call if available
            data = getattr(response, "tool_call", {}) or {}

            # Fallback: manually extract from narrative_text if tool_call is empty
            if not data:
                text = getattr(response, "narrative_text", str(response))
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        print(f"[DEBUG] Timekeeper LLM fallback parsing failed: {text}")
                
            # Final fallback if still empty or invalid
            if not data:
                data = {"elapsed_minutes": 1, "major_event_description": None}

            elapsed = int(data.get("elapsed_minutes", 1))
            major_event = data.get("major_event_description")
            
            new_time = current_time + elapsed

            # 4. Insert into Timeline
            # We insert if time passed OR if a major event was identified
            if elapsed > 0 or major_event:
                description = major_event if major_event else "Time advances"
                with get_connection(self.db_path) as conn:
                    conn.execute(
                        "INSERT INTO Timeline (save_id, turn_id, in_game_time, description) "
                        "VALUES (?, ?, ?, ?)",
                        (self.save_id, self.turn_id, new_time, description),
                    )
                    conn.commit()

            self.finished.emit(new_time)

        except sqlite3.Error as e:
            self.error.emit(f"Database error in Timekeeper: {e}")
        except Exception as e:
            self.error.emit(f"Timekeeper error: {e}")
