"""
tests/test_ollama_client.py

Unit tests for llm_engine/ollama_client.py.

All HTTP interactions are mocked at the httpx transport layer using
httpx.MockTransport / unittest.mock.  No real network calls are made.
"""

import json
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Iterator

import httpx
import pytest

from llm_engine.base import LLMConnectionError, LLMParseError, LLMResponse
from llm_engine.ollama_client import OllamaClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chat_response(content: str, done: bool = True, status: int = 200) -> MagicMock:
    """Build a mock httpx.Response for /api/chat (non-streaming)."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status
    mock_resp.json.return_value = {
        "message": {"role": "assistant", "content": content},
        "done": done,
    }
    return mock_resp


def _make_tags_response(status: int = 200) -> MagicMock:
    """Build a mock httpx.Response for /api/tags."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status
    return mock_resp


def _ndjson_lines(tokens: list[str]) -> list[str]:
    """Build NDJSON lines as Ollama would emit for a streaming response."""
    lines = []
    for i, token in enumerate(tokens):
        done = (i == len(tokens) - 1)
        lines.append(json.dumps({"message": {"content": token}, "done": done}))
    return lines


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_returns_true_on_200(self) -> None:
        with patch("httpx.get", return_value=_make_tags_response(200)):
            client = OllamaClient("llama3.2")
            assert client.is_available() is True

    def test_returns_false_on_non_200(self) -> None:
        with patch("httpx.get", return_value=_make_tags_response(404)):
            client = OllamaClient("llama3.2")
            assert client.is_available() is False

    def test_returns_false_on_connection_error(self) -> None:
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            client = OllamaClient("llama3.2")
            assert client.is_available() is False

    def test_returns_false_on_timeout(self) -> None:
        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            client = OllamaClient("llama3.2")
            assert client.is_available() is False

    def test_never_raises(self) -> None:
        with patch("httpx.get", side_effect=RuntimeError("unexpected")):
            client = OllamaClient("llama3.2")
            # Must not propagate
            result = client.is_available()
            assert result is False


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

class TestComplete:
    def test_returns_llm_response(self) -> None:
        mock_resp = _make_chat_response("The dragon attacks.")
        with patch("httpx.post", return_value=mock_resp):
            client = OllamaClient("llama3.2")
            result = client.complete([{"role": "user", "content": "attack"}])
        assert isinstance(result, LLMResponse)
        assert result.narrative_text == "The dragon attacks."
        assert result.tool_call is None
        assert result.finish_reason == "stop"

    def test_correct_request_body(self) -> None:
        mock_resp = _make_chat_response("ok")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client = OllamaClient("mistral", base_url="http://localhost:11434")
            client.complete([{"role": "user", "content": "hi"}], temperature=0.8, top_p=0.9)
        call_kwargs = mock_post.call_args
        sent_payload = call_kwargs.kwargs["json"]
        assert sent_payload["model"] == "mistral"
        assert sent_payload["stream"] is False
        assert sent_payload["messages"][0]["content"] == "hi"
        assert sent_payload["options"]["temperature"] == 0.8
        assert sent_payload["options"]["top_p"] == 0.9

    def test_extracts_tool_call(self) -> None:
        content = (
            "The knight falls.\n"
            "~~~json\n"
            '{"state_changes": [{"entity_id": "knight", "stat_key": "HP", "delta": -20}]}\n'
            "~~~"
        )
        mock_resp = _make_chat_response(content)
        with patch("httpx.post", return_value=mock_resp):
            client = OllamaClient("llama3.2")
            result = client.complete([])
        assert result.tool_call is not None
        assert result.tool_call["state_changes"][0]["delta"] == -20
        assert "~~~json" not in result.narrative_text

    def test_finish_reason_length_when_not_done(self) -> None:
        mock_resp = _make_chat_response("truncated", done=False)
        with patch("httpx.post", return_value=mock_resp):
            client = OllamaClient("llama3.2")
            result = client.complete([])
        assert result.finish_reason == "length"

    def test_raises_connection_error_on_connect_refused(self) -> None:
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            client = OllamaClient("llama3.2")
            with pytest.raises(LLMConnectionError, match="Cannot connect"):
                client.complete([])

    def test_raises_connection_error_on_timeout(self) -> None:
        with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
            client = OllamaClient("llama3.2")
            with pytest.raises(LLMConnectionError, match="timed out"):
                client.complete([])

    def test_raises_connection_error_on_server_500(self) -> None:
        mock_resp = _make_chat_response("err", status=500)
        with patch("httpx.post", return_value=mock_resp):
            client = OllamaClient("llama3.2")
            with pytest.raises(LLMConnectionError, match="server error"):
                client.complete([])

    def test_raises_parse_error_on_invalid_json_response(self) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        with patch("httpx.post", return_value=mock_resp):
            client = OllamaClient("llama3.2")
            with pytest.raises(LLMParseError):
                client.complete([])

    def test_raises_parse_error_on_missing_message_key(self) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"done": True}  # no "message" key
        with patch("httpx.post", return_value=mock_resp):
            client = OllamaClient("llama3.2")
            with pytest.raises(LLMParseError):
                client.complete([])

    def test_custom_base_url_used(self) -> None:
        mock_resp = _make_chat_response("ok")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client = OllamaClient("llama3.2", base_url="http://192.168.1.5:11434")
            client.complete([])
        url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url", "")
        # The URL is the first positional argument
        called_url = mock_post.call_args[0][0] if mock_post.call_args[0] else mock_post.call_args[1].get("url","")
        assert "192.168.1.5" in called_url


