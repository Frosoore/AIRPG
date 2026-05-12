"""
database/schema.py

Provisions a fresh AIRPG universe SQLite database with all required tables.
Every universe is stored in a single .db file; this module is the sole authority
over the schema definition.
"""

import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# DDL statements — one constant per table for clarity and testability
# ---------------------------------------------------------------------------

_DDL_UNIVERSE_META = """
CREATE TABLE IF NOT EXISTS Universe_Meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_DDL_ENTITIES = """
CREATE TABLE IF NOT EXISTS Entities (
    entity_id   TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('player', 'npc', 'faction', 'world')),
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1))
);
"""

_DDL_ENTITY_STATS = """
CREATE TABLE IF NOT EXISTS Entity_Stats (
    entity_id  TEXT NOT NULL,
    stat_key   TEXT NOT NULL,
    stat_value TEXT NOT NULL,
    PRIMARY KEY (entity_id, stat_key),
    FOREIGN KEY (entity_id) REFERENCES Entities(entity_id) ON DELETE CASCADE
);
"""

_DDL_RULES = """
CREATE TABLE IF NOT EXISTS Rules (
    rule_id       TEXT PRIMARY KEY,
    priority      INTEGER NOT NULL DEFAULT 0,
    conditions    TEXT NOT NULL,
    actions       TEXT NOT NULL,
    target_entity TEXT NOT NULL DEFAULT '*'
);
"""

_DDL_ACTIVE_MODIFIERS = """
CREATE TABLE IF NOT EXISTS Active_Modifiers (
    modifier_id     TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    stat_key        TEXT NOT NULL,
    delta           REAL NOT NULL,
    minutes_remaining INTEGER NOT NULL CHECK(minutes_remaining >= 0),
    FOREIGN KEY (entity_id) REFERENCES Entities(entity_id) ON DELETE CASCADE
);
"""

_DDL_SAVES = """
CREATE TABLE IF NOT EXISTS Saves (
    save_id        TEXT PRIMARY KEY,
    player_name    TEXT NOT NULL,
    difficulty     TEXT NOT NULL CHECK(difficulty IN ('Normal', 'Hardcore')),
    last_updated   TEXT NOT NULL,
    player_persona TEXT NOT NULL DEFAULT ''
);
"""

_DDL_EVENT_LOG = """
CREATE TABLE IF NOT EXISTS Event_Log (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    save_id       TEXT NOT NULL,
    turn_id       INTEGER NOT NULL,
    event_type    TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    payload       TEXT NOT NULL,
    FOREIGN KEY (save_id) REFERENCES Saves(save_id) ON DELETE CASCADE
);
"""

_DDL_STATE_CACHE = """
CREATE TABLE IF NOT EXISTS State_Cache (
    save_id    TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    stat_key   TEXT NOT NULL,
    stat_value TEXT NOT NULL,
    PRIMARY KEY (save_id, entity_id, stat_key),
    FOREIGN KEY (save_id) REFERENCES Saves(save_id) ON DELETE CASCADE
);
"""

_DDL_LORE_BOOK = """
CREATE TABLE IF NOT EXISTS Lore_Book (
    entry_id TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT '',
    name     TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '',
    content  TEXT NOT NULL DEFAULT ''
);
"""

_DDL_GLOBAL_PERSONAS = """
CREATE TABLE IF NOT EXISTS Global_Personas (
    persona_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL
);
"""

_DDL_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS Snapshots (
    save_id    TEXT NOT NULL,
    turn_id    INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY (save_id, turn_id),
    FOREIGN KEY (save_id) REFERENCES Saves(save_id) ON DELETE CASCADE
);
"""

_DDL_STAT_DEFINITIONS = """
CREATE TABLE IF NOT EXISTS Stat_Definitions (
    stat_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    value_type  TEXT NOT NULL CHECK(value_type IN ('numeric', 'categorical')),
    parameters  TEXT NOT NULL DEFAULT '{}'
);
"""

