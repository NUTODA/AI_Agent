"""Typed runtime contracts for the browser agent runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Generate a readable object identifier."""

    return f"{prefix}_{uuid4().hex[:12]}"


class RiskLevel(str, Enum):
    """Risk levels used by the safety layer."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuntimeStatus(str, Enum):
    """Session/report lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    WAITING_FOR_INTERVENTION = "waiting_for_intervention"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class ToolExecutionStatus(str, Enum):
    """Possible outcomes of a skill invocation."""

    SUCCESS = "success"
    BLOCKED = "blocked"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    ERROR = "error"
    SKIPPED = "skipped"


# Backward-compatible alias kept for older tests and trace helpers.
ToolResultStatus = ToolExecutionStatus


class PlannerDecisionType(str, Enum):
    """The only planner decisions the runtime understands."""

    ACT = "act"
    ASK_USER = "ask_user"
    REQUEST_CONFIRMATION = "request_confirmation"
    FINISH = "finish"
    FAIL = "fail"


class PlannerProgressState(str, Enum):
    """Planner-provided progress signal used by anti-loop logic."""

    UNKNOWN = "unknown"
    NO_PROGRESS = "no_progress"
    PARTIAL_PROGRESS = "partial_progress"
    SUBSTANTIAL_PROGRESS = "substantial_progress"


class InteractiveElement(BaseModel):
    """A user-visible interactive control discovered on a page."""

    element_id: str = Field(default_factory=lambda: new_id("element"))
    label: str
    tag: str | None = None
    role: str | None = None
    text: str | None = None
    aria_label: str | None = None
    placeholder: str | None = None
    selector: str
    selector_candidates: list[str] = Field(default_factory=list)
    is_visible: bool = True
    is_enabled: bool = True
    is_clickable: bool = False
    is_input: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class FormFieldSummary(BaseModel):
    """Compact description of an observed input-like control."""

    field_id: str = Field(default_factory=lambda: new_id("field"))
    label: str | None = None
    name: str | None = None
    selector: str
    field_type: str | None = None
    placeholder: str | None = None
    required: bool = False
    filled: bool = False
    is_visible: bool = True
    is_enabled: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)


class UserTask(BaseModel):
    """The operator request the runtime is trying to satisfy."""

    task_id: str = Field(default_factory=lambda: new_id("task"))
    request: str
    start_url: str | None = None
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    requires_authentication: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class AgentObservation(BaseModel):
    """A concise, structured view of the current browser state."""

    observation_id: str = Field(default_factory=lambda: new_id("obs"))
    page_url: str = "about:blank"
    page_title: str = "Blank Page"
    summary: str
    visible_text_excerpt: str = ""
    interactive_elements: list[InteractiveElement] = Field(default_factory=list)
    form_fields: list[FormFieldSummary] = Field(default_factory=list)
    observation_errors: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=utc_now)


class AgentThought(BaseModel):
    """Structured reasoning emitted by the planner before action selection."""

    thought_id: str = Field(default_factory=lambda: new_id("thought"))
    summary: str
    rationale: str
    missing_information: list[str] = Field(default_factory=list)
    confidence: float | None = None
    needs_user_input: bool = False
    can_finish: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class AgentAction(BaseModel):
    """A typed instruction for the runtime to execute via a skill."""

    action_id: str = Field(default_factory=lambda: new_id("action"))
    tool_name: str
    rationale: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str
    risk_level: RiskLevel = RiskLevel.LOW
    destructive: bool = False
    requires_confirmation: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class ToolCall(BaseModel):
    """The runtime's record of invoking a skill."""

    call_id: str = Field(default_factory=lambda: new_id("call"))
    action_id: str | None = None
    skill_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    invoked_at: datetime = Field(default_factory=utc_now)


class ToolResult(BaseModel):
    """Structured outcome of a skill invocation."""

    call_id: str
    skill_name: str
    status: ToolExecutionStatus
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    completed_at: datetime = Field(default_factory=utc_now)


