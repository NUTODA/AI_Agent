"""Typed runtime contracts for the browser agent foundation.

These models define the integration surface between planning, runtime
orchestration, skills, browser automation, safety checks, and reporting.
"""

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


class InteractiveElement(BaseModel):
    """A user-visible interactive control discovered on a page."""

    element_id: str = Field(default_factory=lambda: new_id("element"))
    label: str
    role: str | None = None
    selector: str
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
    completed_at: datetime = Field(default_factory=utc_now)


class ExecutionTraceItem(BaseModel):
    """Correlates observation, thought, action, and execution metadata."""

    trace_id: str = Field(default_factory=lambda: new_id("trace"))
    step_index: int
    observation_id: str | None = None
    thought_id: str | None = None
    action_id: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    notes: list[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=utc_now)


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
    generated_at: datetime = Field(default_factory=utc_now)
