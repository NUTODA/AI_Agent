"""Tests for console step view formatting helpers."""

from __future__ import annotations

from browser_agent.ui.formatting import format_step_card_plain
from browser_agent.ui.models import TimelineStepView


def test_format_step_card_text_includes_key_sections() -> None:
    step = TimelineStepView(
        step_number=4,
        phase_label="ACT",
        rationale_summary="Proceed to checkout",
        expected_outcome="See cart",
        skill_name="click_element",
        target_summary="element_id=el_41",
        result_status="success",
        progress_note="navigated to /cart",
    )
    text = format_step_card_plain(step)
    assert "[Step 5] ACT" in text
    assert "See cart" in text
    assert "Click Element" in text
    assert "element_id=el_41" in text
    assert "Success" in text
    assert "navigated" in text
