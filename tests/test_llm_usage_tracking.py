"""Tests for LLM token aggregation and tracking wrapper."""

from __future__ import annotations

from browser_agent.llm.provider import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    FakeLLMProvider,
    TrackingLLMProvider,
    extract_openai_usage,
    merge_usage_counts,
)
from browser_agent.runtime.models import LLMUsageTotals


def test_merge_usage_counts_prefers_api_numbers() -> None:
    msgs = [LLMMessage(role="user", content="hello")]
    pt, ct, tt, approx = merge_usage_counts(msgs, "{}", 10, 5, None)
    assert (pt, ct, tt) == (10, 5, 15)
    assert approx is False


def test_merge_usage_counts_estimates_when_missing() -> None:
    msgs = [LLMMessage(role="user", content="x" * 40)]
    pt, ct, tt, approx = merge_usage_counts(msgs, "y" * 40, None, None, None)
    assert approx is True
    assert pt >= 1 and ct >= 1 and tt == pt + ct


def test_extract_openai_usage_reads_payload() -> None:
    payload = {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
    assert extract_openai_usage(payload) == (3, 2, 5)


def test_tracking_llm_provider_accumulates() -> None:
    totals = LLMUsageTotals()
    inner = FakeLLMProvider([LLMResponse(content='{"decision_type":"fail"}')])
    tracker = TrackingLLMProvider(inner, totals)
    tracker.complete(
        LLMRequest(messages=[LLMMessage(role="user", content="abc")])
    )
    assert totals.request_count == 1
    assert totals.cumulative_total_tokens > 0
