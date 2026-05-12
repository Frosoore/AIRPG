
import sys
import os
import traceback

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_db_worker():
    """Verify that DbWorker has all required signals defined on the class."""
    print("[1/3] Checking DbWorker signals...")
    try:
        from workers.db_worker import DbWorker
        
        # Signals in PySide6 are class attributes. We don't need an instance.
        required_signals = [
            'stats_loaded', 'checkpoints_loaded', 'rewind_complete',
            'universe_meta_loaded', 'stat_definitions_loaded', 'entities_loaded',
            'rules_loaded', 'lore_book_loaded', 'scheduled_events_loaded',
            'personas_loaded', 'library_loaded', 'saves_loaded',
            'history_loaded', 'modifiers_ticked', 'variant_updated',
            'full_universe_loaded',
            'save_complete', 'error_occurred', 'status_update'
        ]
        
        missing = []
        for sig in required_signals:
            if not hasattr(DbWorker, sig):
                missing.append(sig)
        
        if missing:
            print(f"FAILED: Missing signals in DbWorker class: {missing}")
            return False
        
        print("SUCCESS: DbWorker signals verified.")
        return True
            
    except Exception as e:
        print(f"FAILED: Unexpected error checking DbWorker: {e}")
        return False

def check_schema():
    """Verify that the schema producing function includes the new spatial tables."""
    print("[2/3] Verifying database schema...")
    try:
        from database.schema import EXPECTED_TABLES
        new_tables = ["Locations", "Location_Connections"]
        missing = [t for t in new_tables if t not in EXPECTED_TABLES]
        if missing:
            print(f"FAILED: Missing spatial tables in EXPECTED_TABLES: {missing}")
            return False
        print("SUCCESS: Spatial tables present in schema definition.")
        return True
    except Exception as e:
        print(f"FAILED: Unexpected error checking schema: {e}")
        return False

def check_imports():
    """Verify core imports aren't broken."""
    print("[3/3] Verifying core imports...")
    core_modules = [
        ('PySide6.QtWidgets', 'pyside6'),
        ('chromadb', 'chromadb'),
        ('sentence_transformers', 'sentence-transformers'),
        ('google.genai', 'google-genai'),
        ('PIL', 'pillow'),
        ('core.arbitrator', 'core'),
        ('database.schema', 'database'),
        ('llm_engine.base', 'llm_engine'),
        ('ui.main_window', 'ui')
    ]
    
    all_ok = True
    for mod_name, pkg_name in core_modules:
        try:
            __import__(mod_name)
            print(f"  OK: {mod_name}")
        except ImportError as e:
            print(f"  FAILED: Could not import '{mod_name}' (package: {pkg_name})")
            print(f"  Error: {e}")
            if pkg_name in ['pyside6', 'chromadb', 'sentence-transformers']:
                print(f"  HINT: Try running 'pip install {pkg_name}' manually in the .venv")
            all_ok = False
        except Exception as e:
            print(f"  FAILED: Unexpected error importing '{mod_name}': {e}")
            all_ok = False
            
    if all_ok:
        print("SUCCESS: Core imports verified.")
    return all_ok

def run_checks():
    """Main entry point for startup validation, called by main.py."""
    print("--- AIRPG Startup Validation ---")
    
    if not check_db_worker():
        sys.exit(1)

    if not check_schema():
        sys.exit(1)
        
    if not check_imports():
        print("\nERROR: Some dependencies are missing or broken.")
        if sys.platform != "win32":
            print("If you are on Linux, ensure you have installed system requirements:")
            print("  sudo apt install python3-venv libxcb-cursor0")
        
        print("\nTry recreating the virtual environment:")
        if sys.platform == "win32":
            print("  rd /s /q .venv && run.bat")
        else:
            print("  rm -rf .venv && bash run.sh")
        sys.exit(1)
        
    print("--- Startup Validation Passed ---\n")

if __name__ == "__main__":
    run_checks()
