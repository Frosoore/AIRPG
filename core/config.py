"""
core/config.py

Application configuration model for AIRPG.

Stores user preferences (LLM backend, model names, API keys, Chronicler
interval) in a JSON file at ~/.config/AIRPG/settings.json.

This module is pure Python with no UI dependencies — it can be imported
by workers and backend code safely.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from llm_engine.base import LLMBackend


_CONFIG_DIR: Path = Path.home() / ".config" / "AIRPG"
_CONFIG_FILE: Path = _CONFIG_DIR / "settings.json"
GLOBAL_DB_FILE: Path = _CONFIG_DIR / "global.db"


@dataclass
class AppConfig:
    """User preferences for AIRPG.

    Attributes:
        llm_backend:         Active backend — "universal" or "gemini".
        universal_base_url:  Base URL for Universal API (e.g. OpenAI-compatible).
        universal_api_key:   Optional API key for Universal API.
        universal_model:     Model identifier for Universal API.
        gemini_api_key:      Google Gemini API key (may be empty).
        gemini_model:        Gemini model identifier.
        extraction_model:    Model used specifically for data extraction (Populate).
        chronicler_interval: Player turns between Chronicler runs.
        ui_font_size:        Font size for the chat UI.
        enable_audio:        Whether background ambiance is enabled.
        rag_chunk_count:     Number of memory chunks to retrieve for RAG.
    """

    llm_backend: str = "universal"
    universal_base_url: str = "http://localhost:11434/v1"
    universal_api_key: str = ""
    universal_model: str = "llama3.2"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    extraction_model: str = "llama3.1:8b"
    chronicler_interval: int = 50
    ui_font_size: int = 14
    enable_audio: bool = True
    rag_chunk_count: int = 5


def load_config() -> AppConfig:
    """Load configuration from the settings file.

    Returns sensible defaults if the file does not exist or is malformed.
    Never raises.

    Returns:
        AppConfig populated from disk, or a default AppConfig on any error.
    """
    from database.schema import create_global_db
    try:
        create_global_db(str(GLOBAL_DB_FILE))
    except Exception:
        pass

    if not _CONFIG_FILE.exists():
        return AppConfig()

    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        # Migrate old ollama settings if universal is missing
        if "ollama_base_url" in raw and "universal_base_url" not in raw:
            old_url = raw.pop("ollama_base_url")
            # If they had the standard ollama URL, upgrade it to the /v1 endpoint
            if old_url.endswith("11434"):
                old_url += "/v1"
            elif old_url.endswith("11434/"):
                old_url += "v1"
            raw["universal_base_url"] = old_url
        if "ollama_model" in raw and "universal_model" not in raw:
            raw["universal_model"] = raw.pop("ollama_model")
        if raw.get("llm_backend") == "ollama":
            raw["llm_backend"] = "universal"

        # Only accept known keys — ignore unknown keys gracefully
        known = {f for f in AppConfig.__dataclass_fields__}
        filtered = {k: v for k, v in raw.items() if k in known}
        return AppConfig(**filtered)
    except Exception:
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Persist an AppConfig to the settings file.

    Creates the config directory if it does not exist.

    Args:
        config: The configuration to save.

    Raises:
        OSError: If the file cannot be written (propagated to the caller).
    """
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def build_llm_from_config(config: AppConfig, model_override: str | None = None) -> LLMBackend:
    """Instantiate and return the correct LLMBackend for the given config.

    Args:
        config:         The current AppConfig.
        model_override: Optional model identifier to use instead of the default.

    Returns:
        A concrete LLMBackend instance ready for use.

    Raises:
        ValueError: If config.llm_backend is not "universal" or "gemini".
    """
    from llm_engine.universal_client import UniversalClient
    from llm_engine.gemini_client import GeminiClient

    backend = config.llm_backend.lower().strip()

    # Treat old "ollama" config as "universal"
    if backend == "ollama" or backend == "universal":
        return UniversalClient(
            base_url=config.universal_base_url,
            api_key=config.universal_api_key,
            model_name=model_override if model_override else config.universal_model,
        )

    if backend == "gemini":
        if not config.gemini_api_key:
            raise ValueError(
                "Gemini backend selected but no API key is configured. "
                "Add your key in File → Settings → Cloud (Gemini)."
            )
        return GeminiClient(
            api_key=config.gemini_api_key,
            model_name=model_override if model_override else config.gemini_model,
        )

    raise ValueError(
        f"Unknown LLM backend: '{config.llm_backend}'. "
        "Expected 'universal' or 'gemini'."
    )
