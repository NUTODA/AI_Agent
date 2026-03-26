"""Unit tests for Agent Console presentation helpers (no Rich snapshots)."""

from __future__ import annotations

from browser_agent.ui.formatting import (
    FinalSummaryInput,
    build_final_summary_lines,
    compute_timeline_phase_label,
    generate_human_summary,
    humanize_skill_name,
)
from browser_agent.ui.models import AgentConsoleState
from browser_agent.ui.render import build_layout


def test_compute_timeline_phase_label_waiting_confirmation() -> None:
    assert (
        compute_timeline_phase_label(
            session_status="waiting_for_confirmation",
            step_had_non_observe_skill=True,
        )
        == "WAITING_CONFIRMATION"
    )


def test_compute_timeline_phase_label_planner_fail_without_action_skill() -> None:
    assert (
        compute_timeline_phase_label(
            session_status="failed",
            step_had_non_observe_skill=False,
        )
        == "PLAN"
    )


def test_compute_timeline_phase_label_act_when_skill_ran() -> None:
    assert (
        compute_timeline_phase_label(
            session_status="running",
            step_had_non_observe_skill=True,
        )
        == "ACT"
    )


def test_generate_human_summary_planner_decision_with_expected_outcome() -> None:
    s = generate_human_summary(
        event_kind="planner_decision",
        decision_type="act",
        rationale="Select the spam row by element id",
        expected_outcome="Spam folder shows the message",
        skill_name="click_element",
    )
    assert "Expected:" in s or "Spam folder" in s or "Select the spam" in s


def test_generate_human_summary_observation() -> None:
    s = generate_human_summary(event_kind="observation_ready")
    assert "page" in s.lower() or "structure" in s.lower()


def test_humanize_skill_name() -> None:
    assert humanize_skill_name("click_element") == "Click Element"
    assert humanize_skill_name(None) == "—"


def test_build_layout_does_not_break_on_rich_markup_like_strings() -> None:
    """User/LLM text may contain [brackets]; layout must not raise MarkupError."""
    state = AgentConsoleState()
    state.task = "Order [combo] and note [/] special"
    state.human_summary = "Saw [/] in page title"
    state.observation_summary = "Button [submit] and stray [/] token"
    state.last_rationale = "Use [bold] not raw"
    state.page_title = "Test [/] page"
    state.current_url = "http://127.0.0.1/foo[bar]"
    layout = build_layout(state)
    assert layout is not None


def _layout_export_text(state: AgentConsoleState) -> str:
    from rich.console import Console

    c = Console(record=True, width=120, legacy_windows=False, force_terminal=True)
    c.print(build_layout(state))
    return c.export_text()


def test_build_layout_idle_bottom_panel_operator_read_only() -> None:
    state = AgentConsoleState()
    state.bottom_mode = "idle"
    text = _layout_export_text(state)
    assert "Operator" in text
    assert "not a text field" in text.lower() or "status only" in text.lower()


def test_build_layout_confirm_bottom_panel_title() -> None:
    state = AgentConsoleState()
    state.bottom_mode = "confirm"
    state.confirm_action = "delete_row"
    state.confirm_reason = "irreversible"
    state.confirm_consequences = ["Data loss"]
    text = _layout_export_text(state)
    assert "Confirmation" in text
    assert "CONFIRMATION REQUIRED" in text


def test_build_layout_input_bottom_panel_question_title() -> None:
    state = AgentConsoleState()
    state.bottom_mode = "input"
    state.input_question = "Which size?"
    text = _layout_export_text(state)
    assert "Question" in text
    assert "Which size?" in text
    assert "read-only" in text.lower() or "not a text field" in text.lower()


def test_build_final_summary_lines_structure() -> None:
    data = FinalSummaryInput(
        task="Mark spam emails",
        status="completed",
        outcome_label="Completed",
        step_count=3,
        llm_request_count=4,
        prompt_tokens=1000,
        completion_tokens=200,
        total_tokens=1200,
        tokens_approximate=False,
        estimated_cost_usd=0.0012,
        latency_avg_ms="450 ms",
        duration_mmss="01:05",
        summary="Done.",
        visited_urls=["https://example.com/inbox"],
        trace_refs=("traces/session_x.jsonl",),
        artifact_refs=("traces/session_x.md",),
        key_actions=["Navigate — opened inbox", "Click Element — marked spam"],
    )
    lines = build_final_summary_lines(data)
    text = "\n".join(lines)
    assert "RUN COMPLETED" in text
    assert "Outcome: Completed" in text
    assert "Steps: 3" in text
    assert "LLM calls: 4" in text
    assert "Prompt:" in text
    assert "Completion:" in text
    assert "Key actions:" in text
    assert "Visited URLs:" in text
    assert "Artifacts" in text