# ---------------------------------------------------------------------------
# stream_tokens
# ---------------------------------------------------------------------------

class TestStreamTokens:
    def _mock_stream_context(self, lines: list[str], status: int = 200):
        """Return a mock context manager for httpx.stream()."""
        mock_response = MagicMock()
        mock_response.status_code = status
        mock_response.iter_lines.return_value = iter(lines)
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_response)
        mock_context.__exit__ = MagicMock(return_value=False)
        return mock_context

    def test_yields_tokens_in_order(self) -> None:
        lines = _ndjson_lines(["Hello", " world", "!"])
        with patch("httpx.stream", return_value=self._mock_stream_context(lines)):
            client = OllamaClient("llama3.2")
            tokens = list(client.stream_tokens([]))
        assert tokens == ["Hello", " world", "!"]

    def test_stops_at_done_true(self) -> None:
        # Provide extra lines after done=True — they must be ignored
        lines = [
            json.dumps({"message": {"content": "A"}, "done": False}),
            json.dumps({"message": {"content": "B"}, "done": True}),
            json.dumps({"message": {"content": "C"}, "done": False}),  # must not appear
        ]
        with patch("httpx.stream", return_value=self._mock_stream_context(lines)):
            client = OllamaClient("llama3.2")
            tokens = list(client.stream_tokens([]))
        assert tokens == ["A", "B"]

    def test_skips_empty_lines(self) -> None:
        lines = ["", _ndjson_lines(["X"])[0]]
        with patch("httpx.stream", return_value=self._mock_stream_context(lines)):
            client = OllamaClient("llama3.2")
            tokens = list(client.stream_tokens([]))
        assert "X" in tokens

    def test_raises_connection_error_on_connect_refused(self) -> None:
        with patch("httpx.stream", side_effect=httpx.ConnectError("refused")):
            client = OllamaClient("llama3.2")
            with pytest.raises(LLMConnectionError):
                list(client.stream_tokens([]))

    def test_raises_connection_error_on_server_500(self) -> None:
        with patch("httpx.stream", return_value=self._mock_stream_context([], status=500)):
            client = OllamaClient("llama3.2")
            with pytest.raises(LLMConnectionError, match="server error"):
                list(client.stream_tokens([]))
