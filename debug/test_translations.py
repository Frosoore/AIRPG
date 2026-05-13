"""
debug/test_translations.py

Debug script to verify the localization system.
Prints all translated strings for all supported languages.
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from core.localization import tr, SUPPORTED_LANGUAGES, get_translations_dict

def test_all_translations():
    print("Axiom AI Translation Debug Tool")
    print("============================")
    
    # Mock config to test different languages
    # We'll just read from the dict directly for pure testing
    translations = get_translations_dict()
    
    test_keys = [
        "app_title", "menu_file", "settings_title", "hub_title", 
        "new_universe", "play", "stats", "tab_entities", "death_title"
    ]
    
    for lang_code, lang_name in SUPPORTED_LANGUAGES.items():
        print(f"\nLanguage: {lang_name} ({lang_code})")
        lang_dict = translations.get(lang_code, {})
        
        for key in test_keys:
            val = lang_dict.get(key)
            if val:
                print(f"  {key:20} -> {val}")
            else:
                print(f"  {key:20} -> MISSING (Fallback to en: {translations['en'].get(key, 'N/A')})")

    print("\nVerifying tr() function with active config...")
    from core.config import load_config
    try:
        cfg = load_config()
        print(f"Current Config Language: {cfg.language}")
        print(f"tr('app_title') -> {tr('app_title')}")
    except Exception as e:
        print(f"Could not verify tr() with config: {e}")

if __name__ == "__main__":
    test_all_translations()
