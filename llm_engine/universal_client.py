"""
llm_engine/universal_client.py

Universal OpenAI-compatible API client for Axiom AI.
Supports any local/remote backend that implements the OpenAI /v1/chat/completions API
(e.g., LM Studio, KoboldCPP, Ollama, standard OpenAI, etc.).
"""

from __future__ import annotations

import json
from typing import Iterator

import httpx

from llm_engine.base import LLMBackend, LLMConnectionError, LLMMessage, LLMResponse

_DEFAULT_TIMEOUT: float = 600.0


class UniversalClient(LLMBackend):
    """OpenAI-compatible LLM client using httpx.

    Args:
        base_url:   The base URL (e.g., http://localhost:1234/v1).
        api_key:    Optional API key for authorization.
        model_name: The model identifier to request.
    """

    def __init__(self, base_url: str, api_key: str, model_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=_DEFAULT_TIMEOUT
        )

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_payload(self, messages: list[LLMMessage], stream: bool, temperature: float = 0.7, top_p: float = 1.0, response_format: str | None = None, stop_sequences: list[str] | None = None, max_tokens: int | None = None) -> dict:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens if max_tokens else 1024,
        }
        
        # Merge stop sequences
        stops = ["~~~", "</s>", "<|im_end|>", "\n===", "\n###", "\nUser:", "\nPlayer:", "\n[User]"]
        if stop_sequences:
            stops.extend(stop_sequences)
        payload["stop"] = list(dict.fromkeys(stops))

        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        return payload

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
        """Send a list of messages and return a fully assembled LLMResponse."""
        payload = self._get_payload(messages, stream=False, temperature=temperature, top_p=top_p, response_format=response_format, stop_sequences=stop_sequences, max_tokens=max_tokens)

        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            
            raw_text = data["choices"][0]["message"]["content"]
            reason = data["choices"][0].get("finish_reason", "stop")

            narrative, tool_call = self.parse_tool_call(raw_text)
            return LLMResponse(
                narrative_text=narrative,
                tool_call=tool_call,
                finish_reason=reason,
            )
        except httpx.HTTPError as exc:
            raise LLMConnectionError(f"Universal API unreachable: {exc}") from exc
        except (KeyError, json.JSONDecodeError) as exc:
            raise LLMConnectionError(f"Unexpected response format: {exc}") from exc

    def stream_tokens(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        top_p: float = 1.0,
        response_format: str | None = None,
        stop_sequences: list[str] | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """Yield individual tokens as they arrive via SSE."""
        payload = self._get_payload(messages, stream=True, temperature=temperature, top_p=top_p, response_format=response_format, stop_sequences=stop_sequences, max_tokens=max_tokens)

        try:
            with self._client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[len("data: "):]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except httpx.HTTPError as exc:
            raise LLMConnectionError(f"Universal API streaming error: {exc}") from exc

    def is_available(self) -> bool:
        """Check if the backend is reachable."""
        try:
            response = self._client.get("/models", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