class ConfirmationRequest(BaseModel):
    """A human approval request for a risky or destructive action."""

    request_id: str = Field(default_factory=lambda: new_id("confirm"))
    action_id: str | None = None
    action_name: str
    reason: str
    risk_level: RiskLevel
    consequences: list[str] = Field(default_factory=list)
    prompt: str
    created_at: datetime = Field(default_factory=utc_now)


class PendingUserQuestion(BaseModel):
    """A user-facing question that blocks the runtime from continuing."""

    question_id: str = Field(default_factory=lambda: new_id("question"))
    question: str
    created_at: datetime = Field(default_factory=utc_now)


class HumanInterventionKind(str, Enum):
    """Reasons the runtime hands browser control back to the operator."""

    LOGIN = "login"
    CAPTCHA = "captcha"
    TWO_FACTOR = "two_factor"
    SITE_HANDOFF = "site_handoff"
    REVIEW = "review"
    CUSTOM = "custom"


class HumanInterventionRequest(BaseModel):
    """A typed browser handoff that requires manual operator action."""

    request_id: str = Field(default_factory=lambda: new_id("handoff"))
    kind: HumanInterventionKind = HumanInterventionKind.CUSTOM
    instruction: str
    prompt: str
    resume_hint: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class UserResponse(BaseModel):
    """A user answer captured for a pending runtime question."""

    response_id: str = Field(default_factory=lambda: new_id("answer"))
    question_id: str | None = None
    answer: str
    received_at: datetime = Field(default_factory=utc_now)


class ProgressOutcome(BaseModel):
    """Deterministic runtime progress signal recorded after each step."""

    made_progress: bool
    summary: str
    signals: list[str] = Field(default_factory=list)
    no_progress_streak: int = 0


class ExecutionTraceItem(BaseModel):
    """Correlates observation, thought, action, and execution metadata."""

    trace_id: str = Field(default_factory=lambda: new_id("trace"))
    step_index: int
    observation_id: str | None = None
    observation_summary: str | None = None
    thought_id: str | None = None
    action_id: str | None = None
    action_name: str | None = None
    action_input: dict[str, Any] = Field(default_factory=dict)
    planner_decision_type: PlannerDecisionType | None = None
    rationale_summary: str | None = None
    completion_confidence: float | None = None
    planner_progress_assessment: PlannerProgressState | None = None
    status: ToolExecutionStatus | None = None
    output_summary: str | None = None
    duration_ms: int | None = None
    current_url: str | None = None
    page_title: str | None = None
    error_message: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    progress_outcome: ProgressOutcome | None = None
    state_transition: str | None = None
    report_summary: str | None = None
    notes: list[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=utc_now)


class LLMUsageTotals(BaseModel):
    """Cumulative LLM usage for one runtime session (UI / metrics)."""

    cumulative_prompt_tokens: int = 0
    cumulative_completion_tokens: int = 0
    cumulative_total_tokens: int = 0
    request_count: int = 0
    last_prompt_tokens: int | None = None
    last_completion_tokens: int | None = None
    last_total_tokens: int | None = None
    last_latency_ms: float | None = None
    last_approximate: bool = False
    last_model_name: str | None = None

    def add_request(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        approximate: bool,
        latency_ms: float | None,
        model_name: str | None,
    ) -> None:
        self.cumulative_prompt_tokens += prompt_tokens
        self.cumulative_completion_tokens += completion_tokens
        self.cumulative_total_tokens += total_tokens
        self.request_count += 1
        self.last_prompt_tokens = prompt_tokens
        self.last_completion_tokens = completion_tokens
        self.last_total_tokens = total_tokens
        self.last_approximate = approximate
        self.last_latency_ms = latency_ms
        self.last_model_name = model_name


class FinalReport(BaseModel):
    """A user-facing summary of the runtime outcome."""

    session_id: str
    status: RuntimeStatus
    summary: str
    completed: bool = False
    actions_taken: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    final_url: str | None = None
    step_count: int = 0
    completion_reason: str | None = None
    failure_reason: str | None = None
    pending_confirmation: ConfirmationRequest | None = None
    pending_user_question: PendingUserQuestion | None = None
    pending_human_intervention: HumanInterventionRequest | None = None
    generated_at: datetime = Field(default_factory=utc_now)
