"""
tests/test_gemini_client.py

Unit tests for llm_engine/gemini_client.py.

The google.genai SDK is mocked entirely — no real API calls are made.
We patch the client instance created inside GeminiClient.__init__.
"""

from unittest.mock import MagicMock, patch, PropertyMock
from typing import Iterator

import pytest

from llm_engine.base import LLMConnectionError, LLMParseError, LLMResponse
from llm_engine.gemini_client import GeminiClient


# ---------------------------------------------------------------------------
# Helpers — fake SDK objects
# ---------------------------------------------------------------------------

def _make_response(text: str, finish_reason_str: str = "STOP") -> MagicMock:
    """Build a mock GenerateContentResponse."""
    mock_resp = MagicMock()
    mock_resp.text = text

    candidate = MagicMock()
    candidate.finish_reason = finish_reason_str
    mock_resp.candidates = [candidate]
    return mock_resp


def _make_streaming_chunks(tokens: list[str]) -> list[MagicMock]:
    chunks = []
    for token in tokens:
        chunk = MagicMock()
        chunk.text = token
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Fixture: patch genai.Client at instantiation
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client_cls():
    """Patch google.genai.Client so no real HTTP client is created."""
    with patch("llm_engine.gemini_client.genai.Client") as mock_cls:
        yield mock_cls


def _make_gemini_client(mock_client_cls) -> tuple[GeminiClient, MagicMock]:
    """Instantiate GeminiClient with a fully mocked inner client."""
    mock_inner = MagicMock()
    mock_client_cls.return_value = mock_inner
    client = GeminiClient(api_key="fake-key")
    return client, mock_inner


# ---------------------------------------------------------------------------
# _translate_messages (static helper — no SDK dependency)
# ---------------------------------------------------------------------------

class TestTranslateMessages:
    def test_system_becomes_instruction(self) -> None:
        msgs = [
            {"role": "system", "content": "You are a dungeon master."},
            {"role": "user", "content": "I enter the cave."},
        ]
        instruction, contents = GeminiClient._translate_messages(msgs)
        assert instruction == "You are a dungeon master."
        assert contents[0]["role"] == "user"

    def test_assistant_maps_to_model(self) -> None:
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        _, contents = GeminiClient._translate_messages(msgs)
        assert contents[1]["role"] == "model"

    def test_no_system_message(self) -> None:
        msgs = [{"role": "user", "content": "hello"}]
        instruction, contents = GeminiClient._translate_messages(msgs)
        assert instruction is None
        assert len(contents) == 1

    def test_subsequent_system_message_prepended_to_next_user(self) -> None:
        msgs = [
            {"role": "system", "content": "Base system."},
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "system", "content": "Correction note."},
            {"role": "user", "content": "Turn 2"},
        ]
        instruction, contents = GeminiClient._translate_messages(msgs)
        assert instruction == "Base system."
        last_user = contents[-1]
        assert last_user["role"] == "user"
        assert "Correction note." in last_user["parts"][0]["text"]
        assert "Turn 2" in last_user["parts"][0]["text"]

    def test_empty_messages(self) -> None:
        instruction, contents = GeminiClient._translate_messages([])
        assert instruction is None
        assert contents == []


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_returns_true_when_list_models_succeeds(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.list.return_value = [MagicMock()]
        assert client.is_available() is True

    def test_returns_false_on_exception(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.list.side_effect = Exception("auth error")
        assert client.is_available() is False

    def test_never_raises(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.list.side_effect = RuntimeError("unexpected")
        assert client.is_available() is False


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

class TestComplete:
    def test_returns_llm_response(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content.return_value = _make_response("The castle falls.")
        result = client.complete([{"role": "user", "content": "attack"}])
        assert isinstance(result, LLMResponse)
        assert result.narrative_text == "The castle falls."
        assert result.finish_reason == "stop"

    def test_extracts_tool_call(self, mock_client_cls) -> None:
        content = (
            "The goblin dies.\n"
            "~~~json\n"
            '{"state_changes": [{"entity_id": "goblin", "stat_key": "HP", "delta": -50}]}\n'
            "~~~"
        )
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content.return_value = _make_response(content)
        result = client.complete([])
        assert result.tool_call is not None
        assert result.tool_call["state_changes"][0]["entity_id"] == "goblin"
        assert "~~~json" not in result.narrative_text

    def test_finish_reason_length_on_max_tokens(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content.return_value = _make_response("ok", "MAX_TOKENS")
        result = client.complete([])
        assert result.finish_reason == "length"

    def test_finish_reason_stop(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content.return_value = _make_response("ok", "STOP")
        result = client.complete([])
        assert result.finish_reason == "stop"

    def test_system_instruction_passed_in_config(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content.return_value = _make_response("ok")
        messages = [
            {"role": "system", "content": "You are a GM."},
            {"role": "user", "content": "I attack."},
        ]
        client.complete(messages)
        call_kwargs = mock_inner.models.generate_content.call_args.kwargs
        assert call_kwargs["config"].system_instruction == "You are a GM."

    def test_raises_connection_error_on_sdk_exception(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content.side_effect = Exception("network failure")
        with pytest.raises(LLMConnectionError):
            client.complete([])

    def test_raises_parse_error_when_text_is_none(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_resp = _make_response("ok")
        mock_resp.text = None
        mock_inner.models.generate_content.return_value = mock_resp
        with pytest.raises(LLMParseError, match="None text"):
            client.complete([])

    def test_no_system_message_sends_defaults_in_config(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content.return_value = _make_response("ok")
        client.complete([{"role": "user", "content": "hi"}])
        call_kwargs = mock_inner.models.generate_content.call_args.kwargs
        # config should ALWAYS be created now to pass temperature and top_p
        assert call_kwargs["config"] is not None
        assert call_kwargs["config"].temperature == 0.7
        assert call_kwargs["config"].top_p == 1.0
        assert call_kwargs["config"].system_instruction is None


# ---------------------------------------------------------------------------
# stream_tokens
# ---------------------------------------------------------------------------

class TestStreamTokens:
    def test_yields_tokens(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        chunks = _make_streaming_chunks(["Once ", "upon ", "a time."])
        mock_inner.models.generate_content_stream.return_value = iter(chunks)
        tokens = list(client.stream_tokens([{"role": "user", "content": "story"}]))
        assert tokens == ["Once ", "upon ", "a time."]

    def test_skips_empty_chunks(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        empty_chunk = MagicMock()
        empty_chunk.text = ""
        normal_chunk = MagicMock()
        normal_chunk.text = "Hello"
        mock_inner.models.generate_content_stream.return_value = iter([empty_chunk, normal_chunk])
        tokens = list(client.stream_tokens([]))
        assert tokens == ["Hello"]

    def test_raises_connection_error_on_sdk_exception(self, mock_client_cls) -> None:
        client, mock_inner = _make_gemini_client(mock_client_cls)
        mock_inner.models.generate_content_stream.side_effect = Exception("stream error")
        with pytest.raises(LLMConnectionError):
            list(client.stream_tokens([]))

    def test_skips_chunk_with_attribute_error_on_text(self, mock_client_cls) -> None:
        """Chunks that raise AttributeError on .text must be skipped."""
        client, mock_inner = _make_gemini_client(mock_client_cls)

        class _BadChunk:
            @property
            def text(self) -> str:
                raise AttributeError("no text")

        good_chunk = MagicMock()
        good_chunk.text = "Safe text"

        mock_inner.models.generate_content_stream.return_value = iter([_BadChunk(), good_chunk])
        tokens = list(client.stream_tokens([]))
        assert tokens == ["Safe text"]
