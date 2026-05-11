import json
from PySide6.QtCore import QThread, Signal
from llm_engine.base import LLMBackend
from llm_engine.prompt_builder import build_narrative_prompt
from database.schema import get_connection

class RegenerateWorker(QThread):
    token_received = Signal(str)
    regenerate_complete = Signal(str)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(self, llm: LLMBackend, db_path: str, save_id: str, turn_id: int, history: list, system_prompt: str, user_message: str, temperature: float = 0.7, top_p: float = 1.0, verbosity_level: str = "balanced"):
        super().__init__()
        self._llm = llm
        self._db_path = db_path
        self._save_id = save_id
        self._turn_id = turn_id
        self._history = history
        self._system_prompt = system_prompt
        self._user_message = user_message
        self._temperature = temperature
        self._top_p = top_p
        self._verbosity_level = verbosity_level

    def run(self):
        try:
            self.status_update.emit("Generating new variant...")
            
            # Map history format (Event-sourced -> LLMMessage format)
            llm_history = []
            player_id = "player_1"
            
            for h in self._history:
                if h.get("event_type") == "user_input":
                    payload = h.get("payload", "")
                    text = payload.get("text", str(payload)) if isinstance(payload, dict) else str(payload)
                    llm_history.append({"role": "user", "content": text})
                elif h.get("event_type") == "narrative_text":
                    payload = h.get("payload", "")
                    if isinstance(payload, dict) and "variants" in payload:
                        text = payload["variants"][payload["active"]]
                    else:
                        text = str(payload)
                    llm_history.append({"role": "assistant", "content": text})

            prompt = build_narrative_prompt(
                universe_system_prompt=self._system_prompt,
                entity_stats_block="", # We don't need stats because we won't evaluate rules
                rag_chunks=[],
                history=llm_history,
                user_message=self._user_message,
                verbosity_level=self._verbosity_level,
                player_id=player_id
            )
            
            # Remove tool instruction from system prompt to prevent tool calls
            for msg in prompt:
                if msg["role"] == "system":
                    msg["content"] = msg["content"].replace("You MUST end your response with a JSON block", "You are generating a new variant. Do NOT output any JSON tool calls.")

            # Phase 11: Dynamic stop sequences
            stops = ["\nUser:", "\nPlayer:", "\n[User]", "<|eot_id|>", f"\n{player_id}:", f"\n[{player_id}]"]
            
            verbosity_to_tokens = {
                "short": 150,
                "balanced": 400,
                "talkative": 1024
            }
            max_tokens = verbosity_to_tokens.get(self._verbosity_level.lower(), 400)

            narrative_text = ""
            for token in self._llm.stream_tokens(
                prompt, 
                temperature=self._temperature, 
                top_p=self._top_p, 
                stop_sequences=stops,
                max_tokens=max_tokens
            ):
                narrative_text += token
                self.token_received.emit(token)

            # Append variant to DB
            with get_connection(self._db_path) as conn:
                row = conn.execute(
                    "SELECT payload FROM Event_Log WHERE save_id = ? AND turn_id = ? AND event_type = 'narrative_text';",
                    (self._save_id, self._turn_id)
                ).fetchone()
                
                if row:
                    payload_data = json.loads(row[0])
                    if not isinstance(payload_data, dict) or "variants" not in payload_data:
                        text = payload_data.get("text", "") if isinstance(payload_data, dict) else str(payload_data)
                        payload_data = {"active": 0, "variants": [text]}
                    
                    payload_data["variants"].append(narrative_text.strip())
                    payload_data["active"] = len(payload_data["variants"]) - 1
                    
                    conn.execute(
                        "UPDATE Event_Log SET payload = ? WHERE save_id = ? AND turn_id = ? AND event_type = 'narrative_text';",
                        (json.dumps(payload_data), self._save_id, self._turn_id)
                    )
                    conn.commit()

            self.regenerate_complete.emit(narrative_text)
        except Exception as exc:
            self.error_occurred.emit(str(exc))
