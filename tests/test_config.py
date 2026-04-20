"""
tests/test_config.py

Unit tests for core/config.py — AppConfig, load_config, save_config,
build_llm_from_config.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import (
    AppConfig,
    build_llm_from_config,
    load_config,
    save_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_dir(tmp_path: Path):
    """Patch _CONFIG_FILE to use a temp directory."""
    config_file = tmp_path / "settings.json"
    with patch("core.config._CONFIG_FILE", config_file), \
         patch("core.config._CONFIG_DIR", tmp_path):
        yield tmp_path, config_file


# ---------------------------------------------------------------------------
# AppConfig defaults
# ---------------------------------------------------------------------------

class TestAppConfig:
    def test_defaults(self) -> None:
        cfg = AppConfig()
        assert cfg.llm_backend == "universal"
        assert cfg.universal_base_url == "http://localhost:11434/v1"
        assert cfg.universal_model == "llama3.2"
        assert cfg.gemini_api_key == ""
        assert cfg.gemini_model == "gemini-2.0-flash"
        assert cfg.chronicler_interval == 50


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, config_dir) -> None:
        _, config_file = config_dir
        assert not config_file.exists()
        cfg = load_config()
        assert cfg == AppConfig()

    def test_loads_saved_values(self, config_dir) -> None:
        _, config_file = config_dir
        data = {
            "llm_backend": "gemini",
            "gemini_api_key": "test-key",
            "chronicler_interval": 25,
        }
        config_file.write_text(json.dumps(data))
        cfg = load_config()
        assert cfg.llm_backend == "gemini"
        assert cfg.gemini_api_key == "test-key"
        assert cfg.chronicler_interval == 25

    def test_unknown_keys_ignored(self, config_dir) -> None:
        _, config_file = config_dir
        data = {"llm_backend": "universal", "unknown_future_key": "ignored"}
        config_file.write_text(json.dumps(data))
        cfg = load_config()
        assert cfg.llm_backend == "universal"

    def test_malformed_json_returns_defaults(self, config_dir) -> None:
        _, config_file = config_dir
        config_file.write_text("{not valid json")
        cfg = load_config()
        assert cfg == AppConfig()

    def test_never_raises_on_any_error(self, config_dir) -> None:
        _, config_file = config_dir
        config_file.write_text("null")  # valid JSON but wrong type
        cfg = load_config()
        assert isinstance(cfg, AppConfig)


# ---------------------------------------------------------------------------
# save_config + load_config round-trip
# ---------------------------------------------------------------------------

class TestSaveConfig:
    def test_round_trip(self, config_dir) -> None:
        original = AppConfig(
            llm_backend="gemini",
            gemini_api_key="my-secret-key",
            chronicler_interval=10,
        )
        save_config(original)
        loaded = load_config()
        assert loaded.llm_backend == "gemini"
        assert loaded.gemini_api_key == "my-secret-key"
        assert loaded.chronicler_interval == 10

    def test_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "settings.json"
        with patch("core.config._CONFIG_FILE", nested), \
             patch("core.config._CONFIG_DIR", nested.parent):
            save_config(AppConfig())
        assert nested.exists()

    def test_overwrites_existing(self, config_dir) -> None:
        save_config(AppConfig(universal_model="mistral"))
        save_config(AppConfig(universal_model="llama3.2"))
        loaded = load_config()
        assert loaded.universal_model == "llama3.2"


# ---------------------------------------------------------------------------
# build_llm_from_config
# ---------------------------------------------------------------------------

class TestBuildLlmFromConfig:
    def test_ollama_backend_returns_universal_client(self) -> None:
        from llm_engine.universal_client import UniversalClient
        cfg = AppConfig(llm_backend="universal", universal_model="llama3.2")
        llm = build_llm_from_config(cfg)
        assert isinstance(llm, UniversalClient)

    def test_gemini_backend_returns_gemini_client(self) -> None:
        from llm_engine.gemini_client import GeminiClient
        from unittest.mock import patch as p
        with p("llm_engine.gemini_client.genai.Client"):
            cfg = AppConfig(llm_backend="gemini", gemini_api_key="key")
            llm = build_llm_from_config(cfg)
            assert isinstance(llm, GeminiClient)

    def test_unknown_backend_raises_value_error(self) -> None:
        cfg = AppConfig(llm_backend="unknown_ai")
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            build_llm_from_config(cfg)

    def test_gemini_without_api_key_raises(self) -> None:
        cfg = AppConfig(llm_backend="gemini", gemini_api_key="")
        with pytest.raises(ValueError, match="no API key"):
            build_llm_from_config(cfg)

    def test_ollama_url_passed_to_client(self) -> None:
        from llm_engine.universal_client import UniversalClient
        cfg = AppConfig(
            llm_backend="universal",
            universal_base_url="http://192.168.1.5:11434",
            universal_model="mistral",
        )
        llm = build_llm_from_config(cfg)
        assert isinstance(llm, UniversalClient)
        assert llm.base_url == "http://192.168.1.5:11434"
        assert llm.model_name == "mistral"
