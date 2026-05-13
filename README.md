# AIRPG — AI Role Playing Game

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Qt 6](https://img.shields.io/badge/Qt-6-green.svg)](https://www.qt.io/)

**AIRPG** is a local-first, deterministic sandbox RPG engine that bridges the gap between the narrative freedom of Large Language Models (LLMs) and the strict, mathematical logic of traditional RPGs.

No cloud servers. No data collection. Absolute player sovereignty.

---
![image](assets/main_menu.png "Main Menu")
![image](assets/in_game.png "In Game")
![image](assets/creator.png "Creator")

## Vision

Traditionally, AI-driven games suffer from "hallucinations" where the AI ignores game rules or character stats. AIRPG solves this using an **Arbitrator** architecture: every narrative turn is validated against a deterministic SQLite state machine before being committed to the timeline.

- **Local-First:** Designed for Linux. Your stories and data never leave your machine.
- **Event Sourced:** Every action is an immutable event. Rewind the timeline to any previous turn with perfect state reconstruction.
- **World Simulation:** A background "Chronicler" engine simulates off-screen factions and NPCs, ensuring the world feels alive and independent of the player.
- **Sandbox Rules:** Define your own entities, stats, and JSON-based logic rules without writing code.

---

## Technical Stack

- **Logic & Backend:** Python 3.10+ (Strictly typed)
- **UI Framework:** PySide6 (Qt for Python)
- **Database:** SQLite (Event Sourcing & State Cache)
- **Vector Memory:** ChromaDB + Sentence-Transformers (Local RAG)
- **AI Integration:** 
  - **Local:** Ollama / Universal OpenAI-compatible API
  - **Cloud:** Google Gemini (Optional)

---

## Prerequisites

| Platform | Requirement | Command / Action |
|---|---|---|
| **Linux** | **Python 3.10+** | `sudo apt install python3 python3-pip python3-venv` |
| | **GUI Libraries** | `sudo apt install libxcb-cursor0` |
| **Windows** | **Python 3.10+** | [Download from python.org](https://www.python.org/downloads/) |
| **Optional** | **Ollama** | [Install from ollama.com](https://ollama.com) |

---

## Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Frosoore/AIRPG.git
   cd AIRPG
   ```

2. **Launch the application:**

   **Linux:**
   ```bash
   bash run.sh
   ```

   **Windows:**
   Double-click `run.bat` or run it via CMD/PowerShell.

   *Note: The first launch will automatically create a virtual environment, install dependencies, and download required embedding models. This may take a few minutes.*

3. **Configure your AI:**
   - Open **File → Settings**.
   - **Local (Recommended):** Set up Ollama with `ollama pull llama3.2`.
   - **Cloud:** Enter your Gemini API key.

## Key Features

- **Dual-Agent Architecture:** An *Arbitrator* (deterministic rule-enforcer) and a *Chronicler* (macro-world simulator) work together to keep the story grounded.
- **Event Sourcing:** Every game event is logged. Rewind any session to any previous turn with perfect state reconstruction.
- **Spreadsheet Studio:** Powerful universe creator with bulk-editing, keyboard navigation, and AI-assisted population.
- **Custom Calendars:** Define your own time systems, month names, and adventure start dates.
- **Vector Memory (RAG):** Local semantic search via ChromaDB for infinite lore and narrative consistency.
- **Hardcore Mode:** True stakes—character death triggers permanent file deletion and memory wipe.
- **Architecture Optimized:**
    - **Lazy-Loading:** Heavy AI libraries (ChromaDB, Transformers) only load when needed, saving RAM on startup.
    - **Snapshots:** 20-turn snapshots for near-instant state reconstruction in long campaigns.
    - **Context Pruning:** Heuristic entity filtering to support small local models (7B/8B) without context overflow.

---

## Architecture Overview

- **The Arbitrator:** The deterministic firewall. It parses LLM tool-calls, validates them against current stats, and enforces rules.
- **The Chronicler:** A background agent that performs "World Turns" every X player turns to update the macro-state of the universe.
- **Mini-Dico:** A secondary, RAG-powered chat for lore lookups that is strictly siloed from the main narrative to prevent context contamination.
- **Snapshot System:** Efficient state recovery using periodic snapshots of the event stream.
- **Lazy I/O:** All database and AI operations run in dedicated QThread workers to keep the UI responsive at all times.

---

## Contributing

We welcome contributions! Whether it's bug fixes, new UI features, or lore templates.

1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Run tests to ensure no regressions: `bash test.sh`.
4. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
5. Push to the branch (`git push origin feature/AmazingFeature`).
6. Open a Pull Request.

---

## License

Distributed under the MIT License. See `LICENSE` (to be added) for more information.

## Acknowledgments

- Built for the Linux community and AI roleplaying enthusiasts.
- Inspired by the flexibility of tabletop RPGs and the power of local inference.
