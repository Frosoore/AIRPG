"""
llm_engine/gemini_client.py

LLM backend client for Google Gemini models (remote / cloud fallback).

Uses the google-genai SDK (google.genai).  The client translates Axiom AI's
internal list[LLMMessage] format to Gemini's Content objects: the first
system-role message becomes the model's system_instruction, and the
remaining turns become the contents list.

Typical usage
-------------
    from llm_engine.gemini_client import GeminiClient

    llm = GeminiClient(api_key="YOUR_KEY", model_name="gemini-2.0-flash")
    if llm.is_available():
        response = llm.complete(messages)
        print(response.narrative_text)
"""

from typing import Iterator

from google import genai
from google.genai import types as genai_types

from llm_engine.base import (
    LLMBackend,
    LLMConnectionError,
    LLMMessage,
    LLMParseError,
    LLMResponse,
)

_DEFAULT_MODEL: str = "gemini-2.0-flash"


class GeminiClient(LLMBackend):
    """LLM backend targeting Google Gemini via the google-genai SDK.

    Args:
        api_key:    Google Generative AI API key.
        model_name: Gemini model identifier.
                    Defaults to "gemini-2.0-flash".
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = _DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check whether the Gemini API is reachable with the configured key.

        Attempts to list available models.  Returns True on success, False
        on any exception.  Never raises.

        Returns:
            True if the API responds without error, False otherwise.
        """
        try:
            # A lightweight list call — verifies connectivity and auth
            list(self._client.models.list())
            return True
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
        """Send messages to Gemini and return a parsed LLMResponse.

        Translates list[LLMMessage] into Gemini format:
        - The first message with role="system" becomes system_instruction.
        - Remaining messages map user/assistant → user/model roles.

        Args:
            messages:    Conversation turns (system, user, assistant).
            stream:      Ignored; use stream_tokens() for token streaming.
            temperature: Sampling temperature (0.0 to 1.0).
            top_p:       Nucleus sampling parameter (0.0 to 1.0).
            response_format: Currently unused for Gemini.
            stop_sequences:  Custom strings to trigger generation stop.
            max_tokens:      Optional limit on the number of tokens to generate.

        Returns:
            LLMResponse with narrative_text, optional tool_call, finish_reason.

        Raises:
            LLMConnectionError: On network failure or API error.
            LLMParseError: On unexpected response structure or bad tool-call JSON.
        """
        system_instruction, contents = self._translate_messages(messages)

        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_tokens if max_tokens else 1024,
            stop_sequences=stop_sequences,
        )

        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            raise LLMConnectionError(
                f"Gemini API error ({type(exc).__name__}): {exc}"
            ) from exc

        try:
            raw_content: str = response.text
        except (AttributeError, ValueError) as exc:
            raise LLMParseError(
                f"Cannot extract text from Gemini response: {exc}"
            ) from exc

        if raw_content is None:
            raise LLMParseError("Gemini response returned None text.")

        finish_reason = self._extract_finish_reason(response)
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
        """Yield tokens from a streaming Gemini response.

        Args:
            messages:    Conversation turns (system, user, assistant).
            temperature: Sampling temperature (0.0 to 1.0).
            top_p:       Nucleus sampling parameter (0.0 to 1.0).
            response_format: Currently unused for Gemini.
            stop_sequences:  Custom strings to trigger generation stop.
            max_tokens:      Optional limit on the number of tokens to generate.

        Yields:
            Individual token strings in arrival order.

        Raises:
            LLMConnectionError: On network failure.
        """
        system_instruction, contents = self._translate_messages(messages)

        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_tokens if max_tokens else 1024,
            stop_sequences=stop_sequences,
        )

        try:
            for chunk in self._client.models.generate_content_stream(
                model=self._model_name,
                contents=contents,
                config=config,
            ):
                try:
                    text = chunk.text
                    if text:
                        yield text
                except (AttributeError, ValueError):
                    # Empty or safety-blocked chunk — skip silently
                    continue
        except LLMConnectionError:
            raise
        except Exception as exc:
            raise LLMConnectionError(
                f"Gemini stream error ({type(exc).__name__}): {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _translate_messages(
        messages: list[LLMMessage],
    ) -> tuple[str | None, list[genai_types.ContentDict]]:
        """Translate list[LLMMessage] into (system_instruction, contents).

        The first message with role='system' is extracted as system_instruction.
        Remaining messages are mapped: user→user, assistant→model.
        Additional system messages after the first are folded into the user
        turn that follows them as a prefixed block.

        Args:
            messages: Axiom AI internal message list.

        Returns:
            Tuple of (system_instruction_str_or_None, gemini_contents_list).
        """
        system_instruction: str | None = None
        contents: list[dict] = []
        pending_system_injections: list[str] = []

        for msg in messages:
            role: str = msg["role"]
            content: str = msg["content"]

            if role == "system":
                if system_instruction is None:
                    system_instruction = content
                else:
                    pending_system_injections.append(content)
            elif role == "user":
                if pending_system_injections:
                    injection = "\n".join(
                        f"[SYSTEM: {s}]" for s in pending_system_injections
                    )
                    content = f"{injection}\n\n{content}"
                    pending_system_injections = []
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})

        return system_instruction, contents

    @staticmethod
    def _extract_finish_reason(response: object) -> str:
        """Extract a normalised finish_reason string from a Gemini response.

        Args:
            response: The GenerateContentResponse object.

        Returns:
            "stop", "length", or "error".
        """
        try:
            candidates = response.candidates  # type: ignore[attr-defined]
            if not candidates:
                return "error"
            finish = candidates[0].finish_reason
            # FinishReason: STOP=1, MAX_TOKENS=2, others treated as stop
            finish_str = str(finish).upper() if finish else ""
            if "MAX_TOKENS" in finish_str or finish_str == "2":
                return "length"
            return "stop"
        except Exception:
            return "stop"
