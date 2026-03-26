"""Runtime session state for a single browser-agent task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from browser_agent.config import RuntimeSettings
from browser_agent.llm.planner import AvailableSkill, PlannerContext, PlannerSessionState
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    AgentThought,
    ConfirmationRequest,
    ExecutionTraceItem,
    FinalReport,
    LLMUsageTotals,
    PendingUserQuestion,
    ProgressOutcome,
    RuntimeStatus,
    ToolCall,
    ToolResult,
    UserResponse,
    UserTask,
    new_id,
)
from browser_agent.safety.confirmations import ConfirmationDecision


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


@dataclass(slots=True)
class RuntimeSession:
    """Mutable state container for one agent execution.

    The session keeps a clean record of what the agent saw, thought, decided,
    executed, and reported. It is intentionally in-memory for the current
    foundation stage.
    """

    task: UserTask
    settings: RuntimeSettings
    session_id: str = field(default_factory=lambda: new_id("session"))
    status: RuntimeStatus = RuntimeStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    step_count: int = 0
    no_progress_streak: int = 0
    observations: list[AgentObservation] = field(default_factory=list)
    thoughts: list[AgentThought] = field(default_factory=list)
    actions: list[AgentAction] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    trace_items: list[ExecutionTraceItem] = field(default_factory=list)
    pending_confirmation: ConfirmationRequest | None = None
    pending_action: AgentAction | None = None
    pending_user_question: PendingUserQuestion | None = None
    user_responses: list[UserResponse] = field(default_factory=list)
    execution_history_summary: list[str] = field(default_factory=list)
    completion_reason: str | None = None
    failure_reason: str | None = None
    final_report: FinalReport | None = None
    llm_usage: LLMUsageTotals = field(default_factory=LLMUsageTotals)

    def start(self) -> None:
        """Move the session into the running state."""

        self.status = RuntimeStatus.RUNNING
        self.final_report = None

    def add_observation(self, observation: AgentObservation) -> None:
        """Store a new observation."""

        self.observations.append(observation)

    def add_thought(self, thought: AgentThought) -> None:
        """Store a planner thought."""

        self.thoughts.append(thought)

    def add_action(self, action: AgentAction) -> None:
        """Store a planned action."""

        self.actions.append(action)

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Store a skill invocation."""

        self.tool_calls.append(tool_call)

    def add_tool_result(self, tool_result: ToolResult) -> None:
        """Store a skill result."""

        self.tool_results.append(tool_result)

    def add_trace_item(self, trace_item: ExecutionTraceItem) -> None:
        """Append a trace entry."""

        self.trace_items.append(trace_item)

    def increment_step(self) -> None:
        """Advance the planner-step counter."""

        self.step_count += 1

    def record_history(self, summary: str) -> None:
        """Store a bounded human-readable execution summary line."""

        self.execution_history_summary.append(summary)
        if len(self.execution_history_summary) > 50:
            self.execution_history_summary = self.execution_history_summary[-50:]

    def register_progress(self, outcome: ProgressOutcome) -> None:
        """Persist the latest deterministic progress signal."""

        self.no_progress_streak = outcome.no_progress_streak

    def set_pending_confirmation(
        self,
        request: ConfirmationRequest | None,
        *,
        action: AgentAction | None = None,
    ) -> None:
        """Set or clear a pending confirmation request."""

        self.pending_confirmation = request
        self.pending_action = action if request is not None else None
        if request is not None:
            self.pending_user_question = None
            self.status = RuntimeStatus.WAITING_FOR_CONFIRMATION
        elif self.status == RuntimeStatus.WAITING_FOR_CONFIRMATION:
            self.status = RuntimeStatus.RUNNING

    def set_pending_user_question(
        self,
        question: PendingUserQuestion | None,
    ) -> None:
        """Set or clear the current blocking user question."""

        self.pending_user_question = question
        if question is not None:
            self.pending_confirmation = None
            self.pending_action = None
            self.status = RuntimeStatus.WAITING_FOR_USER
        elif self.status == RuntimeStatus.WAITING_FOR_USER:
            self.status = RuntimeStatus.RUNNING

    def continue_after_confirmation(
        self,
        decision: ConfirmationDecision,
    ) -> AgentAction | None:
        """Apply a confirmation response and return the approved action if any."""

        if self.pending_confirmation is None or self.pending_action is None:
            raise ValueError("There is no pending confirmation to resolve.")
        if decision.request_id != self.pending_confirmation.request_id:
            raise ValueError("Confirmation decision does not match the pending request.")

        action = self.pending_action
        status_label = "approved" if decision.approved else "rejected"
        self.record_history(
            f"Confirmation `{self.pending_confirmation.action_name}` was {status_label}."
        )
        self.pending_confirmation = None
        self.pending_action = None
        self.final_report = None

        if decision.approved:
            self.status = RuntimeStatus.RUNNING
            return action

        self.status = RuntimeStatus.STOPPED
        self.failure_reason = (
            decision.reviewer_notes
            or f"The operator rejected `{action.tool_name}`."
        )
        return None

    def continue_after_user_answer(self, answer: str) -> UserResponse:
        """Persist a user answer so the runtime can continue planning."""

        if self.pending_user_question is None:
            raise ValueError("There is no pending user question to answer.")

        response = UserResponse(
            question_id=self.pending_user_question.question_id,
            answer=answer,
        )
        self.user_responses.append(response)
        self.record_history(f"User answered: {answer}")
        self.pending_user_question = None
        self.final_report = None
        self.status = RuntimeStatus.RUNNING
        return response

    def trace_summary(self, *, limit: int = 8) -> list[str]:
        """Return a bounded execution-history summary for the planner."""

        return self.execution_history_summary[-limit:]

    def complete(self, report: FinalReport) -> FinalReport:
        """Persist the final report and update status."""

        self.final_report = report
        self.status = report.status
        self.completion_reason = report.completion_reason or self.completion_reason
        self.failure_reason = report.failure_reason or self.failure_reason
        if report.status not in {
            RuntimeStatus.WAITING_FOR_CONFIRMATION,
            RuntimeStatus.WAITING_FOR_USER,
        }:
            self.pending_confirmation = None
            self.pending_action = None
            self.pending_user_question = None
        return report

    @property
    def latest_observation(self) -> AgentObservation | None:
        """Return the most recent observation if available."""

        return self.observations[-1] if self.observations else None

    @property
    def latest_thought(self) -> AgentThought | None:
        """Return the most recent thought if available."""

        return self.thoughts[-1] if self.thoughts else None

    @property
    def latest_action(self) -> AgentAction | None:
        """Return the most recent action if available."""

        return self.actions[-1] if self.actions else None

    @property
    def latest_tool_result(self) -> ToolResult | None:
        """Return the most recent tool result if available."""

        return self.tool_results[-1] if self.tool_results else None

    @property
    def latest_user_response(self) -> UserResponse | None:
        """Return the most recent user answer if available."""

        return self.user_responses[-1] if self.user_responses else None

    def planner_state(self) -> PlannerSessionState:
        """Return the typed planner-facing snapshot of session state."""

        return PlannerSessionState(
            session_id=self.session_id,
            status=self.status,
            step_count=self.step_count,
            max_steps=self.settings.max_steps,
            no_progress_streak=self.no_progress_streak,
            latest_url=(
                self.latest_observation.page_url if self.latest_observation else None
            ),
            latest_page_title=(
                self.latest_observation.page_title if self.latest_observation else None
            ),
            latest_action_name=(
                self.latest_action.tool_name if self.latest_action else None
            ),
            latest_tool_status=(
                self.latest_tool_result.status if self.latest_tool_result else None
            ),
            pending_confirmation=self.pending_confirmation,
            pending_user_question=self.pending_user_question,
            user_responses=self.user_responses[-3:],
        )

    def build_planner_context(
        self,
        *,
        available_skills: list[AvailableSkill],
    ) -> PlannerContext:
        """Build the typed planner context for the next loop iteration."""

        return PlannerContext(
            task=self.task,
            current_observation=self.latest_observation,
            trace_summary=self.trace_summary(),
            available_skills=available_skills,
            session_state=self.planner_state(),
        )

    def summary(self) -> dict[str, object]:
        """Backward-compatible summary view of the typed planner state."""

        return self.planner_state().model_dump(mode="json")
