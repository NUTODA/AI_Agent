"""Lightweight runtime events for terminal UI (no full state dumps)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AgentRunStarted:
    """Emitted when a run begins (session + task summary)."""

    timestamp: datetime
    session_id: str
    task_summary: str
    max_steps: int
    model_name: str | None = None
    provider_kind: str | None = None


@dataclass(frozen=True, slots=True)
class StepStarted:
    """Planner step iteration started (0-based step_index as in runtime)."""

    timestamp: datetime
    step_number: int


@dataclass(frozen=True, slots=True)
class ObservationReady:
    """After observe_page for this step."""

    timestamp: datetime
    step_number: int
    page_url: str | None
    page_title: str | None
    summary: str
    interactive_element_count: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannerDecisionReady:
    """After planner returns a decision (safe fields only)."""

    timestamp: datetime
    step_number: int
    decision_type: str
    rationale_summary: str
    expected_outcome: str | None
    chosen_skill: str | None
    skill_input_summary: str | None


@dataclass(frozen=True, slots=True)
class GuardrailCheck:
    """After safety guardrails classify the action."""

    timestamp: datetime
    step_number: int
    requires_confirmation: bool
    reason: str
    matched_signals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillExecutionStarted:
    """Right before skill.execute."""

    timestamp: datetime
    step_number: int
    skill_name: str
    target_summary: str | None


@dataclass(frozen=True, slots=True)
class SkillExecutionCompleted:
    """After skill returns (success or error)."""

    timestamp: datetime
    step_number: int
    skill_name: str
    status: str
    message: str
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class ConfirmationRequested:
    """Runtime paused for operator confirmation."""

    timestamp: datetime
    step_number: int
    action_name: str
    reason: str
    prompt: str
    consequences: tuple[str, ...] = ()
    risk_level: str | None = None


@dataclass(frozen=True, slots=True)
class UserInputRequested:
    """Runtime paused for blocking user question."""

    timestamp: datetime
    step_number: int
    question: str


@dataclass(frozen=True, slots=True)
class HumanInterventionRequested:
    """Runtime paused so the operator can act directly in the browser."""

    timestamp: datetime
    step_number: int
    kind: str
    instruction: str
    prompt: str
    resume_hint: str | None = None
    allowed_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StepCompleted:
    """Trace recorded and step counter advanced for this iteration."""

    timestamp: datetime
    step_number: int
    progress_summary: str | None
    session_status: str


@dataclass(frozen=True, slots=True)
class TokenUsageUpdated:
    """Per-request or cumulative LLM usage."""

    timestamp: datetime
    step_number: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cumulative_prompt_tokens: int
    cumulative_completion_tokens: int
    cumulative_total_tokens: int
    request_count: int
    latency_ms: float | None
    approximate: bool
    model_name: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunCompleted:
    """Terminal success or controlled stop with final report summary."""

    timestamp: datetime
    status: str
    summary: str
    step_count: int
    trace_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    final_url: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunFailed:
    """Non-terminal failure path (startup, observation, etc.)."""

    timestamp: datetime
    message: str
    failure_reason: str | None = None


RuntimeEvent = (
    AgentRunStarted
    | StepStarted
    | ObservationReady
    | PlannerDecisionReady
    | GuardrailCheck
    | SkillExecutionStarted
    | SkillExecutionCompleted
    | ConfirmationRequested
    | UserInputRequested
    | HumanInterventionRequested
    | StepCompleted
    | TokenUsageUpdated
    | AgentRunCompleted
    | AgentRunFailed
)


class RuntimeEventEmitter(Protocol):
    """Optional sink for UI events; default is no-op."""

    def emit(self, event: RuntimeEvent) -> None: ...


@dataclass
class NoOpEventEmitter:
    """Default emitter when no console is attached."""

    def emit(self, event: RuntimeEvent) -> None:  # noqa: ARG002
        return None


@dataclass
class CallbackEventEmitter:
    """Bridge to a callable (e.g. queue append for tests or UI thread)."""

    callback: Any

    def emit(self, event: RuntimeEvent) -> None:
        self.callback(event)


def list_event_types() -> tuple[str, ...]:
    """Names of all event dataclasses (for smoke tests)."""
    return (
        "AgentRunStarted",
        "StepStarted",
        "ObservationReady",
        "PlannerDecisionReady",
        "GuardrailCheck",
        "SkillExecutionStarted",
        "SkillExecutionCompleted",
        "ConfirmationRequested",
        "UserInputRequested",
        "HumanInterventionRequested",
        "StepCompleted",
        "TokenUsageUpdated",
        "AgentRunCompleted",
        "AgentRunFailed",
    )
