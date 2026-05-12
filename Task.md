# Task Tracker — AIRPG

Status legend: `[ ]` To Do · `[~]` In Progress · `[x]` Done

---

## Phase 1: Foundation & Event Sourcing (No UI)
- [x] 1.1 — Directory Structure & Package Scaffolding
- [x] 1.2 — SQLite Schema
- [x] 1.3 — Event Sourcing Engine
- [x] 1.4 — Checkpoint (Rewind) Logic
- [x] 1.5 — Rules Engine
- [x] 1.6 — Active Modifiers Processor

## Phase 2: LLM Integration & Dual Agents
- [x] 2.1 — LLM Backend Abstraction
- [x] 2.2 — Ollama Client
- [x] 2.3 — Gemini Client
- [x] 2.4 — Prompt Builder
- [x] 2.5 — Vector Memory
- [x] 2.6 — Arbitrator
- [x] 2.7 — Chronicler Engine

## Phase 3: The UI Skeletons (PySide6)
- [x] 3.1 — Package Scaffolding & Entry Point
- [x] 3.2 — Main Window
- [x] 3.3 — Hub View
- [x] 3.4 — Universe Card Widget
- [x] 3.5 — Import/Export Worker
- [x] 3.6 — Creator Studio View
- [x] 3.7 — Entity Editor Widget
- [x] 3.8 — Rule Editor Widget
- [x] 3.9 — Tabletop View
- [x] 3.10 — Chat Display Widget
- [x] 3.11 — Constants Sidebar
- [x] 3.12 — Mini-Dico Panel
- [x] 3.13 — Narrative Worker
- [x] 3.14 — Chronicler Worker
- [x] 3.15 — DB Worker
- [x] 3.16 — Vector Worker
- [x] 3.17 — Mini-Dico Worker
- [x] 3.18 — Checkpoint Dialog

## Phase 4: Assembly & Refinement
- [x] 4.1 — LLM Backend Configuration
- [x] 4.2 — True Per-Token Streaming
- [x] 4.3 — Hardcore Mode: Player Death Detection
- [x] 4.4 — Hardcore Mode: Safe Deletion Sequence
- [x] 4.5 — Signal/Slot Wiring Completion
- [x] 4.6 — Partial Chat History Rewind
- [x] 4.7 — Global Error Handling & First-Run UX
- [x] 4.8 — requirements.txt
- [x] 4.9 — Ubuntu Launch Script (run.sh)

## Phase 5: UX/UI Overhaul & Lore Integration
- [x] 5.1 — Universe Meta & Lore Integration
- [x] 5.2 — Player Persona & Save Management
- [x] 5.3 — Hub Universe Management
- [x] 5.4 — Dynamic Settings Reload
- [x] 5.5 — Aesthetic Polish (QSS)

## Phase 6: Bug Fixes & Lore Book Expansion
- [x] 6.1 — Startup Hub Refresh
- [x] 6.2 — Save Race Condition Fix
- [x] 6.3 — Lore Book Schema
- [x] 6.4 — Lore Book UI
- [x] 6.5 — Lore Book LLM Injection
- [x] 6.6 — Hide JSON blocks in Chat UI
- [x] 6.7 — UI Form Synchronization Fix

## Phase 7: Absolute Persistence Protocol
- [x] 7.1 — Eradicate Silent Failures (UI Wiring)
- [x] 7.2 — Missing Commits & Data Serialization Fix
- [x] 7.3 — Atomic Load Full Universe
- [x] 7.4 — collect_data Sync Enforcement

## Phase 8: Social & Narrative Polish
- [x] 8.1 — Personas System (DDL, Migration, Editor, Hub Integration)
- [x] 8.2 — First Message Option (Creation & Auto-Display)
- [x] 8.3 — Narrative Formatting (Markdown Italics, Dialogue Line Breaks)
- [x] 8.4 — Buffer Truncation Fix (final flush flag)

## Phase 9 — UI Polish & Transition UX (Complete)
- [x] 9.1 — Loading Screen Implementation (Indeterminate progress)
- [x] 9.2 — Global Emoji & Symbol Removal (Standardised ASCII aesthetic)

