"""Minimal LLM provider abstractions used by the structured planner."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any, Literal, Protocol
from urllib import error, parse, request

from pydantic import BaseModel, Field

from browser_agent.runtime.models import LLMUsageTotals


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
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    usage_approximate: bool = False


def _coerce_non_negative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return None


def extract_openai_usage(
    payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None, None
    pt = _coerce_non_negative_int(usage.get("prompt_tokens"))
    ct = _coerce_non_negative_int(usage.get("completion_tokens"))
    tt = _coerce_non_negative_int(usage.get("total_tokens"))
    if tt is None and pt is not None and ct is not None:
        tt = pt + ct
    return pt, ct, tt


def extract_gemini_usage(
    payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None]:
    um = payload.get("usageMetadata")
    if not isinstance(um, dict):
        return None, None, None
    pt = _coerce_non_negative_int(um.get("promptTokenCount"))
    ct = _coerce_non_negative_int(um.get("candidatesTokenCount"))
    tt = _coerce_non_negative_int(um.get("totalTokenCount"))
    if tt is None and pt is not None and ct is not None:
        tt = pt + ct
    return pt, ct, tt


def estimate_usage_tokens(
    messages: list[LLMMessage],
    content: str,
) -> tuple[int, int, int]:
    """Very rough token estimate (~4 chars/token) when the API omits usage."""
    prompt_chars = sum(len(m.content) for m in messages)
    completion_chars = len(content)
    pt = max(1, prompt_chars // 4)
    ct = max(1, completion_chars // 4)
    return pt, ct, pt + ct


def merge_usage_counts(
    messages: list[LLMMessage],
    content: str,
    pt: int | None,
    ct: int | None,
    tt: int | None,
) -> tuple[int, int, int, bool]:
    """Return (prompt, completion, total, approximate)."""
    ept, ect, ett = estimate_usage_tokens(messages, content)
    if pt is not None and ct is not None:
        final_tt = tt if tt is not None else pt + ct
        return pt, ct, final_tt, False
    if pt is None and ct is None and tt is None:
        return ept, ect, ett, True
    pt_f = pt if pt is not None else ept
    ct_f = ct if ct is not None else ect
    tt_f = tt if tt is not None else pt_f + ct_f
    return pt_f, ct_f, tt_f, True


class TrackingLLMProvider:
    """Wrap a provider to measure latency and accumulate usage into a session totals object."""

    def __init__(self, inner: LLMProvider, totals: LLMUsageTotals) -> None:
        self._inner = inner
        self._totals = totals

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        started = perf_counter()
        response = self._inner.complete(llm_request)
        latency_ms = (perf_counter() - started) * 1000
        response = response.model_copy(update={"latency_ms": response.latency_ms or latency_ms})
        pt, ct, tt, approx = merge_usage_counts(
            llm_request.messages,
            response.content,
            response.prompt_tokens,
            response.completion_tokens,
            response.total_tokens,
        )
        response = response.model_copy(
            update={
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": tt,
                "usage_approximate": response.usage_approximate or approx,
            }
        )
        self._totals.add_request(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            approximate=response.usage_approximate,
            latency_ms=response.latency_ms,
            model_name=response.model_name,
        )
        return response


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
        api_pt, api_ct, api_tt = extract_openai_usage(response_payload)
        pt, ct, tt, approx = merge_usage_counts(
            llm_request.messages,
            content,
            api_pt,
            api_ct,
            api_tt,
        )
        return LLMResponse(
            content=content,
            raw_payload=response_payload,
            model_name=response_payload.get("model"),
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            usage_approximate=approx,
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


class GoogleGenerativeLanguageProvider:
    """Google AI Gemini `generateContent` REST adapter (not OpenAI-compatible)."""

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

    def endpoint(self) -> str:
        if ":generateContent" in self.base_url:
            return self._append_api_key(self.base_url)
        return self._append_api_key(
            f"{self.base_url}/models/{self.model_name}:generateContent"
        )

    def _append_api_key(self, url: str) -> str:
        if not self.api_key:
            return url
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}{parse.urlencode({'key': self.api_key})}"

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []
        for message in llm_request.messages:
            if message.role == "system":
                system_parts.append({"text": message.content})
                continue
            gemini_role = "model" if message.role == "assistant" else "user"
            contents.append(
                {
                    "role": gemini_role,
                    "parts": [{"text": message.content}],
                }
            )

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature},
        }
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}

        if llm_request.response_format is not None:
            rf = llm_request.response_format
            if isinstance(rf, dict) and rf.get("type") == "json_object":
                body["generationConfig"]["responseMimeType"] = "application/json"

        payload_bytes = json.dumps(body).encode("utf-8")
        http_request = request.Request(
            self.endpoint(),
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
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
        api_pt, api_ct, api_tt = extract_gemini_usage(response_payload)
        pt, ct, tt, approx = merge_usage_counts(
            llm_request.messages,
            content,
            api_pt,
            api_ct,
            api_tt,
        )
        return LLMResponse(
            content=content,
            raw_payload=response_payload,
            model_name=self.model_name,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            usage_approximate=approx,
        )

    def _extract_content(self, payload: dict[str, Any]) -> str:
        feedback = payload.get("promptFeedback")
        if isinstance(feedback, dict):
            block = feedback.get("blockReason")
            if block:
                raise LLMProviderError(
                    f"Gemini blocked the prompt: {block} ({feedback!r})"
                )

        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise LLMProviderError(
                "Gemini response did not include candidates."
            )

        first = candidates[0]
        if not isinstance(first, dict):
            raise LLMProviderError("Gemini returned an invalid candidate.")

        content_obj = first.get("content")
        if not isinstance(content_obj, dict):
            raise LLMProviderError("Gemini response is missing content.")

        parts = content_obj.get("parts")
        if not isinstance(parts, list) or not parts:
            raise LLMProviderError("Gemini response did not include content parts.")

        first_part = parts[0]
        if not isinstance(first_part, dict):
            raise LLMProviderError("Gemini returned an invalid content part.")

        text = first_part.get("text")
        if isinstance(text, str) and text.strip():
            return text

        raise LLMProviderError(
            "Gemini response did not include assistant text content."
        )
