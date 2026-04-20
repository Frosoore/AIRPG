Master Specification: AIRPG (Artificial Intelligence Role Playing Game)

1. Core Vision & Philosophy

AIRPG is a local, highly customizable, sandbox RPG engine. It bridges the gap between the narrative freedom of Large Language Models (LLMs) and the strict, deterministic logic of traditional RPG engines.

Language: The entire application (UI, codebase, comments, logs) MUST be in English. This ensures maximum comprehension by the AI development agent and consistency across all internal documentation.

Priority: Functionality, structural solidity, and deterministic logic over visual aesthetics. The foundation must be mathematically infallible before any graphical polish is applied.

Environment: Native Ubuntu/Linux execution. The software must be self-contained, requiring no external cloud servers for state management, ensuring absolute user data privacy and sovereignty.

The Sandbox Principle: Creators have absolute power over the mathematical reality of their universe. There are no hardcoded "HP" or "Mana" concepts unless the creator explicitly defines them. The engine simply provides the deterministic framework to enforce whatever concepts the creator imagines.

Code Constraint: This specification document explicitly forbids the inclusion of code snippets to maintain high-level architectural focus. The AI agent must derive the code from these strict logical constraints.

2. Technical Stack Mandate

To ensure stability and prevent the AI agent from wandering between frameworks or suggesting trend-chasing web technologies, the stack is strictly defined and justified:

Backend & Logic: Python 3.10+. Python is mandated due to its unparalleled ecosystem for local AI integration, vector database management, and rapid logical prototyping. Strict type-hinting is required across the entire codebase to prevent runtime errors.

Frontend / UI: PySide6 (Qt for Python). We require robust desktop integration, OS-native window management, and strict multi-threading capabilities. Web-based wrappers (like Electron) are forbidden due to high memory overhead and IPC (Inter-Process Communication) complexities when dealing with heavy local LLM inference.

Database (State & Constants): SQLite. Local .db files per universe/save provide an ACID-compliant, portable, and easily queryable ledger. It requires no background server processes, making it perfect for a standalone desktop application.

Vector Database (Memory): FAISS or ChromaDB (running locally). These tools allow the application to efficiently chunk, embed, and query past chat history without relying on expensive cloud embedding APIs like OpenAI's.

Creator Logic Sandbox: UI-driven Rules Engine. This is a JSON-based condition/action architecture. Arbitrary code execution (like allowing users to write Lua or raw Python scripts inside the game files) is strictly prohibited to prevent malicious code injection when users share their universes online.

3. Detailed Architectural Constraints (Crucial for AI Agent)

To prevent token waste and structural refactoring, the following architectural paradigms MUST be strictly implemented. Note that the world is dynamic: stats apply not just to the Player, but to NPCs, Factions, and the World itself.

A. Conceptual Database Schema (SQLite)

Do not invent complex, highly normalized schemas. Stick to this robust, flat conceptual structure per .airpg universe:

Table Universe_Meta: Stores global lore, foundational system prompts, default configurations, and a global World_Tension_Level (a float value that determines the probability and severity of major global events).

Table Entities: The core of a dynamic world. This tracks distinct actors (the Player, specific NPCs, entire Cities, or Factions). Every entity has its own dynamic constants stored as key-value pairs (e.g., King_Status: "Alive", City_Wealth: 5000, Faction_Reputation: -50). This allows the world to exist mathematically outside of the player's immediate view.

Table Rules: The JSON constraints defined by the creator. These map "Conditions" (e.g., Target Entity HP <= 0) to "Actions" (e.g., Trigger Death State, Drop Loot). This table must support targeting specific Entities dynamically.

Table Active_Modifiers: Tracks temporary Status Effects (buffs, debuffs, curses, blessings). Every modifier has a 'turn-duration' countdown. The backend must decrement this counter every turn and purge modifiers that reach zero, recalculating the entity's effective stats.

Table Saves: Metadata for user playthroughs, including the Save ID, Player Name, Difficulty Mode (Normal vs. Hardcore), and the timestamp of the last interaction.

Table Event_Log (Event Sourcing): The absolute, immutable source of truth for the game state. Columns must include: event_id (primary key), save_id, turn_id (the specific chat turn), event_type (e.g., 'dialogue', 'stat_change', 'combat_roll'), target_entity, and a payload (a JSON string of the exact change).

Table State_Cache: A materialized view or continuously updated table representing the current numerical stats for ALL entities. This exists purely for performance, avoiding the need to replay the entire Event_Log from turn 0 every time the UI refreshes the sidebar.

