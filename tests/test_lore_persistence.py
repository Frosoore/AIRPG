
import os
import sqlite3
import pytest
from workers.db_worker import DbWorker
from database.schema import create_universe_db

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_universe.db")
    create_universe_db(path)
    return path

def test_lore_book_persistence_cycle(db_path):
    # 1. Prepare data
    entities = [{"entity_id": "e1", "entity_type": "npc", "name": "Npc 1", "stats": {"hp": "10"}}]
    rules = []
    meta = {"universe_name": "Test Universe", "global_lore": "Some lore"}
    lore_book = [
        {"entry_id": "l1", "category": "Factions", "name": "The Guard", "content": "Guard content"},
        {"entry_id": "l2", "category": "Locations", "name": "The Castle", "content": "Castle content"}
    ]

    # 2. Save data using DbWorker logic (simulated)
    from PySide6.QtCore import QCoreApplication, Qt
    import time
    done = []
    worker = DbWorker(db_path)
    worker.save_complete.connect(lambda: done.append(True), Qt.QueuedConnection)
    worker.save_full_universe(entities, rules, meta, lore_book)
    
    start = time.time()
    while not done and time.time() - start < 5:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    # 3. Verify in DB directly
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM Lore_Book ORDER BY entry_id ASC").fetchall()
        assert len(rows) == 2
        assert rows[0]["entry_id"] == "l1"
        assert rows[0]["name"] == "The Guard"
        assert rows[1]["entry_id"] == "l2"
        assert rows[1]["category"] == "Locations"

    # 4. Load data using DbWorker logic
    loaded_lore = []
    def on_lore_loaded(data):
        loaded_lore.extend(data)
    
    from PySide6.QtCore import Qt
    done2 = []
    worker.save_complete.connect(lambda: done2.append(True), Qt.QueuedConnection)
    worker.lore_book_loaded.connect(on_lore_loaded, Qt.QueuedConnection)
    worker.load_entities_and_rules()
    
    start = time.time()
    while not done2 and time.time() - start < 5:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    assert len(loaded_lore) == 2
    assert loaded_lore[0]["name"] == "The Guard"
    assert loaded_lore[1]["content"] == "Castle content"
