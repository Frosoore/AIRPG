"""
llm_engine/prompt_builder.py

Pure prompt-assembly functions for AIRPG's LLM agents.

All functions in this module are stateless and side-effect-free.  They
take structured data and return list[LLMMessage] ready for any LLMBackend.

Three prompt families are provided:

  build_narrative_prompt  — Main gameplay turn (Arbitrator)
  build_chronicler_prompt — Off-screen world simulation (Chronicler)
  build_mini_dico_prompt  — Encyclopedic lore lookup (Mini-Dico)

Tool-Call Protocol Reminder
-----------------------------
The narrative prompt instructs the LLM to embed its state-change JSON inside
a  ~~~json … ~~~  fenced block (see llm_engine/base.py).
"""

import json
import re

from llm_engine.base import LLMMessage

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

HISTORY_TURN_CAP: int = 10
"""Maximum number of prior conversation turns injected into the narrative prompt.
Older turns are silently dropped to keep context windows manageable.
A "turn" is one user message + one assistant message, so at most
2 * HISTORY_TURN_CAP individual messages are included from history."""


def _strip_media_tags(text: str) -> str:
    """Remove Markdown and HTML image tags to keep the prompt text-only.
    
    Strips ![]() and <img /> patterns.
    """
    # Remove Markdown images: ![alt](url)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove HTML images: <img ... />
    text = re.sub(r"<img.*?>", "", text, flags=re.IGNORECASE)
    return text.strip()

NARRATIVE_TOOL_CALL_SCHEMA: str = """\
At the end of your response, append exactly one fenced JSON block using ~~~json.
Allowed game_state_tag values: 'exploration', 'combat', 'dialogue', 'tension'.

CRITICAL RULES:
1. FACTIONS: Adjust dialogue based on entity 'Reputation' or 'Alliance'.
2. INVENTORY: Manage items via "inventory_changes" using "action": "add"|"remove".
3. NO REPETITION: Do not repeat player actions in the narrative.

~~~json
{
  "state_changes": [{"entity_id": "...", "stat_key": "...", "delta": 0, "value": "..."}],
  "inventory_changes": [{"entity_id": "...", "item_id": "...", "action": "add", "quantity": 1}],
  "narrative_events": ["event_id"],
  "game_state_tag": "exploration"
}
~~~
\
"""

MINI_DICO_SYSTEM_PROMPT: str = """\
You are an encyclopedic lore reference for a fictional universe.
Your role is strictly informational.

RULES you must NEVER break:
- Do NOT roleplay, act as a character, or speak in first person as an NPC.
- Do NOT advance the plot, hint at future events, or make narrative suggestions.
- Do NOT reference the current situation, the player's choices, or recent events.
- ONLY state facts that are explicitly established in the lore excerpts provided.
- If the answer is not in the provided lore, say so plainly.
- Answers must be cold, concise, and encyclopedic — no dramatic flair.\
"""

CHRONICLER_SYSTEM_PROMPT_BASE: str = """\
You are the Chronicler — a macro-simulation engine for a living fictional world.
Your task is to simulate the independent actions of off-screen entities
(factions, VIP NPCs, cities, world forces) while the player is absent.

OUTPUT FORMAT:
Respond ONLY with a ~~~json … ~~~ fenced block containing state changes and world news.
Do NOT write any narrative prose. Do NOT explain your decisions.

~~~json
{
  "state_changes": [
    {
      "entity_id": "<string>",
      "stat_key":  "<string>",
      "delta":     <number>,
      "value":     "<string or number>"
    }
  ],
  "world_news": [
    "<string: a short headline describing a major off-screen event, e.g. 'The Iron Faction has declared war on the Southern Isles'>",
    "<string: another event...>"
  ]
}
~~~

CONSISTENCY RULES:
- Changes must be logical given each entity's current stats.
- Do not invent new entities.  Only update entities provided in the world state.
- You may leave the state_changes list empty if nothing significant occurs.\
"""

_TENSION_LOW_GUIDANCE: str = (
    "WORLD TENSION IS LOW ({tension:.2f}/1.0). "
    "Heavily favour mundane, incremental events: trade, political negotiations, "
    "minor skirmishes, economic shifts.  Avoid dramatic events."
)