B. Concurrency & UI Threading (Mandatory)

PySide6 will permanently freeze and become unresponsive if LLM network calls, disk I/O, or local inference block the main event loop.

Worker Threads: ALL interactions with the LLM (generating responses, parsing JSON), disk writes to SQLite, and Vector DB embedding tasks MUST be executed in separate QThread instances.

Communication: The backend must communicate with the main thread exclusively using Qt Signals and Slots. For example, a Worker thread should emit a signal for every new token received from the LLM, allowing the main UI thread to append the text to the chat window fluidly, creating a typewriter effect without stuttering.

C. The Mini-Dico Architecture

The secondary "Lore Dictionary" chat provides instant lore clarifications. It must be strictly siloed from the main narrative context to prevent character contamination.

Separation of Context: Queries made here trigger an entirely separate LLM API call. It does NOT send the player's current chat history or current situation. It only sends the user's explicit question, heavily injected with relevant chunks retrieved from Universe_Meta via the RAG (Retrieval-Augmented Generation) pipeline.

Tone & Persona: This requires a highly restrictive System Prompt enforcing cold, concise, encyclopedic answers. The AI must be instructed to never roleplay, never advance the plot, and only state established facts from the retrieved lore.

D. Vector Memory Checkpoint Handling

Reverting to a previous save state requires surgical precision in the Vector DB to prevent future, "undone" memories from bleeding into the past.

Metadata Strategy: Every narrative memory chunk embedded and inserted into the Vector DB MUST include a strict metadata tag: turn_id.

Rollback Logic: When the player triggers a rewind to return to turn_id: 45, the system must execute a destructive query on the Vector DB, permanently dropping or filtering out all embeddings where the metadata turn_id is strictly greater than 45.

E. Macro-Simulation: The "Chronicler" Engine

To simulate a living world independent of the player without causing the local AI to enter hallucination loops or logic contradictions, the architecture relies on a secondary, background agent.

The World Turn: The Chronicler does NOT run on every player chat message (which would be too slow and expensive). It triggers periodically based on a threshold (e.g., every 50 player turns, or automatically when the player performs a time-skip action like sleeping or traveling long distances).

Mechanic: A background LLM call is fed the current state of major off-screen Entities (Factions, VIP NPCs) and their recent history. It is instructed to simulate their independent actions. It then outputs JSON tool calls to update their stats/status in the database.

Consistency over Cliché: If the Chronicler decides to assassinate the King, it updates the King_Status to Dead in the SQLite database. When the player later enters the capital, the local player AI is forced to read this constant from the database, making it mathematically impossible for the local AI to accidentally hallucinate that the King is still alive and throwing a banquet.

Organic Plot Twists: The Chronicler uses the World_Tension_Level to throttle dramatic events. A low tension value forces the Chronicler's prompts to heavily favor mundane economic or political shifts. A high tension value removes these constraints, allowing the Chronicler to generate assassinations, wars, or cataclysms.

4. State Management & The Arbitrator

A. Event Sourcing (The Checkpoint System)

Traditional RPGs overwrite a save file. AIRPG uses Event Sourcing to maintain a perfect, rewindable history.

Transaction Log: Every single state change (for ANY entity, whether triggered by the Player, a Rule, or the Chronicler) is recorded as a discrete event in the Event_Log.

Rewind Mechanism (Normal Mode): To revert to a past state, the engine does not load an old file. It deletes the chat history, vector memories, and Event_Log entries that occurred after the target turn ID. It then completely flushes the State_Cache and rebuilds it from scratch by replaying the remaining events in chronological order.

Hardcore Mode: Upon receiving a "Player_Death" event trigger from the Rules Engine, the system immediately bypasses the rewind mechanism and irrevocably deletes the save directory and all associated databases from the Ubuntu file system.

B. The Arbitrator (The Logic Bridge)

The Arbitrator acts as a strict, unyielding firewall between the creative chaos of LLM hallucinations and the game's deterministic mathematical state.

Mechanism: LLM Tool Calling (Structured Output). The narrative LLM is strictly prompted to output its narrative text alongside a structured JSON object representing its intended state changes targeting specific Entities.

Validation & Rejection: Before any text is shown to the user, the Rules Engine evaluates the LLM's JSON against the creator's Rules and the current Active_Modifiers in the State_Cache.

