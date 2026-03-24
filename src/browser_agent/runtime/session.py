"""Runtime session state for a single browser-agent task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from browser_agent.config import RuntimeSettings
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    AgentThought,
    ConfirmationRequest,
    ExecutionTraceItem,
    FinalReport,
    RuntimeStatus,
    ToolCall,
    ToolResult,
    UserTask,
    new_id,
)


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
    observations: list[AgentObservation] = field(default_factory=list)
    thoughts: list[AgentThought] = field(default_factory=list)
    actions: list[AgentAction] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    trace_items: list[ExecutionTraceItem] = field(default_factory=list)
    pending_confirmation: ConfirmationRequest | None = None
    final_report: FinalReport | None = None

    def start(self) -> None:
        """Move the session into the running state."""

        self.status = RuntimeStatus.RUNNING

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

    def set_pending_confirmation(
        self,
        request: ConfirmationRequest | None,
    ) -> None:
        """Set or clear a pending confirmation request."""

        self.pending_confirmation = request
        if request is not None:
            self.status = RuntimeStatus.WAITING_FOR_USER

    def complete(self, report: FinalReport) -> FinalReport:
        """Persist the final report and update status."""

        self.final_report = report
        self.status = report.status
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

    def summary(self) -> dict[str, object]:
        """Return a concise planner-facing summary of the session state."""

        return {
            "session_id": self.session_id,
            "task_id": self.task.task_id,
            "task_request": self.task.request,
            "task_start_url": self.task.start_url,
            "status": self.status.value,
            "observation_count": len(self.observations),
            "action_count": len(self.actions),
            "tool_result_count": len(self.tool_results),
            "latest_url": (
                self.latest_observation.page_url if self.latest_observation else None
            ),
            "latest_page_title": (
                self.latest_observation.page_title if self.latest_observation else None
            ),
            "latest_observation_summary": (
                self.latest_observation.summary if self.latest_observation else None
            ),
            "latest_action_name": (
                self.latest_action.tool_name if self.latest_action else None
            ),
            "latest_tool_status": (
                self.latest_tool_result.status.value if self.latest_tool_result else None
            ),
            "pending_confirmation": (
                self.pending_confirmation.model_dump(mode="json")
                if self.pending_confirmation
                else None
            ),
        }
