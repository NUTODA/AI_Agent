"""Trace collection helpers for the browser agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field

from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    AgentThought,
    ExecutionTraceItem,
    ToolCall,
    ToolResult,
)


@dataclass(slots=True)
class TraceRecorder:
    """Collect execution trace items in memory.

    This foundation keeps tracing simple and process-local. A later phase can
    extend this into durable JSONL or artifact-backed storage.
    """

    items: list[ExecutionTraceItem] = field(default_factory=list)

    def record(
        self,
        *,
        step_index: int,
        observation: AgentObservation | None = None,
        thought: AgentThought | None = None,
        action: AgentAction | None = None,
        tool_call: ToolCall | None = None,
        tool_result: ToolResult | None = None,
        notes: list[str] | None = None,
    ) -> ExecutionTraceItem:
        """Create and store a trace item."""

        item = ExecutionTraceItem(
            step_index=step_index,
            observation_id=observation.observation_id if observation else None,
            thought_id=thought.thought_id if thought else None,
            action_id=action.action_id if action else None,
            tool_call=tool_call,
            tool_result=tool_result,
            notes=notes or [],
        )
        self.items.append(item)
        return item

    def as_markdown(self) -> str:
        """Render a short human-readable summary for debugging and demos."""

        lines = ["# Runtime Trace"]
        for item in self.items:
            lines.append(f"- step `{item.step_index}` trace `{item.trace_id}`")
            if item.action_id:
                lines.append(f"  action: `{item.action_id}`")
            if item.tool_result:
                lines.append(f"  result: `{item.tool_result.status.value}`")
        return "\n".join(lines)