_DDL_TIMELINE = """
CREATE TABLE IF NOT EXISTS Timeline (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    save_id       TEXT NOT NULL,
    turn_id       INTEGER NOT NULL,
    in_game_time  INTEGER NOT NULL,
    description   TEXT NOT NULL,
    FOREIGN KEY (save_id) REFERENCES Saves(save_id) ON DELETE CASCADE
);
"""

_DDL_SCHEDULED_EVENTS = """
CREATE TABLE IF NOT EXISTS Scheduled_Events (
    event_id        TEXT PRIMARY KEY,
    trigger_minute  INTEGER NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL
);
"""

_DDL_FIRED_SCHEDULED_EVENTS = """
CREATE TABLE IF NOT EXISTS Fired_Scheduled_Events (
    save_id  TEXT NOT NULL,
    event_id TEXT NOT NULL,
    PRIMARY KEY (save_id, event_id),
    FOREIGN KEY (save_id) REFERENCES Saves(save_id) ON DELETE CASCADE,
    FOREIGN KEY (event_id) REFERENCES Scheduled_Events(event_id) ON DELETE CASCADE
);
"""

_DDL_ITEM_DEFINITIONS = """
CREATE TABLE IF NOT EXISTS Item_Definitions (
    item_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT 'misc',
    weight      REAL NOT NULL DEFAULT 0.0,
    rarity      TEXT NOT NULL DEFAULT 'common'
);
"""

_DDL_ITEMS_INVENTORY = """
CREATE TABLE IF NOT EXISTS Items_Inventory (
    save_id     TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK(quantity >= 0),
    PRIMARY KEY (save_id, entity_id, item_id),
    FOREIGN KEY (save_id) REFERENCES Saves(save_id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES Entities(entity_id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES Item_Definitions(item_id) ON DELETE CASCADE
);
"""

_DDL_STORY_SETUP = """
CREATE TABLE IF NOT EXISTS Story_Setup (
    setup_id       TEXT PRIMARY KEY,
    question       TEXT NOT NULL,
    type           TEXT NOT NULL CHECK(type IN ('text', 'single_choice', 'multi_choice')),
    options        TEXT NOT NULL DEFAULT '[]',
    max_selections INTEGER NOT NULL DEFAULT 1,
    priority       INTEGER NOT NULL DEFAULT 0
);
"""

_DDL_LOCATIONS = """
CREATE TABLE IF NOT EXISTS Locations (
    location_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    scale       TEXT NOT NULL CHECK(scale IN ('universe', 'galaxy', 'world', 'country', 'zone', 'city', 'district', 'building', 'room', 'poi')),
    parent_id   TEXT,
    description TEXT NOT NULL DEFAULT '',
    x           REAL DEFAULT 0,
    y           REAL DEFAULT 0,
    FOREIGN KEY (parent_id) REFERENCES Locations(location_id) ON DELETE CASCADE
);
"""

_DDL_LOCATION_CONNECTIONS = """
CREATE TABLE IF NOT EXISTS Location_Connections (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    distance_km INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id),
    FOREIGN KEY (source_id) REFERENCES Locations(location_id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES Locations(location_id) ON DELETE CASCADE
);
"""

_ALL_DDL: list[str] = [
    _DDL_UNIVERSE_META,
    _DDL_ENTITIES,
    _DDL_ENTITY_STATS,
    _DDL_RULES,
    _DDL_STAT_DEFINITIONS,
    _DDL_ACTIVE_MODIFIERS,
    _DDL_SAVES,
    _DDL_EVENT_LOG,
    _DDL_STATE_CACHE,
    _DDL_LORE_BOOK,
    _DDL_SNAPSHOTS,
    _DDL_TIMELINE,
    _DDL_SCHEDULED_EVENTS,
    _DDL_FIRED_SCHEDULED_EVENTS,
    _DDL_ITEM_DEFINITIONS,
    _DDL_ITEMS_INVENTORY,
    _DDL_STORY_SETUP,
    _DDL_LOCATIONS,
    _DDL_LOCATION_CONNECTIONS,
]

