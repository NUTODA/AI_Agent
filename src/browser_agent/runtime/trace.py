"""Trace collection helpers for the browser agent runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    AgentThought,
    ExecutionTraceItem,
    FinalReport,
    ProgressOutcome,
    ToolCall,
    ToolResult,
)


@dataclass(slots=True)
class TraceRecorder:
    """Collect execution trace items in memory and optional files."""

    trace_dir: Path | None = None
    session_id: str | None = None
    items: list[ExecutionTraceItem] = field(default_factory=list)

    def bind_session(self, session_id: str) -> None:
        """Bind persistent trace output to a runtime session."""

        self.session_id = session_id
        if self.trace_dir is not None:
            self.trace_dir.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        step_index: int,
        observation: AgentObservation | None = None,
        thought: AgentThought | None = None,
        planner_decision: PlannerDecision | None = None,
        action: AgentAction | None = None,
        tool_call: ToolCall | None = None,
        tool_result: ToolResult | None = None,
        progress_outcome: ProgressOutcome | None = None,
        state_transition: str | None = None,
        report: FinalReport | None = None,
        notes: list[str] | None = None,
    ) -> ExecutionTraceItem:
        """Create and store a trace item."""

        artifacts: list[str] = []
        if observation is not None:
            artifacts.extend(observation.artifact_refs)
        if tool_result is not None:
            artifacts.extend(tool_result.artifacts)

        item = ExecutionTraceItem(
            step_index=step_index,
            observation_id=observation.observation_id if observation else None,
            observation_summary=observation.summary if observation else None,
            thought_id=thought.thought_id if thought else None,
            action_id=action.action_id if action else None,
            action_name=(
                action.tool_name
                if action is not None
                else (tool_call.skill_name if tool_call is not None else None)
            ),
            action_input=(
                action.parameters
                if action is not None
                else (tool_call.arguments if tool_call is not None else {})
            ),
            status=tool_result.status if tool_result else None,
            output_summary=tool_result.message if tool_result else None,
            duration_ms=tool_result.duration_ms if tool_result else None,
            current_url=observation.page_url if observation else None,
            page_title=observation.page_title if observation else None,
            error_message=tool_result.error_message if tool_result else None,
            planner_decision_type=(
                planner_decision.decision_type if planner_decision is not None else None
            ),
            rationale_summary=(
                planner_decision.rationale if planner_decision is not None else None
            ),
            completion_confidence=(
                planner_decision.completion_confidence
                if planner_decision is not None
                else None
            ),
            planner_progress_assessment=(
                planner_decision.progress_assessment
                if planner_decision is not None
                else None
            ),
            artifacts=list(dict.fromkeys(artifacts)),
            tool_call=tool_call,
            tool_result=tool_result,
            progress_outcome=progress_outcome,
            state_transition=state_transition,
            report_summary=report.summary if report is not None else None,
            notes=notes or [],
        )
        self.items.append(item)
        self._append_jsonl(item)
        return item

    @property
    def jsonl_path(self) -> Path | None:
        if self.trace_dir is None or self.session_id is None:
            return None
        return self.trace_dir / f"{self.session_id}.jsonl"

    @property
    def markdown_path(self) -> Path | None:
        if self.trace_dir is None or self.session_id is None:
            return None
        return self.trace_dir / f"{self.session_id}.md"

    def artifact_refs(self) -> list[str]:
        """Return persistent trace artifacts if they exist."""

        refs: list[str] = []
        if self.jsonl_path is not None and self.jsonl_path.exists():
            refs.append(str(self.jsonl_path))
        if self.markdown_path is not None and self.markdown_path.exists():
            refs.append(str(self.markdown_path))
        return refs

    def _append_jsonl(self, item: ExecutionTraceItem) -> None:
        if self.jsonl_path is None:
            return
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item.model_dump(mode="json")))
            handle.write("\n")
        self.markdown_path.write_text(self.as_markdown(), encoding="utf-8")

    def as_markdown(self) -> str:
        """Render a short human-readable summary for debugging and demos."""

        lines = ["# Runtime Trace"]
        for item in self.items:
            action_name = item.action_name or (
                item.planner_decision_type.value
                if item.planner_decision_type is not None
                else "unknown"
            )
            status = item.status.value if item.status else "no_tool_result"
            lines.append(f"- step `{item.step_index}` `{action_name}` -> `{status}`")
            if item.planner_decision_type:
                lines.append(f"  decision: {item.planner_decision_type.value}")
            if item.rationale_summary:
                lines.append(f"  rationale: {item.rationale_summary}")
            if item.observation_summary:
                lines.append(f"  observation: {item.observation_summary}")
            if item.current_url:
                lines.append(f"  url: {item.current_url}")
            if item.output_summary:
                lines.append(f"  summary: {item.output_summary}")
            if item.progress_outcome is not None:
                lines.append(f"  progress: {item.progress_outcome.summary}")
            if item.state_transition:
                lines.append(f"  state: {item.state_transition}")
            if item.report_summary:
                lines.append(f"  report: {item.report_summary}")
            if item.error_message:
                lines.append(f"  error: {item.error_message}")
        return "\n".join(lines)
