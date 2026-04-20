"""
core/st_parser.py

Utility functions for extracting character data from SillyTavern files (PNG/JSON).
"""

import base64
import json
from pathlib import Path
from PIL import Image

def parse_st_card(filepath: str) -> dict:
    """Extract character data from a SillyTavern character card (PNG or JSON).
    
    Args:
        filepath: The path to the .png or .json file.
        
    Returns:
        A dictionary containing the parsed character data.
        
    Raises:
        ValueError: If the file format is unsupported, metadata is missing, or invalid JSON.
    """
    path = Path(filepath)
    ext = path.suffix.lower()
    
    if ext == ".json":
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                # Handle nested data structure common in V2/V3 cards
                if "data" in data:
                    return data["data"]
                return data
        except Exception as exc:
            raise ValueError(f"Failed to parse JSON card: {exc}")
            
    elif ext == ".png":
        try:
            with Image.open(path) as img:
                info = img.info
                chara_base64 = info.get("chara")
                
                if not chara_base64:
                    raise ValueError("PNG does not contain 'chara' metadata (Not a valid ST card).")
                
                decoded_bytes = base64.b64decode(chara_base64)
                data = json.loads(decoded_bytes)
                
                # Handle nested data structure common in V2/V3 cards
                if "data" in data:
                    return data["data"]
                return data
                
        except Exception as exc:
            raise ValueError(f"Failed to extract/parse metadata from PNG: {exc}")
    
    else:
        raise ValueError(f"Unsupported file extension: {ext}")