# Canonical set of table names produced by create_universe_db
EXPECTED_TABLES: frozenset[str] = frozenset({
    "Universe_Meta",
    "Entities",
    "Entity_Stats",
    "Rules",
    "Stat_Definitions",
    "Active_Modifiers",
    "Saves",
    "Event_Log",
    "State_Cache",
    "Lore_Book",
    "Snapshots",
    "Timeline",
    "Scheduled_Events",
    "Fired_Scheduled_Events",
    "Item_Definitions",
    "Items_Inventory",
    "Story_Setup",
    "Locations",
    "Location_Connections",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_universe_db(db_path: str) -> None:
    """Provision a fresh AIRPG universe database at the given path.

    Creates the file (and any missing parent directories) if it does not
    already exist, then executes all DDL statements inside a single
    transaction.  Calling this function on an already-provisioned database
    is idempotent (CREATE TABLE IF NOT EXISTS).

    Args:
        db_path: Absolute or relative filesystem path for the .db file.

    Raises:
        sqlite3.Error: If the database cannot be opened or the DDL fails.
        OSError: If parent directories cannot be created.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        for ddl in _ALL_DDL:
            conn.execute(ddl)
        conn.commit()


def create_global_db(db_path: str) -> None:
    """Provision the global user database (personas, etc).

    Args:
        db_path: Path to the global .db file.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(_DDL_GLOBAL_PERSONAS)
        conn.commit()


def migrate_entities_table(db_path: str) -> None:
    """Add the description column to an existing Entities table if absent."""
    with sqlite3.connect(str(db_path)) as conn:
        try:
            conn.execute(
                "ALTER TABLE Entities ADD COLUMN description TEXT NOT NULL DEFAULT '';"
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def migrate_saves_table(db_path: str) -> None:
    """Add the player_persona column to an existing Saves table if absent.

    Idempotent — safe to call on databases provisioned before Phase 5.
    Silently succeeds if the column already exists.

    Args:
        db_path: Path to an existing universe .db file.

    Raises:
        sqlite3.Error: If the ALTER TABLE statement fails for a reason other
                       than the column already existing.
    """
    with sqlite3.connect(str(db_path)) as conn:
        try:
            conn.execute(
                "ALTER TABLE Saves ADD COLUMN player_persona TEXT NOT NULL DEFAULT '';"
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def migrate_lore_book_table(db_path: str) -> None:
    """Create the Lore_Book table if it does not exist in an older database.

    Idempotent — safe to call on any universe database, regardless of age.
    Uses CREATE TABLE IF NOT EXISTS so it silently succeeds when the table
    already exists.

    Args:
        db_path: Path to an existing universe .db file.

    Raises:
        sqlite3.Error: If the statement fails for an unexpected reason.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_DDL_LORE_BOOK)
        conn.commit()


def migrate_stat_definitions_table(db_path: str) -> None:
    """Create the Stat_Definitions table if it does not exist in an older database."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_DDL_STAT_DEFINITIONS)
        conn.commit()


def migrate_timeline_table(db_path: str) -> None:
    """Create the Timeline table if it does not exist in an older database.

    Idempotent — safe to call on any universe database.
    Uses CREATE TABLE IF NOT EXISTS so it silently succeeds when the table
    already exists.

    Args:
        db_path: Path to an existing universe .db file.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_DDL_TIMELINE)
        conn.commit()


def migrate_scheduled_events_table(db_path: str) -> None:
    """Create the Scheduled_Events table if it does not exist in an older database.

    Idempotent — safe to call on any universe database.
    Uses CREATE TABLE IF NOT EXISTS so it silently succeeds when the table
    already exists.

    Args:
        db_path: Path to an existing universe .db file.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_DDL_SCHEDULED_EVENTS)
        conn.commit()


def migrate_inventory_tables(db_path: str) -> None:
    """Create Item_Definitions and Items_Inventory tables if they do not exist."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_DDL_ITEM_DEFINITIONS)
        conn.execute(_DDL_ITEMS_INVENTORY)
        conn.commit()


def migrate_story_setup_table(db_path: str) -> None:
    """Create the Story_Setup table if it does not exist in an older database."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_DDL_STORY_SETUP)
        conn.commit()


def migrate_location_tables(db_path: str) -> None:
    """Create Locations and Location_Connections tables if they do not exist, or migrate them if constraints changed."""
    with sqlite3.connect(str(db_path)) as conn:
        # Check if table exists
        row_loc = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Locations';").fetchone()
        row_conn = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Location_Connections';").fetchone()
        
        if not row_loc:
            # Table doesn't exist, just create them
            conn.execute(_DDL_LOCATIONS)
            conn.execute(_DDL_LOCATION_CONNECTIONS)
        else:
            # Table exists, check for migration needs:
            # 1. New scales (room/poi)
            # 2. Unit change (minutes to km)
            # 3. Corruption (dangling FKs pointing to Locations_Old)
            current_sql_loc = row_loc[0]
            current_sql_conn = row_conn[0] if row_conn else ""
            
            needs_scale_update = ("'room'" not in current_sql_loc or "'poi'" not in current_sql_loc)
            needs_unit_update = ("distance_minutes" in current_sql_conn)
            is_corrupted = ("Locations_Old" in current_sql_conn)
            
            if needs_scale_update or needs_unit_update or is_corrupted:
                # Migration needed or corruption detected
                conn.execute("PRAGMA foreign_keys=OFF;")
                try:
                    conn.execute("BEGIN TRANSACTION;")
                    
                    # A. Migrate Locations
                    conn.execute("DROP TABLE IF EXISTS Locations_Old;")
                    conn.execute("ALTER TABLE Locations RENAME TO Locations_Old;")
                    conn.execute(_DDL_LOCATIONS)
                    # Copy data safely
                    conn.execute(
                        "INSERT INTO Locations (location_id, name, scale, parent_id, description, x, y) "
                        "SELECT location_id, name, scale, parent_id, description, x, y FROM Locations_Old;"
                    )
                    conn.execute("DROP TABLE Locations_Old;")
                    
                    # B. Migrate Location_Connections
                    if row_conn:
                        # Detect which column to copy from
                        info = conn.execute("PRAGMA table_info(Location_Connections);").fetchall()
                        cols = [i[1] for i in info]
                        source_col = "distance_km" if "distance_km" in cols else "distance_minutes"
                        
                        conn.execute("DROP TABLE IF EXISTS Location_Connections_Old;")
                        conn.execute("ALTER TABLE Location_Connections RENAME TO Location_Connections_Old;")
                        conn.execute(_DDL_LOCATION_CONNECTIONS)
                        # Map the old column (minutes or km) to the new distance_km
                        conn.execute(
                            f"INSERT INTO Location_Connections (source_id, target_id, distance_km) "
                            f"SELECT source_id, target_id, {source_col} FROM Location_Connections_Old;"
                        )
                        conn.execute("DROP TABLE Location_Connections_Old;")
                    else:
                        conn.execute(_DDL_LOCATION_CONNECTIONS)
                    
                    conn.execute("COMMIT;")
                    print("[SCHEMA] Location tables successfully migrated/repaired.")
                except Exception as e:
                    conn.execute("ROLLBACK;")
                    print(f"[SCHEMA] Migration failed, rolled back: {e}")
                    # If migration fails, we don't raise here to avoid blocking app start, 
                    # but the DB task worker will likely fail again on usage.
                finally:
                    conn.execute("PRAGMA foreign_keys=ON;")
        
        conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open and return a configured SQLite connection to an existing universe db.

    The caller is responsible for closing the connection (or using it as a
    context manager).  Foreign-key enforcement and WAL journal mode are
    enabled automatically.

    Args:
        db_path: Path to an existing .db file created by create_universe_db().

    Returns:
        An open sqlite3.Connection with FK enforcement and WAL enabled.

    Raises:
        FileNotFoundError: If db_path does not point to an existing file.
        sqlite3.Error: If the connection cannot be established.
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Universe database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn
