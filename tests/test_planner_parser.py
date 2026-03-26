"""Tests for the structured planner parser and planner boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from browser_agent.llm.parser import PlannerResponseParser
from browser_agent.llm.planner import (
    LLMPlanner,
    PlannerContext,
    PlannerDecision,
    PlannerSessionState,
)
from browser_agent.llm.provider import LLMProviderError
from browser_agent.runtime.models import (
    RuntimeStatus,
    PlannerDecisionType,
    PlannerProgressState,
    UserTask,
)
from browser_agent.skills.registry import build_default_registry


class RaisingProvider:
    """Provider stub that always fails."""

    def complete(self, llm_request):
        del llm_request
        raise LLMProviderError("upstream unavailable")


def build_parser() -> PlannerResponseParser:
    return PlannerResponseParser(skill_registry=build_default_registry())


def test_parser_accepts_valid_structured_action_json() -> None:
    parser = build_parser()

    decision = parser.parse(
        """
        {
          "decision_type": "act",
          "rationale": "Navigate to the requested page first.",
          "chosen_skill": "navigate",
          "skill_input": {"url": "https://example.com", "wait_for": "load"},
          "expected_outcome": "The requested page loads successfully.",
          "risk_level": "low",
          "destructive": false,
          "completion_confidence": 0.6,
          "progress_assessment": "partial_progress",
          "requires_confirmation": false,
          "user_question": null,
          "finish_reason": null,
          "failure_reason": null
        }
        """
    )

    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.chosen_skill == "navigate"
    assert decision.skill_input["url"] == "https://example.com"


def test_parser_rejects_unregistered_skill_names() -> None:
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act",
            "rationale": "Use an imaginary tool.",
            "chosen_skill": "delete_spam_emails",
            "skill_input": {},
            "expected_outcome": "Magic happens.",
            "risk_level": "low",
            "destructive": False,
            "completion_confidence": 0.5,
            "progress_assessment": "unknown",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    assert decision.decision_type == PlannerDecisionType.FAIL
    assert "unregistered skill" in (decision.failure_reason or "")


def test_parser_rejects_invalid_skill_arguments() -> None:
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act",
            "rationale": "Navigate with the wrong argument shape.",
            "chosen_skill": "navigate",
            "skill_input": {"wait_for": "load"},
            "expected_outcome": "The page loads.",
            "risk_level": "low",
            "destructive": False,
            "completion_confidence": 0.5,
            "progress_assessment": "unknown",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    assert decision.decision_type == PlannerDecisionType.FAIL
    assert "skill schema" in (decision.failure_reason or "")


def test_parser_falls_back_to_safe_fail_for_malformed_json() -> None:
    parser = build_parser()

    decision = parser.parse("not json at all")

    assert decision.decision_type == PlannerDecisionType.FAIL
    assert "json" in (decision.failure_reason or "").lower()


def test_planner_decision_validation_rejects_invalid_finish_payload() -> None:
    with pytest.raises(ValidationError):
        PlannerDecision(
            decision_type=PlannerDecisionType.FINISH,
            rationale="Try to finish without a reason.",
            completion_confidence=0.9,
            progress_assessment=PlannerProgressState.SUBSTANTIAL_PROGRESS,
        )


def test_llm_planner_returns_safe_fail_when_provider_errors() -> None:
    parser = build_parser()
    planner = LLMPlanner(provider=RaisingProvider(), parser=parser)

    decision = planner.decide(
        PlannerContext(
            task=UserTask(request="Do something"),
            current_observation=None,
            trace_summary=[],
            available_skills=[],
            session_state=PlannerSessionState(
                session_id="session_test",
                status=RuntimeStatus.RUNNING,
                step_count=0,
                max_steps=4,
            ),
        )
    )

    assert decision.decision_type == PlannerDecisionType.FAIL
    assert "provider error" in (decision.failure_reason or "")


def test_parser_accepts_element_id_for_click_element() -> None:
    """Parser should accept click_element with element_id parameter."""
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act",
            "rationale": "Click the spam button using element_id.",
            "chosen_skill": "click_element",
            "skill_input": {"element_id": "element_abc123"},
            "expected_outcome": "The email is marked as spam.",
            "risk_level": "low",
            "destructive": False,
            "completion_confidence": 0.8,
            "progress_assessment": "partial_progress",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.chosen_skill == "click_element"
    assert decision.skill_input.get("element_id") == "element_abc123"


def test_parser_accepts_selector_fallback_when_element_id_missing() -> None:
    """Parser should accept click_element with only selector (fallback)."""
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act",
            "rationale": "Click using selector fallback.",
            "chosen_skill": "click_element",
            "skill_input": {"selector": '[data-testid="custom-btn"]'},
            "expected_outcome": "Button is clicked.",
            "risk_level": "low",
            "destructive": False,
            "completion_confidence": 0.8,
            "progress_assessment": "partial_progress",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.chosen_skill == "click_element"
    assert decision.skill_input.get("selector") == '[data-testid="custom-btn"]'


def test_parser_rejects_click_element_without_target() -> None:
    """Parser should reject click_element without element_id or selector."""
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act",
            "rationale": "Click without specifying target.",
            "chosen_skill": "click_element",
            "skill_input": {},
            "expected_outcome": "Nothing happens.",
            "risk_level": "low",
            "destructive": False,
            "completion_confidence": 0.5,
            "progress_assessment": "unknown",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    assert decision.decision_type == PlannerDecisionType.FAIL
    assert "skill schema" in (decision.failure_reason or "") or "selector" in (decision.failure_reason or "").lower()


def test_parser_prefers_element_id_when_both_provided() -> None:
    """Parser should accept both element_id and selector, preferring element_id at runtime."""
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act",
            "rationale": "Click with both identifiers.",
            "chosen_skill": "click_element",
            "skill_input": {
                "element_id": "element_abc123",
                "selector": 'text="Submit"'
            },
            "expected_outcome": "Button is clicked.",
            "risk_level": "low",
            "destructive": False,
            "completion_confidence": 0.8,
            "progress_assessment": "partial_progress",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    # Parser validates schema, which allows both - runtime will prefer element_id
    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.chosen_skill == "click_element"
    assert decision.skill_input.get("element_id") == "element_abc123"
    assert decision.skill_input.get("selector") == 'text="Submit"'
