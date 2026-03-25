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
        """Render a demo-readable execution trace with clear step summaries."""

        lines = [
            "# Browser Agent Execution Trace",
            "",
        ]

        # Session header
        if self.session_id:
            lines.append(f"**Session ID:** `{self.session_id}`")
        lines.append(f"**Total Steps:** {len(self.items)}")
        lines.append(f"**Generated:** {self.items[0].recorded_at.strftime('%Y-%m-%d %H:%M:%S UTC') if self.items else 'N/A'}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for item in self.items:
            action_name = item.action_name or (
                item.planner_decision_type.value
                if item.planner_decision_type is not None
                else "unknown"
            )
            status = item.status.value if item.status else "pending"

            # Status indicator
            status_emoji = ""
            if status == "success":
                status_emoji = ""
            elif status == "error":
                status_emoji = ""
            elif status == "waiting_for_confirmation":
                status_emoji = ""
            elif status == "blocked":
                status_emoji = ""
            elif status == "skipped":
                status_emoji = ""

            # Step header
            lines.append(f"## Step {item.step_index + 1}: {action_name} {status_emoji}")
            lines.append("")

            # Decision info
            if item.planner_decision_type:
                lines.append(f"**Decision:** `{item.planner_decision_type.value}`")

            # Action details
            if item.action_name:
                lines.append(f"**Skill:** `{item.action_name}`")
            if item.action_input:
                # Show concise input summary
                input_summary = self._summarize_input(item.action_input)
                if input_summary:
                    lines.append(f"**Input:** {input_summary}")

            # Rationale (truncated for readability)
            if item.rationale_summary:
                rationale = item.rationale_summary
                if len(rationale) > 120:
                    rationale = rationale[:117] + "..."
                lines.append(f"**Rationale:** {rationale}")

            # Observation (truncated)
            if item.observation_summary:
                obs = item.observation_summary
                if len(obs) > 100:
                    obs = obs[:97] + "..."
                lines.append(f"**Observation:** {obs}")

            # Page context
            if item.page_title:
                lines.append(f"**Page:** {item.page_title}")
            if item.current_url:
                url_display = item.current_url[:80] + "..." if len(item.current_url) > 80 else item.current_url
                lines.append(f"**URL:** {url_display}")

            # Result
            if item.output_summary:
                lines.append(f"**Result:** {item.output_summary}")

            # Progress
            if item.progress_outcome:
                progress_indicator = "" if item.progress_outcome.made_progress else ""
                lines.append(f"**Progress:** {progress_indicator} {item.progress_outcome.summary}")

            # State transition (highlight pending states)
            if item.state_transition:
                if "waiting_for_confirmation" in item.state_transition:
                    lines.append(f"**State:**  {item.state_transition}")
                elif "waiting_for_user" in item.state_transition:
                    lines.append(f"**State:**  {item.state_transition}")
                elif "completed" in item.state_transition or "success" in item.state_transition:
                    lines.append(f"**State:**  {item.state_transition}")
                elif "failed" in item.state_transition:
                    lines.append(f"**State:**  {item.state_transition}")
                else:
                    lines.append(f"**State:** {item.state_transition}")

            # Error details
            if item.error_message:
                lines.append(f"**Error:** {item.error_message}")

            # Performance
            if item.duration_ms is not None:
                lines.append(f"**Duration:** {item.duration_ms}ms")

            # Artifacts
            if item.artifacts:
                lines.append(f"**Artifacts:** {', '.join(item.artifacts)}")

            # Separator between steps
            lines.append("")
            lines.append("---")
            lines.append("")

        # Final summary if available
        if self.items:
            last_item = self.items[-1]
            if last_item.report_summary:
                lines.append("## Final Summary")
                lines.append("")
                lines.append(last_item.report_summary)
                lines.append("")

        return "\n".join(lines)

    def _summarize_input(self, action_input: dict) -> str | None:
        """Create a concise summary of action input parameters."""

        if not action_input:
            return None

        # Key fields to display for common skills
        priority_fields = [
            "selector", "element_id", "url", "text", "key",
            "direction", "option_text", "option_value", "file_path"
        ]

        parts = []
        for field in priority_fields:
            if field in action_input and action_input[field]:
                value = str(action_input[field])
                # Truncate long values
                if len(value) > 40:
                    value = value[:37] + "..."
                parts.append(f"{field}={value}")
                if len(parts) >= 3:  # Limit to 3 parameters
                    break

        return ", ".join(parts) if parts else None
