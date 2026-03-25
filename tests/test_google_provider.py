"""Unit tests for GoogleGenerativeLanguageProvider."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from browser_agent.llm.provider import (
    GoogleGenerativeLanguageProvider,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
)


def _make_context_manager_mock(body_bytes: bytes) -> MagicMock:
    """Return a mock that works as a context manager for urlopen."""

    mock_response = MagicMock()
    mock_response.read.return_value = body_bytes
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_response)
    mock_cm.__exit__ = MagicMock(return_value=False)
    return mock_cm


def test_google_provider_builds_endpoint_from_host() -> None:
    """URL built as {base_url}/models/{model}:generateContent?key={api_key}"""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model_name="gemini-flash-latest",
        api_key="AIzaTestKey",
    )
    assert provider.endpoint() == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-flash-latest:generateContent?key=AIzaTestKey"
    )


def test_google_provider_uses_full_url_if_contains_generatecontent() -> None:
    """If BASE_URL already includes :generateContent, use as-is."""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://example.com/v1/models/mymodel:generateContent",
        model_name="ignored-when-full-url",
        api_key="K",
    )
    assert provider.endpoint() == (
        "https://example.com/v1/models/mymodel:generateContent?key=K"
    )


def test_google_provider_no_api_key_omits_query_param() -> None:
    """Without key, URL has no ?key=..."""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://genai.example.com/v1",
        model_name="m",
        api_key=None,
    )
    assert provider.endpoint() == "https://genai.example.com/v1/models/m:generateContent"


def test_google_provider_request_body_structure() -> None:
    """Request maps messages to contents and systemInstruction correctly."""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://genai.example.com/v1",
        model_name="m",
        api_key="k",
        temperature=0.5,
    )

    llm_request = LLMRequest(
        messages=[
            LLMMessage(role="system", content="You are a planner."),
            LLMMessage(role="user", content="Observe the page."),
            LLMMessage(role="assistant", content="I see a button."),
        ],
        response_format={"type": "json_object"},
    )

    captured_body: dict | None = None

    def fake_urlopen(request, **_kwargs):
        nonlocal captured_body
        captured_body = json.loads(request.data.decode("utf-8"))
        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": '{"decision": "act"}'}],
                        }
                    }
                ]
            }
        ).encode("utf-8")
        return _make_context_manager_mock(body)

    with patch("browser_agent.llm.provider.request.urlopen", fake_urlopen):
        provider.complete(llm_request)

    assert captured_body is not None
    assert captured_body["generationConfig"]["temperature"] == 0.5
    assert captured_body["generationConfig"].get("responseMimeType") == "application/json"
    assert captured_body["systemInstruction"] == {"parts": [{"text": "You are a planner."}]}
    assert captured_body["contents"] == [
        {"role": "user", "parts": [{"text": "Observe the page."}]},
        {"role": "model", "parts": [{"text": "I see a button."}]},
    ]


def test_google_provider_extracts_text_from_candidates() -> None:
    """Happy path: extract text from candidates[0].content.parts[0].text"""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://genai.example.com/v1",
        model_name="m",
    )

    body = json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": '{"decision": "finish"}'}],
                    }
                }
            ]
        }
    ).encode("utf-8")
    mock_cm = _make_context_manager_mock(body)

    with patch("browser_agent.llm.provider.request.urlopen", return_value=mock_cm):
        result = provider.complete(
            LLMRequest(messages=[LLMMessage(role="user", content="hi")])
        )

    assert result.content == '{"decision": "finish"}'
    assert result.model_name == "m"


def test_google_provider_raises_on_blocked_prompt() -> None:
    """promptFeedback.blockReason triggers LLMProviderError."""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://genai.example.com/v1",
        model_name="m",
    )

    body = json.dumps(
        {
            "promptFeedback": {"blockReason": "SAFETY"},
            "candidates": [],
        }
    ).encode("utf-8")
    mock_cm = _make_context_manager_mock(body)

    with patch("browser_agent.llm.provider.request.urlopen", return_value=mock_cm):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.complete(LLMRequest(messages=[]))

    assert "SAFETY" in str(exc_info.value)


def test_google_provider_raises_on_empty_candidates() -> None:
    """Empty candidates list triggers LLMProviderError."""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://genai.example.com/v1",
        model_name="m",
    )

    body = json.dumps({"candidates": []}).encode("utf-8")
    mock_cm = _make_context_manager_mock(body)

    with patch("browser_agent.llm.provider.request.urlopen", return_value=mock_cm):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.complete(LLMRequest(messages=[]))

    assert "did not include candidates" in str(exc_info.value)


def test_google_provider_raises_on_missing_text() -> None:
    """If parts[0] has no text field, raise."""

    provider = GoogleGenerativeLanguageProvider(
        base_url="https://genai.example.com/v1",
        model_name="m",
    )

    body = json.dumps(
        {
            "candidates": [
                {"content": {"role": "model", "parts": [{"inlineData": {}}]}}
            ]
        }
    ).encode("utf-8")
    mock_cm = _make_context_manager_mock(body)

    with patch("browser_agent.llm.provider.request.urlopen", return_value=mock_cm):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.complete(LLMRequest(messages=[]))

    assert "did not include assistant text content" in str(exc_info.value)
