"""Tests for selector generation and target resolution helpers."""

from __future__ import annotations

from browser_agent.browser.page_state import ElementRole, InteractiveElementState
from browser_agent.browser.selectors import (
    SelectorStrategy,
    build_selector_candidates,
    resolve_target_candidates,
)


def test_build_selector_candidates_prefers_testid_then_semantics() -> None:
    element = InteractiveElementState(
        name="Submit order",
        tag="button",
        role=ElementRole.BUTTON,
        selector="form > button:nth-of-type(1)",
        text="Submit order",
        attributes={
            "data-testid": "submit-order",
            "id": "submit-button",
            "name": "submit",
        },
        clickable=True,
    )

    candidates = build_selector_candidates(element)

    assert [candidate.strategy for candidate in candidates[:3]] == [
        SelectorStrategy.DATA_TESTID,
        SelectorStrategy.ROLE,
        SelectorStrategy.LABEL,
    ]
    assert candidates[0].value == '[data-testid="submit-order"]'
    assert candidates[-1].strategy == SelectorStrategy.CSS


def test_resolve_target_candidates_uses_observed_element_reference() -> None:
    element = InteractiveElementState(
        element_id="element_submit",
        name="Submit order",
        tag="button",
        role=ElementRole.BUTTON,
        selector="form > button:nth-of-type(1)",
        text="Submit order",
        attributes={"data-testid": "submit-order"},
        clickable=True,
    )

    resolution = resolve_target_candidates(element.element_id, {element.element_id: element})

    assert resolution.used_element_reference is True
    assert resolution.matched_element_id == element.element_id
    assert resolution.candidates[0].value == '[data-testid="submit-order"]'


def test_resolve_target_candidates_keeps_stale_element_reference_structured() -> None:
    resolution = resolve_target_candidates("element_missing", {})

    assert resolution.used_element_reference is True
    assert resolution.matched_element_id == "element_missing"
    assert resolution.candidates == []
