
import sqlite3
import json
import pytest
from PySide6.QtCore import QCoreApplication, Qt
from database.schema import create_universe_db
from workers.db_worker import DbWorker

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "universe.db")
    create_universe_db(path)
    return path

def test_load_inventory_and_timeline_signals(db_path):
    save_id = "test_save"
    # 1. Seed DB
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?, 'Player', 'Normal', 'now')", (save_id,))
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name) VALUES ('p1', 'player', 'Hero')")
        conn.execute("INSERT INTO Item_Definitions (item_id, name) VALUES ('sword', 'Sword')")
        conn.execute("INSERT INTO Items_Inventory (save_id, entity_id, item_id, quantity) VALUES (?, 'p1', 'sword', 1)", (save_id,))
        conn.execute("INSERT INTO Timeline (save_id, turn_id, in_game_time, description) VALUES (?, 1, 100, 'Adventure begins')", (save_id,))
        conn.commit()

    worker = DbWorker(db_path)
    
    results = {}
    worker.inventory_loaded.connect(lambda d: results.update({"inventory": d}))
    worker.timeline_loaded.connect(lambda d: results.update({"timeline": d}))

    # 2. Run tasks
    from PySide6.QtCore import QThreadPool
    worker.load_inventory(save_id)
    worker.load_timeline(save_id)
    
    import time
    start = time.time()
    # Wait for signals (using processEvents to allow signals to be delivered)
    while len(results) < 2 and time.time() - start < 5:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    # 3. Assert
    assert "inventory" in results
    assert "p1" in results["inventory"]
    assert results["inventory"]["p1"][0]["item_id"] == "sword"
    
    assert "timeline" in results
    assert len(results["timeline"]) == 1
    assert results["timeline"][0]["description"] == "Adventure begins"

def test_load_full_game_state_signals(db_path):
    save_id = "test_save"
    # 1. Seed DB
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?, 'Player', 'Normal', 'now')", (save_id,))
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name) VALUES ('p1', 'player', 'Hero')")
        conn.execute("INSERT INTO State_Cache (save_id, entity_id, stat_key, stat_value) VALUES (?, 'p1', 'hp', '100')", (save_id,))
        conn.execute("INSERT INTO Item_Definitions (item_id, name) VALUES ('potion', 'Potion')")
        conn.execute("INSERT INTO Items_Inventory (save_id, entity_id, item_id, quantity) VALUES (?, 'p1', 'potion', 2)", (save_id,))
        conn.execute("INSERT INTO Timeline (save_id, turn_id, in_game_time, description) VALUES (?, 1, 200, 'Found potion')", (save_id,))
        conn.commit()

    worker = DbWorker(db_path)
    
    results = {}
    worker.stats_loaded.connect(lambda d: results.update({"stats": d}))
    worker.inventory_loaded.connect(lambda d: results.update({"inventory": d}))
    worker.timeline_loaded.connect(lambda d: results.update({"timeline": d}))

    # 2. Run task
    worker.load_full_game_state(save_id)
    
    import time
    start = time.time()
    while len(results) < 3 and time.time() - start < 5:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    # 3. Assert
    assert "stats" in results
    assert any(s["entity_id"] == "p1" and s["stats"]["hp"] == "100" for s in results["stats"])
    assert "inventory" in results
    assert results["inventory"]["p1"][0]["item_id"] == "potion"
    assert "timeline" in results
    assert results["timeline"][0]["description"] == "Found potion"