_TENSION_HIGH_GUIDANCE: str = (
    "WORLD TENSION IS HIGH ({tension:.2f}/1.0). "
    "Dramatic events are permitted: assassinations, declarations of war, "
    "supernatural occurrences, cataclysms, sudden power shifts."
)

_TENSION_THRESHOLD: float = 0.5

POPULATE_SYSTEM_PROMPT: str = """\
You are a deterministic entity extraction engine.
Your task is to identify unique characters (NPCs) or organized groups (factions) mentioned in the lore.

CRITICAL RULES:
1. Respond ONLY with a ~~~json ... ~~~ fenced block.
2. DO NOT write any conversational text, summaries, or introductions.
3. If no new entities are found, return {"entities": []}.
4. entity_type must be strictly 'npc' or 'faction'.
5. Focus on identifying and describing each entity accurately.
6. STATS RESTRICTION: You MUST ONLY use stat keys provided in the 'AVAILABLE STATS' list. 
   If a stat is not in that list, IT DOES NOT EXIST. Do not invent it.
   If the list is empty, the 'stats' object MUST be empty {}.
"""

def build_populate_prompt(
    lore_chunks: str,
    existing_entities: list[str],
    stat_defs: list[dict] = None,
) -> list[LLMMessage]:
    """Assemble the prompt for the 'Populate' entity generator.

    Args:
        lore_chunks: The text context to analyze for entities.
        existing_entities: List of already defined entity names to skip.
        stat_defs: List of available Stat_Definitions.

    Returns:
        list[LLMMessage] for the LLM.
    """
    skip_list = ""
    if existing_entities:
        skip_list = f"\nALREADY KNOWN ENTITIES (SKIP THESE): {', '.join(existing_entities)}"

    stats_info = "=== AVAILABLE STATS ===\n(No stats defined for this universe. Leave 'stats' empty.)"
    if stat_defs:
        lines = ["=== AVAILABLE STATS ==="]
        for s in stat_defs:
            name = s.get("name")
            vtype = s.get("value_type", "text")
            desc = s.get("description", "No description.")
            params = s.get("parameters", {})
            lines.append(f"- \"{name}\" ({vtype}) : {desc}. Constraints: {params}")
        stats_info = "\n".join(lines)

    user_content = (
        f"{stats_info}\n\n"
        "TASK: Extract NEW unique NPCs or factions from the lore context below.\n"
        "OUTPUT REQUIREMENT: Respond ONLY with the JSON block. No preamble.\n\n"
        "CRITICAL STATS RULE:\n"
        "1. The 'stats' object MUST ONLY contain exact keys from the AVAILABLE STATS list above.\n"
        "2. If a stat does not logically apply, DO NOT include it.\n"
        "3. DO NOT invent, guess, or hallucinate stats (e.g., 'Wisdom', 'HP') if they are not listed above.\n"
        "4. Respect the value_type and Constraints.\n"
        "5. If no stats are listed or relevant, leave the 'stats' object entirely empty {}.\n\n"
        "~~~json\n"
        "{\n"
        "  \"entities\": [\n"
        "    {\n"
        "      \"name\": \"<EXTRACTED_NAME_HERE>\",\n"
        "      \"entity_type\": \"<npc_OR_faction>\",\n"
        "      \"description\": \"<CONCISE_ROLE_DESCRIPTION>\",\n"
        "      \"stats\": {\n"
        "        \"<EXACT_STAT_NAME>\": \"<LOGICAL_VALUE>\"\n"
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "~~~\n\n"
        f"LORE CONTEXT:\n{lore_chunks}\n{skip_list}"
    )

    return [
        {"role": "system", "content": POPULATE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

def _format_lore_book_block(lore_book: list[dict]) -> str:
    """Format a Lore_Book entry list into a category-grouped text block.

    Groups entries by category and formats each as::

        ### Category: Faction
        #### Name: The Red Guard
        Content here...

    Args:
        lore_book: List of entry dicts with keys: category, name, content.

    Returns:
        A formatted multi-line string, or empty string if list is empty.
    """
    if not lore_book:
        return ""

    # Group by category (preserving insertion order)
    groups: dict[str, list[dict]] = {}
    for entry in lore_book:
        cat = entry.get("category", "").strip() or "General"
        groups.setdefault(cat, []).append(entry)

    lines: list[str] = ["=== LORE BOOK ==="]
    for cat, entries in groups.items():
        lines.append(f"\n### Category: {cat}")
        for entry in entries:
            name = entry.get("name", "").strip() or "(unnamed)"
            content = entry.get("content", "").strip()
            lines.append(f"#### {name}")
            if content:
                lines.append(content)
    return "\n".join(lines)


def build_narrative_prompt(
    universe_system_prompt: str,
    entity_stats_block: str,
    rag_chunks: list[str],
    history: list[LLMMessage],
    user_message: str,
    pending_correction: str | None = None,
    global_lore: str | None = None,
    player_persona: str | None = None,
    lore_book: list[dict] | None = None,
    verbosity_level: str = "balanced",
    player_id: str = "player",
    current_time_str: str | None = None,
    scheduled_events: list[dict] | None = None,
) -> list[LLMMessage]:
    """Assemble the full message list for a narrative gameplay turn.

    Structure (in order):
      1. system  — universe prompt + optional global_lore + optional lore_book
                   block + optional player_persona + entity stats + tool-call
                   instructions + verbosity rules
      2. user/assistant pairs — capped prior history (newest HISTORY_TURN_CAP turns)
      3. system  — pending correction (only if not None)
      4. user    — the player's current input (with optional RAG context prepended)

    Args:
        universe_system_prompt: The universe's foundational system prompt.
        entity_stats_block:     Formatted current entity stats string.
        rag_chunks:             Relevant narrative memory chunks for this turn.
        history:                Prior conversation as list[LLMMessage].
        user_message:           The player's raw input for this turn.
        pending_correction:     Hidden correction message for the Correction Loop.
        global_lore:            Optional global lore text from Universe_Meta.
        player_persona:         Optional player background text.
        lore_book:              Optional list of Lore_Book entry dicts; formatted
                                as a category-grouped block under global_lore.
        verbosity_level:        'short', 'balanced', or 'talkative'.
        player_id:              The ID of the player sending the message.
        current_time_str:       Optional formatted time string (e.g. Day 1, 08:00 (Morning)).
        scheduled_events:       Optional list of triggered world events to incorporate.

    Returns:
        list[LLMMessage] ready to pass to any LLMBackend.complete().
    """
    messages: list[LLMMessage] = []

    # 1. Primary system prompt
    parts = [universe_system_prompt]
    
    # Consolidate core narrative rules
    rules = [
        "NARRATOR RULES:",
        "- Formatting: Use *actions* and \"dialogue\".",
        f"- Identity: You are the narrator. Never speak or act for {player_id}.",
        f"- Termination: Stop immediately before {player_id} would react."
    ]
    
    len_map = {
        "short": "CONCISE (2 sentences).",
        "balanced": "MODERATE (1-2 paragraphs).",
        "talkative": "ELABORATE and detailed."
    }
    rules.append(f"- Length: {len_map.get(verbosity_level.lower(), 'MODERATE')}")
    parts.append("\n".join(rules))

    if global_lore and global_lore.strip():
        parts.append(f"WORLD LORE:\n{global_lore.strip()}")
    if lore_book:
        lb_block = _format_lore_book_block(lore_book)
        if lb_block:
            parts.append(lb_block)
    if player_persona and player_persona.strip():
        parts.append(f"CHARACTER BACKGROUND:\n{player_persona.strip()}")
    
    time_header = f"TIME: {current_time_str}\n" if current_time_str else ""
    parts.append(f"CURRENT STATE:\n{time_header}{entity_stats_block}")

    if scheduled_events:
        event_lines = ["WORLD EVENTS TRIGGERED:"]
        for ev in scheduled_events:
            title = ev.get("title", "Event")
            desc = ev.get("description", "")
            event_lines.append(f"- {title}: {desc}")
        event_lines.append("Incorporate these events into your response immediately.")
        parts.append("\n".join(event_lines))

    parts.append(NARRATIVE_TOOL_CALL_SCHEMA)

    system_content = "\n\n".join(parts)
    messages.append({"role": "system", "content": system_content})

    # 2. Capped history (user/assistant pairs only; extra system messages dropped)
    conversation_turns = _extract_conversation_turns(history)
    capped = conversation_turns[-HISTORY_TURN_CAP:]
    for turn_pair in capped:
        messages.extend(turn_pair)

    # 3. Pending correction (injected as system message before user input)
    if pending_correction is not None:
        messages.append({"role": "system", "content": pending_correction})

    # 4. User message with optional RAG context
    if rag_chunks:
        rag_section = "\n\n".join(f"[MEMORY]: {chunk}" for chunk in rag_chunks)
        final_user_content = f"{rag_section}\n\n---\n\n{user_message}"
    else:
        final_user_content = user_message

    messages.append({"role": "user", "content": final_user_content})

    # Phase 11: Final behavior instruction (Recency Bias)
    # This system message is appended AFTER the user message to force compliance.
    verbosity_map = {
        "short": f"[SYSTEM: Response must be VERY SHORT (2 sentences). Do NOT speak for {player_id}.]",
        "balanced": f"[SYSTEM: Response must be BALANCED (1-2 paragraphs). Do NOT speak for {player_id}.]",
        "talkative": f"[SYSTEM: Response must be DETAILED and descriptive. Do NOT speak for {player_id}.]"
    }
    final_instr = verbosity_map.get(verbosity_level.lower(), verbosity_map["balanced"])
    messages.append({"role": "system", "content": final_instr})

    return messages


def build_chronicler_prompt(
    off_screen_entities: list[dict],
    world_tension_level: float,
) -> list[LLMMessage]:
    """Assemble the message list for a Chronicler world-simulation run.

    Structure:
      1. system — base Chronicler prompt + tension guidance
      2. user   — serialised JSON of all off-screen entity states

    Args:
        off_screen_entities: List of entity snapshots, each a dict with at
                             minimum: entity_id, name, entity_type, stats (dict).
        world_tension_level: Float in [0.0, 1.0].  Controls whether the
                             Chronicler is guided toward mundane or dramatic events.

    Returns:
        list[LLMMessage] ready to pass to any LLMBackend.complete().
    """
    tension = max(0.0, min(1.0, world_tension_level))

    if tension >= _TENSION_THRESHOLD:
        guidance = _TENSION_HIGH_GUIDANCE.format(tension=tension)
    else:
        guidance = _TENSION_LOW_GUIDANCE.format(tension=tension)

    system_content = f"{CHRONICLER_SYSTEM_PROMPT_BASE}\n\n{guidance}"

    world_state_json = json.dumps(
        {"world_state": off_screen_entities},
        indent=2,
        ensure_ascii=False,
    )
    user_content = (
        "Simulate the world's independent evolution based on the following state:\n\n"
        f"{world_state_json}"
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def build_mini_dico_prompt(
    question: str,
    rag_chunks: list[str],
    lore_book: list[dict] | None = None,
    global_lore: str | None = None,
) -> list[LLMMessage]:
    """Assemble the message list for a Mini-Dico lore-lookup query.

    The Mini-Dico is strictly siloed from the narrative context: it receives
    ONLY the system persona, relevant lore chunks from RAG, the structured
    Lore Book (if provided), global world lore, and the user's question.

    Args:
        question:    The player's lore question verbatim.
        rag_chunks:  Relevant lore excerpts from VectorMemory.query().
        lore_book:   Optional Lore_Book entry list; formatted and prepended to
                     the user message to give structured world-building context.
        global_lore: Optional foundational world lore from Universe_Meta.

    Returns:
        list[LLMMessage] ready to pass to any LLMBackend.complete().
    """
    sections: list[str] = []

    if global_lore and global_lore.strip():
        sections.append(f"=== GLOBAL WORLD LORE ===\n{global_lore.strip()}")

    lb_block = _format_lore_book_block(lore_book or [])
    if lb_block:
        sections.append(lb_block)

    if rag_chunks:
        lore_section = "\n\n---\n\n".join(rag_chunks)
        sections.append(f"=== LORE REFERENCE EXCERPTS ===\n{lore_section}")
    else:
        sections.append("[No lore excerpts available for this query.]")

    sections.append(f"=== QUESTION ===\n{question}")
    user_content = "\n\n".join(sections)

    return [
        {"role": "system", "content": MINI_DICO_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def format_entity_stats_block(entity_snapshots: list[dict]) -> str:
    """Format a list of entity stat snapshots into a human-readable block.

    Each snapshot should have keys: entity_id, name, entity_type, stats (dict).
    The resulting block is injected directly into the LLM's system prompt so
    it can reference current game state without hallucinating outdated values.

    Args:
        entity_snapshots: List of dicts, each with entity_id, name,
                          entity_type, and stats keys.

    Returns:
        A formatted multi-line string.  Returns "(no entities)" if the list
        is empty.
    """
    if not entity_snapshots:
        return "(no entities)"

    lines: list[str] = []
    for snap in entity_snapshots:
        entity_id: str = snap.get("entity_id", "unknown")
        name: str = snap.get("name", entity_id)
        entity_type: str = snap.get("entity_type", "unknown")
        stats: dict = snap.get("stats", {})

        lines.append(f"[{entity_type.upper()}] {name} (id: {entity_id})")
        if stats:
            for key, value in stats.items():
                lines.append(f"    {key}: {value}")
        else:
            lines.append("    (no stats)")
        lines.append("")  # blank line between entities

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_conversation_turns(
    history: list[LLMMessage],
) -> list[list[LLMMessage]]:
    """Group a flat message list into (user, assistant) turn pairs.

    System messages in the history are dropped — they are not part of the
    conversation turns injected into the prompt (the primary system message
    is constructed separately by build_narrative_prompt).

    Args:
        history: Flat list of LLMMessages from prior turns.

    Returns:
        List of [user_msg, assistant_msg] pairs.  Unpaired trailing user
        messages are included as single-element sublists.
    """
    turns: list[list[LLMMessage]] = []
    current_pair: list[LLMMessage] = []

    for msg in history:
        if msg["role"] == "system":
            continue  # prior system messages are not replayed
        
        # Phase 10: Multi-player consistency. Prepend name to content for the LLM
        # so it knows exactly who said what in a multi-turn history.
        processed_msg = dict(msg)
        
        # Phase 11: Systematic cleaning. Strip media tags from history.
        clean_content = _strip_media_tags(msg["content"])
        
        if msg.get("name") and not clean_content.startswith(f"[{msg['name']}]:"):
            processed_msg["content"] = f"[{msg['name']}]: {clean_content}"
        else:
            processed_msg["content"] = clean_content

        if msg["role"] == "user":
            if current_pair:
                turns.append(current_pair)
            current_pair = [processed_msg]
        elif msg["role"] == "assistant":
            current_pair.append(processed_msg)
            turns.append(current_pair)
            current_pair = []

    if current_pair:
        turns.append(current_pair)

    return turns


def build_timekeeper_prompt(narrative_text: str) -> list[LLMMessage]:
    """Assemble the prompt for the 'Timekeeper' chronological parser.

    Args:
        narrative_text: The LLM's narrative response to analyze.

    Returns:
        list[LLMMessage] for the LLM.
    """
    system_prompt = (
        "You are a deterministic chronological parser. Your sole task is to analyze the provided narrative text "
        "and deduce the amount of in-game time that has passed, and identify if a major event occurred.\n"
        "RULES:\n"
        "1. Respond ONLY with a valid JSON block, no markdown formatting, no preamble.\n"
        "2. JSON schema: {\"elapsed_minutes\": <int>, \"major_event_description\": \"<string or null>\"}\n"
        "3. 1 hour = 60 minutes. 1 day = 1440 minutes.\n"
        "4. If the text describes a brief conversation or quick action, estimate 1 to 5 minutes.\n"
        "5. If the text describes an immediate combat action with no time jump, return 0 or 1.\n"
        "6. Only provide a 'major_event_description' if something highly significant to the plot happens "
        "(e.g., 'Arrived at Hemlock', 'Defeated the Goblin King'). Otherwise, return null."
    )
    user_content = f"NARRATIVE TEXT:\n{narrative_text}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
