"""
llm_engine/ollama_client.py

LLM backend client for locally running Ollama instances.

Ollama exposes an OpenAI-compatible REST API.  This client targets the
/api/chat endpoint for multi-turn conversation and /api/tags for the
health check.  Both streaming and non-streaming modes are supported.

Typical usage
-------------
    from llm_engine.ollama_client import OllamaClient

    llm = OllamaClient(base_url="http://localhost:11434", model_name="llama3.2")
    if llm.is_available():
        response = llm.complete(messages)
        print(response.narrative_text)
"""

import json
from typing import Iterator

import httpx

from llm_engine.base import (
    LLMBackend,
    LLMConnectionError,
    LLMMessage,
    LLMParseError,
    LLMResponse,
)

_DEFAULT_BASE_URL: str = "http://localhost:11434"
_REQUEST_TIMEOUT: float = 600.0  # seconds


class OllamaClient(LLMBackend):
    """LLM backend targeting a locally running Ollama server.

    Args:
        base_url:   Base URL of the Ollama HTTP API.
                    Defaults to "http://localhost:11434".
        model_name: Name of the Ollama model to use (e.g. "llama3.2").
    """

    def __init__(
        self,
        model_name: str,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check whether the Ollama server is running and reachable.

        GETs /api/tags.  Returns True on HTTP 200, False on any exception.
        Never raises.

        Returns:
            True if the server responds with HTTP 200, False otherwise.
        """
        try:
            response = httpx.get(
                f"{self._base_url}/api/tags",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False

    def complete(
        self,
        messages: list[LLMMessage],
        stream: bool = False,
        temperature: float = 0.7,
        top_p: float = 1.0,
        response_format: str | None = None,
        stop_sequences: list[str] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send messages to Ollama's /api/chat and return a parsed LLMResponse.

        Args:
            messages:    Conversation turns (system, user, assistant).
            stream:      Ignored here; use stream_tokens() for token streaming.
            temperature: Sampling temperature (0.0 to 1.0).
            top_p:       Nucleus sampling parameter (0.0 to 1.0).
            response_format: If "json", forces Ollama to return a JSON object.
            stop_sequences:  Custom strings to trigger generation stop.
            max_tokens:      Optional limit on the number of tokens to generate.

        Returns:
            LLMResponse with narrative_text, optional tool_call, finish_reason.

        Raises:
            LLMConnectionError: On connection refused, timeout, or HTTP 5xx.
            LLMParseError: On malformed response JSON or invalid tool-call block.
        """
        # Phase 11: Mandatory stop sequences to prevent impersonation
        mandatory_stop = ["~~~", "</s>", "<|im_end|>", "<|eot_id|>", "\nUser:", "\nPlayer:", "\n[User]", "\nAssistant:", "\n==="]
        if stop_sequences:
            mandatory_stop.extend(stop_sequences)
        
        # Remove duplicates while preserving order
        final_stop = list(dict.fromkeys(mandatory_stop))

        payload = {
            "model": self._model_name,
            "messages": list(messages),
            "stream": False,
            "options": {
                "num_ctx": 8192,
                "stop": final_stop,
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_tokens if max_tokens else 1024,
            }
        }
        
        if response_format == "json":
            payload["format"] = "json"

        try:
            response = httpx.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Cannot connect to Ollama at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMConnectionError(
                f"Ollama request timed out after {_REQUEST_TIMEOUT}s: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMConnectionError(
                f"Ollama HTTP error: {exc}"
            ) from exc

        if response.status_code >= 500:
            raise LLMConnectionError(
                f"Ollama server error: HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except Exception as exc:
            raise LLMParseError(
                f"Ollama response is not valid JSON: {exc}"
            ) from exc

        try:
            raw_content: str = body["message"]["content"]
            finish_reason: str = "stop" if body.get("done", True) else "length"
        except (KeyError, TypeError) as exc:
            raise LLMParseError(
                f"Unexpected Ollama response structure: {exc}\nBody: {body}"
            ) from exc

        narrative, tool_call = self.parse_tool_call(raw_content)
        return LLMResponse(
            narrative_text=narrative,
            tool_call=tool_call,
            finish_reason=finish_reason,
        )

    def stream_tokens(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        top_p: float = 1.0,
        response_format: str | None = None,
        stop_sequences: list[str] | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """Yield tokens from Ollama's streaming NDJSON response.

        POSTs to /api/chat with stream=true and yields each content token
        as it arrives.

        Args:
            messages:    Conversation turns (system, user, assistant).
            temperature: Sampling temperature (0.0 to 1.0).
            top_p:       Nucleus sampling parameter (0.0 to 1.0).
            response_format: If "json", forces Ollama to return a JSON object.
            stop_sequences:  Custom strings to trigger generation stop.
            max_tokens:      Optional limit on the number of tokens to generate.

        Yields:
            Individual token strings in arrival order.

        Raises:
            LLMConnectionError: On connection failure or HTTP 5xx.
        """
        # Phase 11: Mandatory stop sequences to prevent impersonation
        mandatory_stop = ["~~~", "</s>", "<|im_end|>", "<|eot_id|>", "\nUser:", "\nPlayer:", "\n[User]", "\nAssistant:", "\n==="]
        if stop_sequences:
            mandatory_stop.extend(stop_sequences)
        
        # Remove duplicates while preserving order
        final_stop = list(dict.fromkeys(mandatory_stop))

        payload = {
            "model": self._model_name,
            "messages": list(messages),
            "stream": True,
            "options": {
                "num_ctx": 8192,
                "stop": final_stop,
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_tokens if max_tokens else 1024,
            }
        }
        
        if response_format == "json":
            payload["format"] = "json"

        try:
            with httpx.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status_code >= 500:
                    raise LLMConnectionError(
                        f"Ollama server error during stream: HTTP {response.status_code}"
                    )
                for line in response.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if chunk.get("done", False):
                        break

        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Cannot connect to Ollama at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMConnectionError(
                f"Ollama stream timed out: {exc}"
            ) from exc
        except LLMConnectionError:
            raise
        except httpx.HTTPError as exc:
            raise LLMConnectionError(
                f"Ollama HTTP error during stream: {exc}"
            ) from exc
