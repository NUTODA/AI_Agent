"""Planner contracts for the browser agent runtime."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from browser_agent.runtime.models import AgentAction, AgentThought, RiskLevel, RuntimeStatus


class PlannerDecision(BaseModel):
    """Typed output emitted by a planner for the next runtime step."""

    thought: AgentThought
    action: AgentAction | None = None
    user_question: str | None = None


class Planner(Protocol):
    """Planner interface consumed by the runtime loop."""

    def decide(self, session_summary: dict[str, object]) -> PlannerDecision:
        """Choose the next action based on the current runtime summary."""


class FoundationPlanner:
    """Bootstrap-only planner used until real LLM integration lands.

    The planner intentionally performs a tiny generic workflow:
    observe the current page once, then finish with a transparent foundation
    report. This keeps the runtime executable without faking a production agent.
    """

    def decide(self, session_summary: dict[str, object]) -> PlannerDecision:
        observation_count = int(session_summary.get("observation_count", 0))
        if observation_count == 0:
            thought = AgentThought(
                summary="Collect an initial observation.",
                rationale=(
                    "The runtime should begin from the current page state rather "
                    "than hidden assumptions or task-specific pipelines."
                ),
            )
            action = AgentAction(
                tool_name="observe_page",
                rationale=thought.rationale,
                expected_outcome="Capture the current page for the first planning step.",
                risk_level=RiskLevel.LOW,
            )
            return PlannerDecision(thought=thought, action=action)

        thought = AgentThought(
            summary="Stop after the bootstrap observation.",
            rationale=(
                "This repository currently implements a strong foundation only. "
                "The runtime should return an honest report instead of pretending "
                "that a live autonomous planner already exists."
            ),
            can_finish=True,
        )
        action = AgentAction(
            tool_name="finish_task",
            rationale=thought.rationale,
            expected_outcome="Return a transparent bootstrap report.",
            parameters={
                "status": RuntimeStatus.STOPPED.value,
                "summary": (
                    "Foundation bootstrap completed. The runtime captured an "
                    "initial observation and is ready for real planner and "
                    "Playwright integration in the next phase."
                ),
                "next_steps": [
                    "Replace the stub browser engine with a Playwright adapter.",
                    "Wire a real LLM planner into the runtime loop.",
                    "Expand scenario coverage through generic skills, not scripts.",
                ],
            },
            risk_level=RiskLevel.LOW,
        )
        return PlannerDecision(thought=thought, action=action)
