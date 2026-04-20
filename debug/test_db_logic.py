
import unittest
import sys
import sqlite3
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from database.schema import create_universe_db, get_connection

class TestDBLogic(unittest.TestCase):
    def setUp(self):
        self.db_path = "debug_test.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        create_universe_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_universe_meta_params(self):
        # 1. Insert params
        temp = 0.85
        top_p = 0.95
        
        with get_connection(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES (?, ?);", ("llm_temperature", str(temp)))
            conn.execute("INSERT OR REPLACE INTO Universe_Meta (key, value) VALUES (?, ?);", ("llm_top_p", str(top_p)))
            conn.commit()
            
        # 2. Read back
        with get_connection(self.db_path) as conn:
            row_temp = conn.execute("SELECT value FROM Universe_Meta WHERE key = 'llm_temperature';").fetchone()
            row_top_p = conn.execute("SELECT value FROM Universe_Meta WHERE key = 'llm_top_p';").fetchone()
            
            self.assertEqual(float(row_temp[0]), temp)
            self.assertEqual(float(row_top_p[0]), top_p)

if __name__ == "__main__":
    unittest.main()
