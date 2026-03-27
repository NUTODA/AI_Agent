"""UI-facing view models (not runtime state)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# Demo-facing lifecycle labels (top bar + step cards + final screen).
DisplayPhase = Literal[
    "IDLE",
    "OBSERVE",
    "PLAN",
    "GUARDRAIL",
    "ACT",
    "WAITING_CONFIRMATION",
    "WAITING_USER",
    "FINISHED",
    "FAILED",
]

UIMode = Literal["demo", "debug"]


@dataclass
class TimelineStepView:
    """One row in the center timeline (last N steps)."""

    step_number: int  # 0-based, matches runtime step_index
    phase_label: str  # canonical DisplayPhase for this step
    rationale_summary: str
    expected_outcome: str | None
    skill_name: str | None
    target_summary: str | None
    result_status: str | None
    progress_note: str | None
    skill_display: str | None = None  # human-readable; fallback to formatted skill_name
    result_display: str | None = None  # human-readable result line


@dataclass
class AgentConsoleState:
    """Mutable snapshot consumed by Rich render."""

    task: str = ""
    ui_mode: UIMode = "demo"
    status: str = "pending"
    display_phase: DisplayPhase = "IDLE"
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
    # Short operator-facing line(s); not raw chain-of-thought
    human_summary: str = ""
    timeline: list[TimelineStepView] = field(default_factory=list)
    max_timeline_steps: int = 10
    bottom_mode: Literal["idle", "confirm", "input"] = "idle"
    confirm_action: str = ""
    confirm_reason: str = ""
    confirm_prompt: str = ""
    confirm_consequences: list[str] = field(default_factory=list)
    input_question: str = ""
    # Highlighted error strip (tool fail, ambiguous target, planner fail, guardrail)
    error_title: str | None = None
    error_explanation: str | None = None
    error_hint: str | None = None
    # Token / run metrics
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    total_tokens_total: int = 0
    llm_request_count: int = 0
    tokens_approximate: bool = False
    estimated_cost_usd: float | None = None
    llm_latency_sum_ms: float = 0.0
    llm_latency_count: int = 0
    run_started_at: datetime | None = None
    # Final overlay (built at AgentRunCompleted)
    show_final_summary: bool = False
    final_summary_lines: list[str] = field(default_factory=list)
    final_run_headline: str = ""  # RUN COMPLETED / RUN FAILED
    outcome_label: str = ""  # Completed / Partial / Failed
    key_actions: list[str] = field(default_factory=list)
