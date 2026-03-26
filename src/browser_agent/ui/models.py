"""UI-facing view models (not runtime state)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


Phase = Literal["idle", "observe", "plan", "guardrail", "act", "confirm", "wait_input", "done"]


@dataclass
class TimelineStepView:
    """One row in the center timeline (last N steps)."""

    step_number: int  # 0-based, matches runtime step_index
    phase_label: str  # e.g. ACT, FINISH
    rationale_summary: str
    expected_outcome: str | None
    skill_name: str | None
    target_summary: str | None
    result_status: str | None
    progress_note: str | None


@dataclass
class AgentConsoleState:
    """Mutable snapshot consumed by Rich render."""

    task: str = ""
    status: str = "pending"
    phase: Phase = "idle"
    max_steps_config: int = 0
    step_display: str = "0 / ?"  # current planner step vs max
    model_name: str | None = None
    provider_kind: str | None = None
    current_url: str | None = None
    page_title: str | None = None
    observation_summary: str = ""
    interactive_element_count: int = 0
    observation_warnings: list[str] = field(default_factory=list)
    last_decision_type: str | None = None
    last_rationale: str | None = None
    last_expected_outcome: str | None = None
    timeline: list[TimelineStepView] = field(default_factory=list)
    max_timeline_steps: int = 10
    bottom_mode: Literal["idle", "confirm", "input"] = "idle"
    confirm_action: str = ""
    confirm_reason: str = ""
    confirm_prompt: str = ""
    confirm_consequences: list[str] = field(default_factory=list)
    input_question: str = ""
    # Token / run metrics
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    total_tokens_total: int = 0
    llm_request_count: int = 0
    tokens_approximate: bool = False
    estimated_cost_usd: float | None = None
    run_started_at: datetime | None = None
    # Final overlay
    show_final_summary: bool = False
    final_summary_lines: list[str] = field(default_factory=list)