The Correction Loop: If the LLM attempts an invalid action (e.g., trying to deduct 50 Gold when the player only has 10), the Arbitrator MUST NOT retry the API call (which wastes time and tokens). Instead, it nullifies the math change, displays the LLM's text, but invisibly injects a hidden System prompt into the very next turn's context (e.g., "System Notification: The previous transaction failed because Entity:Player had insufficient Gold. Acknowledge this failure naturally in your next response.").

C. Local Package Management (The .airpg format)

There is no centralized, hosted server. Universes are shared peer-to-peer to ensure longevity and independence.

Export: The Creator Studio gathers the Universe_Meta lore, the JSON rules, the entity templates, and initial constants, zipping them into a compressed archive with a custom .airpg extension.

Import: The Hub interface allows users to select .airpg files from their local Ubuntu file system. The application unpacks the archive, validates the JSON schemas, and provisions a new local SQLite database for that specific universe in the application's library directory.

5. Production Phases (For Claude Code Agent)

To prevent the AI agent from losing context, development must proceed strictly in these granular phases.

Phase 1: Foundation & Event Sourcing (No UI)

Initialize the directory structure (e.g., core/, database/, llm_engine/).

Create and commit the mandatory tracker files: Changelog.md and Task.md.

Implement the SQLite schema setup scripts, ensuring Entities, Active_Modifiers, and global World_Tension tables are properly relational.

Build the core Event Sourcing class: writing to the Event_Log and the logic to rebuild the State_Cache from a specific turn ID.

Develop the Checkpoint rewind logic, ensuring it safely drops future events.

Develop the JSON-based Rules Engine parser. Build comprehensive unit tests to ensure it correctly evaluates complex nested conditions (AND/OR logic) and executes stat changes.

Phase 2: LLM Integration & Dual Agents

Implement standardized API wrappers for Local models (Ollama format) and Remote models (Gemini format).

Build the Arbitrator pipeline: Prompting the LLM for Tool Calls, capturing the JSON output, and passing it to the Rules Engine for validation.

Implement the Correction Loop for rejected Arbitrator actions.

Build the Chronicler Engine: Create the background loop that triggers based on turn counts, formats the global entity states into a prompt, and processes the resulting global updates.

Integrate the local Vector DB (FAISS/Chroma). Implement the embedding logic with strict turn_id metadata tagging and the destructive rollback function.

Phase 3: The UI Skeletons (PySide6)

Set up the main PySide6 application loop and main window structure.

Main Hub: Build the grid view for the local library, and the file dialog logic for the Import/Export of .airpg archives.

Creator Studio: Construct a dynamic, visual form interface that allows users to build JSON rules (Conditions/Actions dropdowns) and create Entity Templates without seeing raw JSON.

Tabletop (Chat): Build the main scrolling text view, the Mini-Dico side-panel, and the dynamic Constants sidebar. Implement the QThread worker classes here to ensure the UI never blocks during LLM or DB operations.

Phase 4: Assembly & Refinement

Connect all PySide6 UI signals and slots to the Python backend logic developed in Phases 1 and 2.

Implement the Hardcore mode file deletion sequence, ensuring file locks are safely released before directory deletion.

Polish the UI token streaming so text appears character-by-character fluidly.

Implement error handling popups for edge cases (e.g., missing local LLM server, corrupted .airpg file).

Finalize the requirements.txt and packaging scripts for seamless Ubuntu execution.

6. Coding Standards & Rules for Claude Code

File Management: The agent MUST iteratively update Changelog.md and Task.md before moving to a new file or phase. These files act as the agent's persistent memory.

Modularity: Strict separation of concerns (MVC architecture). Logic must never be written directly inside PySide6 UI files. No single file should exceed 500 lines.

Typing & Linting: Strict Python type hints (-> int, : str) are mandatory for all function signatures.

Error Handling: Corrupted states or failed API calls must trigger safe fallbacks or explicit UI error messages. Silent failures and empty except: blocks are strictly forbidden.

Documentation: Comprehensive Python docstrings must be provided for every class and method, detailing expected inputs, side effects, and return values.

7. Expected Deliverable

A highly stable, entirely local Python/PySide6 desktop application optimized for Ubuntu. It must flawlessly execute dynamic AI text adventures where a background "Chronicler" engine simulates a living, independent world, while a strict, event-sourced Rules Engine prevents AI hallucinations from breaking deterministic RPG mechanics, demonstrating zero UI freezing and mathematically perfect Checkpoint rewinds.