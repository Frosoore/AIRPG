
import sqlite3
import json
import pytest
from database.schema import create_universe_db
from workers.db_worker import DbWorker

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "universe.db")
    create_universe_db(path)
    return path

def test_load_full_universe_signals(db_path):
    # 1. Seed DB with complete data
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO Entities (entity_id, entity_type, name) VALUES ('e1', 'npc', 'Guard')")
        conn.execute("INSERT INTO Entity_Stats (entity_id, stat_key, stat_value) VALUES ('e1', 'hp', '50')")
        conn.execute("INSERT INTO Rules (rule_id, priority, conditions, actions) VALUES ('r1', 10, '{}', '[]')")
        conn.execute("INSERT INTO Universe_Meta (key, value) VALUES ('global_lore', 'The world is round.')")
        conn.execute("INSERT INTO Lore_Book (entry_id, name, content) VALUES ('l1', 'City', 'Big city.')")
        conn.commit()

    worker = DbWorker(db_path)
    
    results = {}
    worker.entities_loaded.connect(lambda d: results.update({"entities": d}))
    worker.rules_loaded.connect(lambda d: results.update({"rules": d}))
    worker.lore_book_loaded.connect(lambda d: results.update({"lore": d}))
    worker.universe_meta_loaded.connect(lambda d: results.update({"meta": d}))

    # 2. Run task
    from PySide6.QtCore import QCoreApplication, Qt
    done = []
    worker.save_complete.connect(lambda: done.append(True), Qt.QueuedConnection)
    worker.load_full_universe()
    
    import time
    start = time.time()
    while not done and time.time() - start < 5:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    # 3. Assert all signals fired with data
    assert "entities" in results and len(results["entities"]) == 1
    assert results["entities"][0]["name"] == "Guard"
    assert results["entities"][0]["stats"]["hp"] == "50"
    
    assert "rules" in results and len(results["rules"]) == 1
    assert results["rules"][0]["rule_id"] == "r1"
    
    assert "lore" in results and len(results["lore"]) == 1
    assert results["lore"][0]["name"] == "City"
    
    assert "meta" in results
    assert results["meta"]["global_lore"] == "The world is round."
