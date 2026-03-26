"""Tests for remapping stale element_id after a fresh observation."""

from __future__ import annotations

from browser_agent.runtime.element_remap import remap_stale_element_references
from browser_agent.runtime.models import AgentAction, AgentObservation, InteractiveElement


def _btn_old() -> InteractiveElement:
    return InteractiveElement(
        element_id="element_stale111",
        label="Order",
        tag="button",
        role="button",
        text="Order",
        selector="button.order-btn",
        selector_candidates=["button.order-btn", 'role=button[name="Order"]'],
    )


def _btn_new() -> InteractiveElement:
    return InteractiveElement(
        element_id="element_fresh222",
        label="Order",
        tag="button",
        role="button",
        text="Order",
        selector="button.order-btn",
        selector_candidates=["button.order-btn"],
    )


def test_remap_updates_element_id_when_selector_overlaps() -> None:
    obs_before = AgentObservation(
        summary="before",
        interactive_elements=[_btn_old()],
    )
    pre_obs = AgentObservation(
        summary="after observe",
        interactive_elements=[_btn_new()],
    )
    action = AgentAction(
        tool_name="click_element",
        rationale="Click order",
        parameters={"element_id": "element_stale111"},
        expected_outcome="Clicked",
    )

    out = remap_stale_element_references(action, pre_obs, [obs_before])

    assert out.parameters["element_id"] == "element_fresh222"
    assert "selector" not in out.parameters


def test_remap_noop_when_id_valid_in_pre_observation() -> None:
    pre_obs = AgentObservation(
        summary="current",
        interactive_elements=[_btn_new()],
    )
    action = AgentAction(
        tool_name="click_element",
        rationale="Click",
        parameters={"element_id": "element_fresh222"},
        expected_outcome="Done",
    )

    out = remap_stale_element_references(action, pre_obs, [])

    assert out.parameters["element_id"] == "element_fresh222"


def test_remap_fallback_to_selector_when_no_match_in_pre() -> None:
    old_el = InteractiveElement(
        element_id="element_stale111",
        label="X",
        tag="button",
        selector="button#gone",
        selector_candidates=[],
    )
    obs_before = AgentObservation(summary="before", interactive_elements=[old_el])
    pre_obs = AgentObservation(
        summary="after",
        interactive_elements=[
            InteractiveElement(
                element_id="element_other",
                label="Y",
                tag="a",
                selector="a.different",
            )
        ],
    )
    action = AgentAction(
        tool_name="click_element",
        rationale="Click",
        parameters={"element_id": "element_stale111"},
        expected_outcome="Done",
    )

    out = remap_stale_element_references(action, pre_obs, [obs_before])

    assert "element_id" not in out.parameters
    assert out.parameters.get("selector") == "button#gone"


def test_remap_skips_non_targeting_skill() -> None:
    pre_obs = AgentObservation(summary="x", interactive_elements=[])
    action = AgentAction(
        tool_name="navigate",
        rationale="Go",
        parameters={"url": "https://example.com", "wait_for": "load"},
        expected_outcome="Loaded",
    )

    out = remap_stale_element_references(action, pre_obs, [])

    assert out.parameters == action.parameters