## Phase 10 — Performance & Resilience (Optimisations)
- [x] 10.1 — Event Sourcing Snapshots (20-turn interval)
- [x] 10.2 — Async Library Loading (Zero-freeze Hub)
- [x] 10.3 — Resilient JSON Parsing (Multi-fence fallback)
- [x] 10.4 — Context Optimization (Heuristic entity filtering)
- [x] 10.5 — RAG-based Lore Book retrieval
- [x] 10.6 — Database Integrity Validator
- [x] 10.7 — Regenerate Worker Argument Fix

## Phase 11: Multiplayer & Temporal Variants
- [x] 11.1 — Dynamic Stop Sequences & Player Impersonation Prevention
- [x] 11.2 — Temporal Variants UI Navigation & Divergence Handling
- [x] 11.3 — Multi-player Queue Logic (ArbitratorWorker adaptation)
- [x] 11.4 — Session Lobby UI (Player ID selection/management)

## Phase 12: Scheduled Events & Lore Enhancements
- [x] 12.1 — Scheduled Events Engine (Interrupting Arbitrator/Chronicler)
- [x] 12.2 — Timeline UI (Creator Studio Event Editor)
- [x] 12.3 — Audio Ambiance Overhaul (Cross-fading & dynamic assets)
- [x] 12.4 — Semantic Entity Filtering (Location/Stat based Context)

## Phase 13: Deep Game Systems
- [x] 13.1 — Inventory & Item System (Schema, Arbitrator Logic, UI Widget)
- [x] 13.2 — Faction Relation Matrix (Stat-based Reputation)
- [x] 13.3 — Timeline Visualizer (Tabletop History View)
- [x] 13.4 — Narrative Chronicler (World News injection)

## Phase 14: Reliability & Deployment
- [x] 14.1 — Verbose Launch Script (run.sh progress tracking)
- [x] 14.2 — System Dependency Validation (python3-venv, libxcb-cursor0 checks)
- [x] 14.3 — Detailed Startup Diagnostics (Import-level validation)
- [x] 14.4 — Documentation Update (System requirements & Troubleshooting)
- [x] 14.5 — Automated Fail-safes (Backups before destructive operations)
- [x] 14.6 — Background Integrity Monitoring (State_Cache validation)
- [x] 14.7 — Root Directory Sanitation (.gitignore, cleanup of test DBs)

## Phase 15: LLM Optimization (7B/8B Support)
- [x] 15.1 — Prompt Compression (Flattening system instructions)
- [x] 15.2 — Schema Simplification (Minimal JSON for small models)
- [x] 15.3 — Narrative Correction Loop (Soft narrator hints vs. technical errors)
- [x] 15.4 — Context Window Pruning (NPC density limiting)

## Phase 16: Public Beta & Community Prep
- [ ] 16.1 — GitHub Action (CI/CD for Linux/Pytest)
- [ ] 16.2 — Contributing.md (Development guidelines)
- [ ] 16.3 — Issue Templates (Bug reports / Feature requests)
- [ ] 16.4 — Security Policy (API key handling documentation)

## Phase 17: Comeback Rework & UX Excellence (Complete)
- [x] 17.1 — Spreadsheet-like Bulk Editing (Multi-cell sync)
- [x] 17.2 — Improved Bulk Deletion (Cell clearing vs Row removal)
- [x] 17.3 — Workflow: Write-before-Add (Focus & Keyboard focus management)
- [x] 17.4 — Keyboard Navigation: Tab/Enter/Del/Ctrl+S/Ctrl+Num
- [x] 17.5 — Entity Studio: Bulk Stat Selection Dialog
- [x] 17.6 — Rule Editor: Strict Stat Validation (Dropdowns only)
- [x] 17.7 — Lore Book: AI Population & Category Management
- [x] 17.8 — Scheduled Events: Fully Custom Calendar Support
- [x] 17.9 — Deployment: SVG Icon Dependency & Absolute Path Fixes
- [x] 17.10 — UX: Descriptive Tooltips & Consistent ASCII Aesthetic

## Phase 18: Spatial Navigation & Hierarchical Mapping
- [x] 18.1 — Database: Locations & Connections tables
- [x] 18.2 — UI: Hierarchical Map Editor (Tree + QGraphicsScene)
- [x] 18.3 — Core: Spatial Context Fetcher (Breadcrumbs & Neighbors)
- [x] 18.4 — Arbitrator: Prompt Injection & Context Optimization
- [x] 18.5 — Integration: Travel Distance -> Time passage logic
- [x] 18.6 — Maintenance: Restore full test coverage (Fix Arbitrator tests)


