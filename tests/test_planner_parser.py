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


def test_parser_normalizes_pipe_separated_decision_type_from_prompt_confusion() -> None:
    """Local models sometimes paste the prompt's 'a | b | c' hint as a single string."""
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act | ask_user | request_confirmation | finish | fail",
            "rationale": "Start with navigation.",
            "chosen_skill": "navigate",
            "skill_input": {"url": "https://example.com", "wait_for": "load"},
            "expected_outcome": "Page loads.",
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

    assert decision.decision_type == PlannerDecisionType.ACT


def test_parser_fills_missing_expected_outcome_for_act() -> None:
    """Models sometimes omit expected_outcome despite the contract; recover before validation."""
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "act",
            "rationale": "Open the menu to add items.",
            "chosen_skill": "click_element",
            "skill_input": {"element_id": "element_1"},
            "risk_level": "low",
            "destructive": False,
            "completion_confidence": 0.5,
            "progress_assessment": "partial_progress",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.expected_outcome
    assert "menu" in decision.expected_outcome.lower()


def test_parser_normalizes_common_decision_synonyms() -> None:
    parser = build_parser()

    decision = parser.parse(
        {
            "decision_type": "action",
            "rationale": "Go to URL.",
            "chosen_skill": "navigate",
            "skill_input": {"url": "https://example.com", "wait_for": "load"},
            "expected_outcome": "Loaded.",
            "risk_level": "LOW",
            "destructive": False,
            "completion_confidence": 0.5,
            "progress_assessment": "PARTIAL_PROGRESS",
            "requires_confirmation": False,
            "user_question": None,
            "finish_reason": None,
            "failure_reason": None,
        }
    )

    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.risk_level.value == "low"
    assert decision.progress_assessment == PlannerProgressState.PARTIAL_PROGRESS


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


def test_parser_unwraps_nested_decision_key() -> None:
    """Some APIs nest the contract under `decision` or similar."""

    parser = build_parser()
    raw = """
    {
      "decision": {
        "decision_type": "act",
        "rationale": "Navigate first.",
        "chosen_skill": "navigate",
        "skill_input": {"url": "https://example.com", "wait_for": "load"},
        "expected_outcome": "Page loads.",
        "risk_level": "low",
        "destructive": false,
        "completion_confidence": 0.5,
        "progress_assessment": "unknown",
        "requires_confirmation": false,
        "user_question": null,
        "finish_reason": null,
        "failure_reason": null
      }
    }
    """
    decision = parser.parse(raw)
    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.chosen_skill == "navigate"


def test_parser_accepts_type_and_reason_aliases() -> None:
    parser = build_parser()
    decision = parser.parse(
        {
            "type": "act",
            "reason": "Go.",
            "chosen_skill": "navigate",
            "skill_input": {"url": "https://example.com", "wait_for": "load"},
            "expected_outcome": "Loaded.",
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
    assert decision.decision_type == PlannerDecisionType.ACT
    assert decision.rationale == "Go."


def test_parser_tries_later_json_object_when_first_invalid() -> None:
    """If the model emits a junk object then the real decision, use the valid one."""

    parser = build_parser()
    raw = """
    {"invalid": true}
    {
      "decision_type": "act",
      "rationale": "Second object is valid.",
      "chosen_skill": "navigate",
      "skill_input": {"url": "https://example.com", "wait_for": "load"},
      "expected_outcome": "Loaded.",
      "risk_level": "low",
      "destructive": false,
      "completion_confidence": 0.5,
      "progress_assessment": "unknown",
      "requires_confirmation": false,
      "user_question": null,
      "finish_reason": null,
      "failure_reason": null
    }
    """
    decision = parser.parse(raw)
    assert decision.decision_type == PlannerDecisionType.ACT
    assert "Second object" in decision.rationale


def test_parser_handles_missing_decision_type_with_extended_aliases() -> None:
    """Parser should handle missing decision_type by trying extended alias list."""
    parser = build_parser()

    # Test with "action" alias (commonly used by some models)
    decision = parser.parse(
        {
            "action": "act",
            "rationale": "Navigate to page.",
            "chosen_skill": "navigate",
            "skill_input": {"url": "https://example.com"},
            "expected_outcome": "Page loads.",
        }
    )
    assert decision.decision_type == PlannerDecisionType.ACT

    # Test with "decision" alias - must include all required fields for finish type
    decision2 = parser.parse(
        {
            "decision": "finish",
            "rationale": "Task complete.",
            "finish_reason": "Done successfully.",
            "completion_confidence": 0.95,
            "progress_assessment": "substantial_progress",
        }
    )
    assert decision2.decision_type == PlannerDecisionType.FINISH


def test_parser_returns_safe_fail_when_decision_type_completely_missing() -> None:
    """Parser should return safe_fail when decision_type is missing and no aliases match."""
    parser = build_parser()

    decision = parser.parse(
        {
            "rationale": "Missing decision type entirely.",
            "chosen_skill": "navigate",
            "skill_input": {"url": "https://example.com"},
            "expected_outcome": "Page loads.",
        }
    )
    assert decision.decision_type == PlannerDecisionType.FAIL
    assert "decision_type" in (decision.failure_reason or "")
