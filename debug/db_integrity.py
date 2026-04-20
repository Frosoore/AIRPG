
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from database.event_sourcing import EventSourcer

def check_integrity(db_path: str):
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    es = EventSourcer(db_path)
    
    # Get all saves
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT save_id, player_name FROM Saves;").fetchall()
    
    if not rows:
        print("No saves found in this database.")
        return

    for save_id, player_name in rows:
        print(f"--- Checking Save: {player_name} ({save_id}) ---")
        passed, mismatches = es.validate_integrity(save_id)
        if passed:
            print("  Result: [PASSED] Cache is perfectly consistent with history.")
        else:
            print(f"  Result: [FAILED] {len(mismatches)} entities have inconsistent stats!")
            for eid, stats in mismatches.items():
                print(f"    - Entity: {eid}")
                for sk, (cached, actual) in stats.items():
                    print(f"      * {sk}: Cached='{cached}', Actual='{actual}'")
            
            print("\n  [INFO] You can fix this by running 'es.rebuild_state_cache(save_id, force_full=True)'")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_db_integrity.py <path_to_universe_db>")
        sys.exit(1)
    
    check_integrity(sys.argv[1])
