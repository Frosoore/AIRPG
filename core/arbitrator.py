"""
core/arbitrator.py

The ArbitratorEngine — AIRPG's deterministic firewall between LLM creativity and
the game's mathematical state.

On every narrative turn the ArbitratorEngine:
  1. Fetches current entity stats from State_Cache + applies modifier overlay.
  2. Retrieves relevant narrative memories from VectorMemory (RAG).
  3. Builds the full narrative prompt (injecting any pending correction).
  4. Calls the LLM and parses its response.
  5. Validates every proposed state change against current stats.
  6. Persists valid changes via EventSourcer; queues corrections for invalids.
  7. Runs the Rules Engine for each mutated entity; persists triggered actions.
  8. Ticks modifier durations.
  9. Embeds the narrative chunk into VectorMemory.
 10. Returns an ArbitratorResult with full detail for the UI / tests.

The Correction Loop (spec §4-B)
---------------------------------
If a change is rejected, a hidden system message is stored in
`_pending_correction`.  On the VERY NEXT turn this message is injected into
the prompt immediately before the user's input, then immediately cleared
so it cannot affect turn N+2.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from core.rules_engine import RulesEngine
from database.event_sourcing import EventSourcer
from database.modifier_processor import ModifierProcessor
from database.schema import get_connection
from llm_engine.base import LLMBackend, LLMMessage, LLMResponse
from llm_engine.prompt_builder import (
    HISTORY_TURN_CAP,
    build_narrative_prompt,
    format_entity_stats_block
)
from llm_engine.vector_memory import VectorMemory
from workers.db_helpers import get_current_time, get_time_of_day_context


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ArbitratorResult:
    """The complete output of one ArbitratorEngine turn.

    Attributes:
        narrative_text:   The prose to display to the player.  Always present.
        applied_changes:  State changes that passed validation and were persisted.
        rejected_changes: State changes that failed validation, each augmented
                          with a "reason" key explaining the failure.
        triggered_rules:  Rule actions fired as a consequence of applied changes.
        rule_chain_warning: True if the rules engine reached its iteration limit,
                            indicating a possible infinite loop in creator rules.
        game_state_tag:   The ambiance tag returned by the LLM (e.g. 'exploration').
        player_entity_id: The ID of the player who sent the message for this turn.
    """
    narrative_text: str
    applied_changes: list[dict[str, Any]] = field(default_factory=list)
    rejected_changes: list[dict[str, Any]] = field(default_factory=list)
    inventory_changes: list[dict[str, Any]] = field(default_factory=list)
    triggered_rules: list[dict[str, Any]] = field(default_factory=list)
    rule_chain_warning: bool = False
    game_state_tag: str = "exploration"
    player_entity_id: str = "player"


# ---------------------------------------------------------------------------
# ArbitratorEngine
# ---------------------------------------------------------------------------

class ArbitratorEngine:
    """Validates and applies LLM-proposed state changes for one narrative turn.

    Args:
        db_path:            Path to the universe .db for direct entity queries.
        rules_list:         List of creator-defined rules.
    """

    def __init__(
        self,
        db_path: str,
        rules_list: list[dict],
    ) -> None:
        self._db_path = db_path
        self._rules_engine = RulesEngine(rules_list)
        self._event_sourcer = EventSourcer(db_path)
        self._modifier_processor = ModifierProcessor(db_path)
        
        # Dependencies to be injected via configure()
        self._llm: LLMBackend | None = None
        self._vector_memory: VectorMemory | None = None
        self._pending_correction: str | None = None

    def configure(self, llm: LLMBackend, vector_memory: VectorMemory) -> None:
        """Inject runtime dependencies before process_turn."""
        self._llm = llm
        self._vector_memory = vector_memory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_turn(
        self,
        save_id: str,
        turn_id: int,
        user_message: str,
        universe_system_prompt: str,
        history: list[LLMMessage],
        player_entity_id: str = "player",
        stream_token_callback: Callable[[str], None] | None = None,
        temperature: float = 0.7,
        top_p: float = 1.0,
        verbosity_level: str = "balanced",
    ) -> ArbitratorResult:
        """Execute one full ArbitratorEngine turn and return the result.

        Args:
            save_id:                 The active save identifier.
            turn_id:                 The current turn number (monotonically increasing).
            user_message:            The player's raw input.
            universe_system_prompt:  The universe's foundational system prompt.
            history:                 Prior conversation turns for context.
            player_entity_id:        The ID of the player sending the message.
            stream_token_callback:   Optional callable invoked with each streaming
                                     token as it arrives from the LLM.
            temperature:             Sampling temperature (0.0 to 1.0).
            top_p:                   Nucleus sampling parameter (0.0 to 1.0).
            verbosity_level:         'short', 'balanced', or 'talkative'.

        Returns:
            ArbitratorResult containing narrative text and all change outcomes.

        Raises:
            LLMConnectionError: If the LLM backend is unreachable.
        """
        # Step 0 — Log user message event
        self._event_sourcer.append_event(
            save_id, turn_id, "user_input", player_entity_id,
            {"text": user_message}
        )

        # Step 1 — Fetch and overlay stats for all active entities
        all_stats = self._fetch_effective_stats(save_id)

        # Step 2 — RAG retrieval (Narrative Memories + Lore Book)
        # We query for both prior narrative chunks and structured lore
        # Point 2: Pass current_turn_id for Time-Weighted search
        # Mission: Exclude turns that are already in the conversation history (HISTORY_TURN_CAP)
        from core.config import load_config
        cfg = load_config()
        
        # Calculate the oldest turn ID still in the history window
        max_turn_id = max(0, turn_id - HISTORY_TURN_CAP)
        
        rag_results = self._vector_memory.query(
            save_id, 
            user_message, 
            k=cfg.rag_chunk_count, 
            current_turn_id=turn_id,
            max_turn_id=max_turn_id
        )
        rag_chunks = [r["text"] for r in rag_results if r.get("metadata", {}).get("type") != "lore"]
        
        # Step 3 — Relevant Context Filtering (Context Optimization)
        # Only send stats for entities that are "active" in the current context
        # to save tokens and reduce LLM confusion.
        relevant_entity_ids = self._identify_relevant_entities(
            save_id, user_message, history, rag_chunks, all_stats
        )
        print(f"[ARBITRATOR] Identified {len(relevant_entity_ids)} relevant entities: {sorted(list(relevant_entity_ids))}")
        # Always include the player
        relevant_entity_ids.add("player") 
        
        filtered_stats = {
            eid: stats for eid, stats in all_stats.items() 
            if eid in relevant_entity_ids
        }

        # Step 4 — Build prompt (with pending correction)
        entity_block = format_entity_stats_block(
            [
                {"entity_id": eid, "name": eid, "entity_type": "unknown", "stats": stats}
                for eid, stats in filtered_stats.items()
            ]
        )
        
        # Fetch actual Lore Book entries if available (subset matching the query)
        lore_book_subset = self._fetch_relevant_lore(save_id, user_message)

        # Get current time context
        total_mins = get_current_time(self._db_path, save_id)
        time_ctx = get_time_of_day_context(total_mins)

        # Phase 12.1: Fetch triggered scheduled events
        triggered_events = self._fetch_triggered_events(save_id, total_mins)

        messages = build_narrative_prompt(
            universe_system_prompt=universe_system_prompt,
            entity_stats_block=entity_block,
            rag_chunks=rag_chunks,
            history=history,
            user_message=user_message,
            pending_correction=self._pending_correction,
            lore_book=lore_book_subset,
            verbosity_level=verbosity_level,
            player_id=player_entity_id,
            current_time_str=time_ctx,
            scheduled_events=triggered_events,
        )

        # Step 4 — Clear pending correction immediately after prompt is built
        self._pending_correction = None

        # Step 5 — Call LLM (streaming or non-streaming based on callback)
        # Phase 11: Dynamic stop sequences to prevent impersonation
        stops = ["\nUser:", "\nPlayer:", "\n[User]", "<|eot_id|>", f"\n{player_entity_id}:", f"\n[{player_entity_id}]"]
        
        # Mapping verbosity to max_tokens to prevent runaway generation
        verbosity_to_tokens = {
            "short": 150,
            "balanced": 400,
            "talkative": 1024
        }
        max_tokens = verbosity_to_tokens.get(verbosity_level.lower(), 400)
        
        llm_response = self._call_llm(
            messages, 
            stream_token_callback, 
            temperature, 
            top_p, 
            stop_sequences=stops,
            max_tokens=max_tokens
        )
        narrative_text: str = llm_response.narrative_text

        # Step 6 — Parse tool call
        state_changes: list[dict[str, Any]] = []
        inventory_changes: list[dict[str, Any]] = []
        game_state_tag: str = "exploration"
        if llm_response.tool_call:
            state_changes = llm_response.tool_call.get("state_changes", [])
            inventory_changes = llm_response.tool_call.get("inventory_changes", [])
            game_state_tag = str(llm_response.tool_call.get("game_state_tag", "exploration")).strip().lower()

        # Step 7 — Validate and apply each state change
        applied_changes: list[dict[str, Any]] = []
        rejected_changes: list[dict[str, Any]] = []
        rejection_messages: list[str] = []

        for change in state_changes:
            entity_id: str = change.get("entity_id", "")
            stat_key: str = change.get("stat_key", "")
            delta: float | None = change.get("delta")
            value: Any = change.get("value")

            valid, reason = self._validate_change(
                entity_id, stat_key, delta, value, all_stats
            )

            if valid:
                payload: dict[str, Any] = {"entity_id": entity_id, "stat_key": stat_key}
                if delta is not None:
                    payload["delta"] = delta
                    event_type = "stat_change"
                else:
                    payload["value"] = value
                    event_type = "stat_set"

                self._event_sourcer.append_event(
                    save_id, turn_id, event_type, entity_id, payload
                )
                # Update local snapshot for downstream Rules evaluation
                self._apply_local_change(entity_id, payload, all_stats)

                applied_changes.append(change)
            else:
                rejected = dict(change)
                rejected["reason"] = reason
                rejected_changes.append(rejected)
                rejection_messages.append(
                    f"{entity_id}.{stat_key}: {reason}"
                )

        # Queue a combined correction if any changes were rejected
        if rejection_messages:
            self._queue_correction("; ".join(rejection_messages))

        # Step 7.5 — Process Inventory Changes
        applied_inventory: list[dict[str, Any]] = []
        for inv_change in inventory_changes:
            # { "entity_id": str, "item_id": str, "action": "add"|"remove", "quantity": int }
            valid, reason = self._validate_inventory_change(save_id, inv_change)
            if valid:
                self._apply_inventory_change(save_id, turn_id, inv_change)
                applied_inventory.append(inv_change)
            else:
                self._queue_correction(f"Inventory: {reason}")

        # Step 8 — Run Rules Engine (Persistent & Chained)
        # Point 4: Rule actions now generate persistent events and update stats
        triggered_rules: list[dict[str, Any]] = []
        mutated_entities = {c.get("entity_id") for c in applied_changes if c.get("entity_id")}
        rule_chain_warning = False

        # We keep evaluating while new rules trigger (chaining)
        # Max 5 iterations to prevent infinite loops from poorly defined rules
        for i in range(5):
            new_mutations = set()
            for entity_id in list(mutated_entities):
                stats = all_stats.get(entity_id, {})
                triggered_actions = self._rules_engine.evaluate(entity_id, stats)
                
                for action in triggered_actions:
                    # Check if this rule already triggered for this entity this turn
                    # to prevent trivial infinite loops
                    action_id = f"{entity_id}_{action.get('type')}_{action.get('stat')}_{action.get('value')}"
                    if any(f"{entity_id}_{a.get('type')}_{a.get('stat')}_{a.get('value')}" == action_id for a in triggered_rules):
                         continue

                    # 1. Map rule action to a persistent event
                    payload: dict[str, Any] = {
                        "entity_id": entity_id,
                        "stat_key": action.get("stat"),
                        "source_rule": action.get("rule_id")
                    }
                    
                    event_type = "stat_set"
                    if action["type"] == "stat_change":
                        payload["delta"] = action.get("value")
                        event_type = "stat_change"
                    else:
                        payload["value"] = action.get("value")

                    self._event_sourcer.append_event(
                        save_id, turn_id, event_type, entity_id, payload
                    )
                    
                    # 1b. Also record the trigger itself for tracking/history
                    self._event_sourcer.append_event(
                        save_id, turn_id, "rule_trigger", entity_id, action
                    )
                    
                    # 2. Update local stats for chaining/consistency
                    self._apply_local_change(entity_id, payload, all_stats)
                    
                    triggered_rules.append(action)
                    new_mutations.add(entity_id)
            
            if not new_mutations:
                break
            
            if i == 4: # Reached limit
                rule_chain_warning = True
                self._event_sourcer.append_event(
                    save_id, turn_id, "rule_engine_warning", "system",
                    {"message": "Maximum rule chaining depth (5) reached. Possible infinite loop detected."}
                )
            
            mutated_entities = new_mutations

        # Step 9 — Tick modifiers
        self._modifier_processor.tick_modifiers(save_id)

        # Step 10 — Embed narrative chunk
        if narrative_text.strip():
            self._vector_memory.embed_chunk(save_id, turn_id, narrative_text)

        # Step 11 — Log narrative event (Multiverse-compatible)
        text_to_log = user_message if not narrative_text.strip() else narrative_text
        self._event_sourcer.append_event(
            save_id, turn_id, "narrative_text", "player",
            {"active": 0, "variants": [text_to_log]}
        )

        # Phase 12.1: Mark scheduled events as fired
        for ev in triggered_events:
            self._mark_event_as_fired(save_id, ev["event_id"])

        return ArbitratorResult(
            narrative_text=narrative_text,
            applied_changes=applied_changes,
            rejected_changes=rejected_changes,
            inventory_changes=applied_inventory,
            triggered_rules=triggered_rules,
            rule_chain_warning=rule_chain_warning,
            game_state_tag=game_state_tag,
            player_entity_id=player_entity_id,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        messages: list[LLMMessage],
        stream_token_callback: Callable[[str], None] | None,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop_sequences: list[str] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Call the LLM, optionally streaming tokens via a callback.

        When stream_token_callback is None: uses llm.complete() — identical
        to Phase 2 behaviour, all existing tests pass unchanged.

        When stream_token_callback is provided: uses llm.stream_tokens() to
        yield tokens one by one.  Each token is passed to the callback
        (e.g. NarrativeWorker.token_received.emit) for real-time UI updates.
        Tokens are accumulated and assembled into a full string, then
        parse_tool_call() is applied to extract narrative and tool_call JSON.

        Args:
            messages:              The fully built prompt message list.
            stream_token_callback: Optional token handler; None = non-streaming.
            temperature:           Sampling temperature (0.0 to 1.0).
            top_p:                 Nucleus sampling parameter (0.0 to 1.0).
            stop_sequences:        Custom strings to trigger generation stop.
            max_tokens:            Optional limit on the number of tokens to generate.

        Returns:
            LLMResponse with narrative_text, optional tool_call, finish_reason.

        Raises:
            LLMConnectionError: If the LLM is unreachable during streaming.
        """
        if stream_token_callback is None:
            return self._llm.complete(
                messages, 
                temperature=temperature, 
                top_p=top_p, 
                stop_sequences=stop_sequences,
                max_tokens=max_tokens
            )

        # Streaming path
        raw_tokens: list[str] = []
        for token in self._llm.stream_tokens(
            messages, 
            temperature=temperature, 
            top_p=top_p, 
            stop_sequences=stop_sequences,
            max_tokens=max_tokens
        ):
            stream_token_callback(token)
            raw_tokens.append(token)

        full_raw = "".join(raw_tokens)
        narrative, tool_call = self._llm.parse_tool_call(full_raw)
        return LLMResponse(
            narrative_text=narrative,
            tool_call=tool_call,
            finish_reason="stop",
        )

    def _fetch_effective_stats(self, save_id: str) -> dict[str, dict[str, str]]:
        """Fetch all active entity stats and apply modifier overlays.

        Queries State_Cache for all entity IDs belonging to this save, then
        calls ModifierProcessor to produce effective (modifier-adjusted) stats.

        Args:
            save_id: The active save identifier.

        Returns:
            Dict mapping entity_id -> effective stats dict.
        """
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT entity_id FROM State_Cache WHERE save_id = ?;",
                (save_id,),
            ).fetchall()
        entity_ids = [row[0] for row in rows]

        effective: dict[str, dict[str, str]] = {}
        for entity_id in entity_ids:
            base = self._event_sourcer.get_current_stats(save_id, entity_id)
            effective[entity_id] = self._modifier_processor.apply_modifiers(
                save_id, entity_id, base
            )
        return effective

    def _identify_relevant_entities(
        self,
        save_id: str,
        user_message: str,
        history: list[LLMMessage],
        rag_chunks: list[str],
        all_stats: dict[str, dict[str, str]],
    ) -> set[str]:
        """Identify relevant entities based on mentions, type, and location.

        Always includes:
        - Entities explicitly mentioned in the recent context.
        - Entities of type 'world' or 'faction' (global context).
        - NPCs that share the same 'Location' stat as the player.
        """
        import re

        # 1. Mentions-based detection
        text_to_scan = user_message.lower()
        for msg in history[-3:]:
            text_to_scan += " " + msg["content"].lower()
        for chunk in rag_chunks:
            text_to_scan += " " + chunk.lower()

        words_in_text = set(re.findall(r"\b\w+\b", text_to_scan))

        with get_connection(self._db_path) as conn:
            rows = conn.execute("SELECT entity_id, entity_type FROM Entities;").fetchall()
            # Map lowercase ID -> Original ID
            original_case_map = {row[0].lower(): row[0] for row in rows}
            id_to_type = {row[0]: row[1] for row in rows}
            all_ids_lower = set(original_case_map.keys())

        matched_ids = {original_case_map[ml] for ml in words_in_text.intersection(all_ids_lower)}

        # 2. Location-based and Type-based inclusion
        relevant = set(matched_ids)
        
        # Get player's location
        player_stats = all_stats.get("player", {})
        player_loc = player_stats.get("Location", "").lower()

        npc_count_at_loc = 0
        for eid, etype in id_to_type.items():
            # Include all global entities
            if etype in ("world", "faction"):
                relevant.add(eid)
                continue
            
            # Include NPCs at the same location (Limit to 3 to prevent bloat)
            if etype == "npc" and player_loc:
                entity_loc = all_stats.get(eid, {}).get("Location", "").lower()
                if entity_loc == player_loc:
                    if npc_count_at_loc < 3:
                        relevant.add(eid)
                        npc_count_at_loc += 1

        return relevant

    def _fetch_triggered_events(self, save_id: str, current_minute: int) -> list[dict]:
        """Fetch global scheduled events that have triggered but not yet fired for this save."""
        events = []
        try:
            with get_connection(self._db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT e.event_id, e.title, e.description 
                    FROM Scheduled_Events e
                    LEFT JOIN Fired_Scheduled_Events f ON e.event_id = f.event_id AND f.save_id = ?
                    WHERE e.trigger_minute <= ? AND f.event_id IS NULL;
                    """,
                    (save_id, current_minute)
                ).fetchall()
                events = [dict(r) for r in rows]
        except Exception as e:
            print(f"[ARBITRATOR] Error fetching scheduled events: {e}")
        return events

    def _mark_event_as_fired(self, save_id: str, event_id: str) -> None:
        """Record that a scheduled event has occurred for this save."""
        try:
            with get_connection(self._db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO Fired_Scheduled_Events (save_id, event_id) VALUES (?, ?);",
                    (save_id, event_id)
                )
                conn.commit()
        except Exception as e:
            print(f"[ARBITRATOR] Error marking event as fired: {e}")

    def _fetch_relevant_lore(self, save_id: str, user_message: str) -> list[dict]:
        """Fetch Lore Book entries relevant to the current turn.

        Uses RAG to find the most relevant entries from the Lore_Book table.
        """
        # We query VectorMemory but specifically look for 'lore' type metadata
        # (Assuming vector_memory.py supports this or we can filter results)
        results = self._vector_memory.query(save_id, user_message, k=5)
        
        relevant_lore: list[dict] = []
        for r in results:
            if r.get("metadata", {}).get("type") == "lore":
                relevant_lore.append({
                    "category": r["metadata"].get("category", ""),
                    "name": r["metadata"].get("name", ""),
                    "content": r["text"]
                })
        return relevant_lore

    def _validate_change(
        self,
        entity_id: str,
        stat_key: str,
        delta: float | None,
        value: Any,
        all_effective_stats: dict[str, dict[str, str]],
    ) -> tuple[bool, str]:
        """Validate a single proposed state change.

        Rules:
        - Unknown entity_id → rejected (if the entity set is non-empty).
        - Stat key not in Stat_Definitions → rejected (except special 'Description').
        - Delta change on a non-negative resource that would go below 0 → rejected.
        - Absolute assignment on a non-negative resource that would go below 0 → rejected.

        Args:
            entity_id:           The entity to modify.
            stat_key:            The stat to change.
            delta:               Signed numeric change, or None if using value.
            value:               Absolute assignment value, or None if using delta.
            all_effective_stats: Full map of entity_id -> stats for all active
                                 entities in this save.

        Returns:
            (True, "") if valid, or (False, reason_string) if invalid.
        """
        if not entity_id:
            return False, "Missing entity_id in state change."

        if all_effective_stats and entity_id not in all_effective_stats:
            # Non-empty entity set means we know all valid entities
            return False, f"Unknown entity: {entity_id}"

        # Stat Restriction Rule: Only allow stats defined in Stat_Definitions (case-insensitive)
        # Plus the special 'Description' stat which is allowed for all entities.
        if stat_key.lower() != "description":
            with get_connection(self._db_path) as conn:
                row = conn.execute(
                    "SELECT 1 FROM Stat_Definitions WHERE LOWER(name) = ?;",
                    (stat_key.lower(),)
                ).fetchone()
                if not row:
                    return False, f"Stat '{stat_key}' is not defined in this universe. Custom stats are forbidden."

        # Resource sufficiency rules (prevent stats like HP, Gold, etc. from going below zero)
        entity_stats = all_effective_stats.get(entity_id, {})
        current_raw = entity_stats.get(stat_key, "0")

        try:
            current_val = float(current_raw)
        except ValueError:
            current_val = None  # Non-numeric stat

        # Calculate proposed new value
        if delta is not None:
            if current_val is None:
                return False, f"Cannot apply numeric delta to non-numeric stat {entity_id}.{stat_key}."
            result_val = current_val + float(delta)
        elif value is not None:
            try:
                result_val = float(value)
            except (ValueError, TypeError):
                result_val = None  # Assigning a non-numeric string is always valid for the cache
        else:
            return False, f"State change for {entity_id}.{stat_key} has neither delta nor value."

        # Enforce non-negativity if it's a numeric resource
        if current_val is not None and result_val is not None:
            if current_val >= 0 and result_val < 0:
                return False, (
                    f"the player does not have enough {stat_key} (current: {current_val:.0f})"
                )

        return True, ""

    def _queue_correction(self, reason: str) -> None:
        """Format and store a correction message for the next turn's prompt.

        If a correction is already queued (from multiple rejections), the new
        reason is concatenated.

        Args:
            reason: Human-readable description of what failed.
        """
        correction = (
            f"[NARRATOR HINT: The previous action failed because {reason}. "
            "Describe this failure naturally in the story. Do not mention this hint.]"
        )
        if self._pending_correction is None:
            self._pending_correction = correction
        else:
            self._pending_correction += f" {correction}"

    def _apply_local_change(self, entity_id: str, payload: dict, all_stats: dict) -> None:
        """Update a local stats snapshot with a proposed change.
        
        Ensures that within a single turn, subsequent validations or rules
        see the effects of previous changes.
        """
        if entity_id not in all_stats:
            all_stats[entity_id] = {}
            
        stat_key = payload["stat_key"]
        if "delta" in payload:
            current_raw = all_stats[entity_id].get(stat_key, "0")
            try:
                current = float(current_raw)
            except ValueError:
                current = 0.0
            new_val = current + float(payload["delta"])
            all_stats[entity_id][stat_key] = (
                str(int(new_val)) if new_val == int(new_val) else str(new_val)
            )
        else:
            all_stats[entity_id][stat_key] = str(payload["value"])

    def _validate_inventory_change(self, save_id: str, change: dict) -> tuple[bool, str]:
        """Verify if an inventory transaction is legal."""
        entity_id = change.get("entity_id")
        item_id = change.get("item_id")
        action = change.get("action")
        quantity = int(change.get("quantity", 1))

        if not entity_id or not item_id or action not in ("add", "remove"):
            return False, "Malformed inventory change (missing entity_id, item_id, or invalid action)."

        with get_connection(self._db_path) as conn:
            # 1. Check if item exists in definitions
            item_exists = conn.execute(
                "SELECT 1 FROM Item_Definitions WHERE item_id = ?;", (item_id,)
            ).fetchone()
            if not item_exists:
                return False, f"Unknown item: {item_id}"

            # 2. Check if entity exists in this save
            entity_exists = conn.execute(
                "SELECT 1 FROM Entities WHERE entity_id = ?;", (entity_id,)
            ).fetchone()
            if not entity_exists:
                return False, f"Unknown entity: {entity_id}"

            if action == "remove":
                # 3. Check if entity has enough quantity
                row = conn.execute(
                    "SELECT quantity FROM Items_Inventory WHERE save_id = ? AND entity_id = ? AND item_id = ?;",
                    (save_id, entity_id, item_id)
                ).fetchone()
                current_qty = row["quantity"] if row else 0
                if current_qty < quantity:
                    return False, f"Insufficient quantity for {item_id} (has {current_qty}, needs {quantity})."

        return True, ""

    def _apply_inventory_change(self, save_id: str, turn_id: int, change: dict) -> None:
        """Persist an inventory transaction and log the event."""
        entity_id = change["entity_id"]
        item_id = change["item_id"]
        action = change["action"]
        quantity = int(change.get("quantity", 1))

        with get_connection(self._db_path) as conn:
            if action == "add":
                conn.execute(
                    """
                    INSERT INTO Items_Inventory (save_id, entity_id, item_id, quantity)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(save_id, entity_id, item_id) DO UPDATE SET
                    quantity = quantity + excluded.quantity;
                    """,
                    (save_id, entity_id, item_id, quantity)
                )
            elif action == "remove":
                conn.execute(
                    """
                    UPDATE Items_Inventory SET quantity = quantity - ?
                    WHERE save_id = ? AND entity_id = ? AND item_id = ?;
                    """,
                    (quantity, save_id, entity_id, item_id)
                )
                # Cleanup zero-quantity items
                conn.execute(
                    "DELETE FROM Items_Inventory WHERE quantity <= 0;"
                )
            conn.commit()

        # Log to event source for perfect rewindability
        self._event_sourcer.append_event(
            save_id, turn_id, f"inventory_{action}", entity_id, change
        )
