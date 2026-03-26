"""Tests for planner HTTP transport retries and error messages."""

from __future__ import annotations

import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from browser_agent.llm.provider import (
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    OpenAICompatibleProvider,
)


def _minimal_openai_response(content: str) -> bytes:
    payload = {
        "model": "test-model",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return json.dumps(payload).encode("utf-8")


def test_openai_provider_retries_on_transient_timeout() -> None:
    """Transient read timeouts are retried before succeeding."""

    call_count = {"n": 0}

    def fake_urlopen(*_args: object, **_kwargs: object) -> MagicMock:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise socket.timeout("The read operation timed out")
        resp = MagicMock()
        resp.read.return_value = _minimal_openai_response("{}")
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *_a: None
        return resp

    provider = OpenAICompatibleProvider(
        base_url="http://example.invalid/v1",
        model_name="m",
        max_retries=3,
        retry_backoff_seconds=0.001,
        timeout_seconds=5.0,
    )
    req = LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        response_format=None,
    )

    with patch("browser_agent.llm.provider.request.urlopen", side_effect=fake_urlopen):
        out = provider.complete(req)

    assert call_count["n"] == 3
    assert out.content == "{}"


def test_openai_provider_raises_after_retry_exhaustion() -> None:
    """After all attempts fail with timeout, raise LLMProviderError with hint."""

    def always_timeout(*_args: object, **_kwargs: object) -> None:
        raise socket.timeout("The read operation timed out")

    provider = OpenAICompatibleProvider(
        base_url="http://example.invalid/v1",
        model_name="m",
        max_retries=1,
        retry_backoff_seconds=0.001,
        timeout_seconds=2.0,
    )
    req = LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        response_format=None,
    )

    with patch("browser_agent.llm.provider.request.urlopen", side_effect=always_timeout):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.complete(req)

    msg = str(exc_info.value)
    assert "timed out" in msg.lower()
    assert "attempt" in msg.lower()
    assert "BROWSER_AGENT_PLANNER_TIMEOUT_SECONDS" in msg
