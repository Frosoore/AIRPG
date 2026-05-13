"""
llm_engine/base.py

Abstract base class and shared data types for all Axiom AI LLM backends.

Both the Arbitrator (narrative agent) and the Chronicler (world simulation
agent) are decoupled from any concrete LLM provider through this interface.
Swapping between a local Ollama model and a remote Gemini model requires only
changing which concrete subclass is instantiated.

Tool Call Protocol
------------------
The LLM is instructed to wrap any structured state-change JSON inside a
fenced block delimited by ~~~json / ~~~ markers.  This delimiter was chosen
deliberately to avoid ambiguity with standard markdown ``` code fences that
may appear legitimately in narrative prose.

Example LLM output:

    The dragon breathes fire.  The knight loses his shield.

    ~~~json
    {
        "state_changes": [
            {"entity_id": "knight", "stat_key": "Shield", "delta": -1}
        ],
        "narrative_events": ["dragon_attack"]
    }
    ~~~
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, TypedDict, NotRequired


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

class LLMMessage(TypedDict):
    """A single message in an LLM conversation.

    Attributes:
        role:    'system', 'user', or 'assistant'.
        content: The text payload.
        name:    Optional identifier for the speaker (e.g. entity_id).
    """
    role: str
    content: str
    name: NotRequired[str]


@dataclass
class LLMResponse:
    """Parsed response from any LLM backend.

    Attributes:
        narrative_text: The prose portion of the response, with the
                        ~~~json … ~~~ block stripped out.
        tool_call:      The parsed JSON object or list from the fenced block, 
                        or None if the LLM produced no tool call.
        finish_reason:  One of "stop", "length", or "error".
    """
    narrative_text: str
    tool_call: dict | list | None
    finish_reason: str


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class LLMConnectionError(Exception):
    """Raised when the LLM backend is unreachable.

    This covers connection refused, DNS failures, timeouts, and HTTP 5xx
    responses that indicate the server is down.
    """


class LLMParseError(Exception):
    """Raised when the LLM response cannot be parsed into the expected structure.

    This covers malformed JSON inside the ~~~json block, missing required
    fields, or an entirely unexpected response format.
    """


# ---------------------------------------------------------------------------
# Regex patterns for the tool-call fence
# ---------------------------------------------------------------------------

_FENCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"~~~json\s*(.*?)\s*~~~", re.DOTALL),
    re.compile(r"```json\s*(.*?)\s*```", re.DOTALL),
    re.compile(r"~~~\s*(.*?)\s*~~~", re.DOTALL),
    re.compile(r"```\s*(.*?)\s*```", re.DOTALL),
]

# Fallback: find anything that looks like a JSON object at the end of the string
_JSON_OBJECT_PATTERN: re.Pattern[str] = re.compile(r"(\{.*\})", re.DOTALL)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class LLMBackend(ABC):
    """Abstract interface for all Axiom AI LLM provider clients.

    Concrete subclasses must implement complete(), stream_tokens(), and
    is_available().  The parse_tool_call() helper is provided here and is
    shared by all subclasses.
    """

    @abstractmethod
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
        """Send a list of messages and return a fully assembled LLMResponse.

        Args:
            messages:    Conversation history including the system prompt.
            stream:      If True, the implementation may still return a complete
                         LLMResponse (assembled from the stream internally);
                         for token-by-token streaming use stream_tokens().
            temperature: Sampling temperature (0.0 to 1.0).
            top_p:       Nucleus sampling parameter (0.0 to 1.0).
            response_format: Optional format constraint (e.g. "json").
            stop_sequences:  Optional list of strings that trigger generation stop.
            max_tokens:      Optional limit on the number of tokens to generate.

        Returns:
            Parsed LLMResponse with narrative_text, optional tool_call, and
            finish_reason.

        Raises:
            LLMConnectionError: If the backend is unreachable.
            LLMParseError: If the response structure is unrecognisable.
        """

    @abstractmethod
    def stream_tokens(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        top_p: float = 1.0,
        response_format: str | None = None,
        stop_sequences: list[str] | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """Yield individual tokens as they arrive from the LLM backend.

        Intended for the PySide6 typewriter UI effect (Phase 3).  The caller
        is responsible for accumulating tokens and calling parse_tool_call()
        on the assembled string when the stream ends.

        Args:
            messages:    Conversation history including the system prompt.
            temperature: Sampling temperature (0.0 to 1.0).
            top_p:       Nucleus sampling parameter (0.0 to 1.0).
            response_format: Optional format constraint (e.g. "json").
            stop_sequences:  Optional list of strings that trigger generation stop.
            max_tokens:      Optional limit on the number of tokens to generate.

        Yields:
            Individual token strings in the order they are produced.

        Raises:
            LLMConnectionError: If the backend becomes unreachable mid-stream.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Perform a lightweight health check against the backend.

        Must never raise; any failure must be caught and returned as False.

        Returns:
            True if the backend is reachable and ready, False otherwise.
        """

    # ------------------------------------------------------------------
    # Shared parsing logic (concrete, inherited by all subclasses)
    # ------------------------------------------------------------------

    @classmethod
    def parse_tool_call(cls, raw_response: str) -> tuple[str, dict | list | None]:
        """Extract narrative text and tool-call JSON from a raw LLM response.

        Resilient parsing:
        1. Checks for common markdown fences (~~~json, ```json, etc).
        2. Fallback: Heuristic search for JSON objects {...} or arrays [...].
        3. Normalizes minor schema deviations (e.g., missing 'stats' key or flat params).

        Args:
            raw_response: The complete raw string returned by the LLM.

        Returns:
            A tuple (narrative_text, tool_call) where:
            - narrative_text is the response with the JSON block removed.
            - tool_call is the parsed dict/list, or None if no valid JSON was found.
        """
        # 1. Try fenced blocks first (prioritize ~~~json as per spec)
        for pattern in _FENCE_PATTERNS:
            match = pattern.search(raw_response)
            if match:
                json_str = match.group(1).strip()
                narrative = pattern.sub("", raw_response).strip()
                try:
                    data = json.loads(json_str)
                    return narrative, cls._normalize_json(data)
                except json.JSONDecodeError as exc:
                    raise LLMParseError(f"Failed to parse tool-call JSON block: {exc}") from exc

        # 2. Fallback: Heuristic search for largest JSON-looking block
        # Support both objects {...} and arrays [...]
        json_pattern = re.compile(r"([\{\[].*[\}\]])", re.DOTALL)
        match = json_pattern.search(raw_response)
        if match:
            json_str = match.group(1).strip()
            start_idx = raw_response.find(json_str)
            end_idx = start_idx + len(json_str)
            narrative = (raw_response[:start_idx] + raw_response[end_idx:]).strip()
            try:
                data = json.loads(json_str)
                return narrative, cls._normalize_json(data)
            except json.JSONDecodeError:
                pass

        return raw_response.strip(), None

    @classmethod
    def _normalize_json(cls, data: Any) -> dict | list | None:
        """Heuristically fix common LLM deviations from requested schemas."""
        if isinstance(data, list):
            # If they gave a list directly (common in 'populate stats'), we normalize items
            return [cls._normalize_item(i) for i in data]
        
        if isinstance(data, dict):
            # If they wrapped it in 'stats', 'entities', etc., normalize the contents
            for key in ["stats", "entities", "rules", "lore_book", "scheduled_events"]:
                if key in data and isinstance(data[key], list):
                    data[key] = [cls._normalize_item(i) for i in data[key]]
            return data
            
        return data

    @classmethod
    def _normalize_item(cls, item: Any) -> Any:
        """Fix a single stat/entity/rule item."""
        if not isinstance(item, dict):
            return item
            
        # Fix categorical stats where parameters is a list instead of {"options": [...]}
        # Log showed: "parameters": ["Villager", "Adventurer", ...]
        if item.get("value_type") == "categorical":
            params = item.get("parameters")
            if isinstance(params, list):
                item["parameters"] = {"options": params}
        
        return item
