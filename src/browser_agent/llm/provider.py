"""Minimal LLM provider abstractions used by the structured planner."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol
from urllib import error, request

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """One chat-style message sent to the provider."""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """Provider-agnostic inference request for the planner."""

    messages: list[LLMMessage]
    response_format: dict[str, Any] | None = None


class LLMResponse(BaseModel):
    """Provider-agnostic inference response for the planner."""

    content: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    model_name: str | None = None


class LLMProviderError(RuntimeError):
    """Raised when the configured provider cannot return a usable response."""


class LLMProvider(Protocol):
    """Transport interface used by the planner layer."""

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        """Run one structured completion and return the assistant content."""


class FakeLLMProvider:
    """Queue-driven fake provider for planner tests."""

    def __init__(self, responses: list[str | LLMResponse]) -> None:
        self._responses = list(responses)

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        del llm_request
        if not self._responses:
            raise LLMProviderError("FakeLLMProvider has no queued responses.")
        response = self._responses.pop(0)
        if isinstance(response, LLMResponse):
            return response
        return LLMResponse(content=response)


class OpenAICompatibleProvider:
    """Very small OpenAI-compatible chat-completions adapter."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        temperature: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in llm_request.messages
            ],
            "temperature": self.temperature,
        }
        if llm_request.response_format is not None:
            payload["response_format"] = llm_request.response_format

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise LLMProviderError(
                f"Planner provider returned HTTP {exc.code}: {details}"
            ) from exc
        except error.URLError as exc:
            raise LLMProviderError(
                f"Planner provider is unavailable: {exc.reason}"
            ) from exc
        except Exception as exc:
            raise LLMProviderError(f"Planner provider request failed: {exc}") from exc

        try:
            response_payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                "Planner provider returned a non-JSON response payload."
            ) from exc

        content = self._extract_content(response_payload)
        return LLMResponse(
            content=content,
            raw_payload=response_payload,
            model_name=response_payload.get("model"),
        )

    def _extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMProviderError("Planner provider response did not include choices.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LLMProviderError("Planner provider returned an invalid choice payload.")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise LLMProviderError("Planner provider response is missing the message.")

        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            if parts:
                return "".join(parts)

        raise LLMProviderError(
            "Planner provider response did not include assistant text content."
        )
