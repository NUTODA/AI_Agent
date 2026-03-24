"""Deterministic progress detection helpers for the runtime loop."""

from __future__ import annotations

import hashlib

from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.models import AgentObservation, ProgressOutcome, ToolResult


class ProgressDetector:
    """Compute small, explainable progress signals from runtime state."""

    def evaluate(
        self,
        *,
        previous_observation: AgentObservation | None,
        current_observation: AgentObservation | None,
        tool_result: ToolResult | None,
        planner_decision: PlannerDecision,
        previous_no_progress_streak: int,
    ) -> ProgressOutcome:
        """Decide whether the latest step produced observable progress."""

        signals: list[str] = []

        if previous_observation is None and current_observation is not None:
            signals.append("initial observation captured")
        elif previous_observation is not None and current_observation is not None:
            if previous_observation.page_url != current_observation.page_url:
                signals.append("page URL changed")
            if previous_observation.page_title != current_observation.page_title:
                signals.append("page title changed")
            if self._text_hash(previous_observation) != self._text_hash(current_observation):
                signals.append("visible text excerpt changed")
            if self._interactive_signature(
                previous_observation
            ) != self._interactive_signature(current_observation):
                signals.append("interactive element set changed")

        if (
            tool_result is not None
            and tool_result.status.value == "success"
            and not signals
            and planner_decision.progress_assessment.value
            in {"partial_progress", "substantial_progress"}
        ):
            signals.append("planner marked progress after successful execution")

        if tool_result is not None and tool_result.status.value == "error":
            summary = "The last action failed and did not produce progress."
            return ProgressOutcome(
                made_progress=False,
                summary=summary,
                signals=["tool execution failed"],
                no_progress_streak=previous_no_progress_streak + 1,
            )

        made_progress = bool(signals)
        if made_progress:
            return ProgressOutcome(
                made_progress=True,
                summary="Observable progress detected after the last planner step.",
                signals=signals,
                no_progress_streak=0,
            )

        if planner_decision.progress_assessment.value == "no_progress":
            summary = "The planner explicitly reported no progress."
        else:
            summary = "No observable progress was detected after the last planner step."
        return ProgressOutcome(
            made_progress=False,
            summary=summary,
            signals=[],
            no_progress_streak=previous_no_progress_streak + 1,
        )

    def _text_hash(self, observation: AgentObservation) -> str:
        text = observation.visible_text_excerpt.strip().encode("utf-8")
        return hashlib.sha256(text).hexdigest()

    def _interactive_signature(self, observation: AgentObservation) -> tuple[str, ...]:
        signature_parts: list[str] = []
        for element in observation.interactive_elements[:20]:
            signature_parts.append(
                "|".join(
                    [
                        element.element_id,
                        element.label,
                        element.selector,
                        str(element.is_enabled),
                        str(element.is_visible),
                    ]
                )
            )
        return tuple(signature_parts)
