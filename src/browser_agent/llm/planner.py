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
        task_start_url = session_summary.get("task_start_url")
        latest_action_name = session_summary.get("latest_action_name")
        observation_count = int(session_summary.get("observation_count", 0))
        action_count = int(session_summary.get("action_count", 0))

        if action_count == 0 and task_start_url:
            thought = AgentThought(
                summary="Navigate to the requested starting page.",
                rationale=(
                    "A provided start URL is an explicit operator input, so the "
                    "bootstrap planner can begin with a single typed navigation "
                    "step before observing the live page."
                ),
            )
            action = AgentAction(
                tool_name="navigate",
                rationale=thought.rationale,
                parameters={"url": task_start_url, "wait_for": "load"},
                expected_outcome="Load the requested page before the first observation.",
                risk_level=RiskLevel.LOW,
            )
            return PlannerDecision(thought=thought, action=action)

        if latest_action_name == "navigate":
            thought = AgentThought(
                summary="Observe the page after navigation.",
                rationale=(
                    "The runtime should capture the page that actually loaded after "
                    "navigation instead of assuming the resulting state."
                ),
            )
            action = AgentAction(
                tool_name="observe_page",
                rationale=thought.rationale,
                expected_outcome="Capture the navigated page as a structured observation.",
                risk_level=RiskLevel.LOW,
            )
            return PlannerDecision(thought=thought, action=action)

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
                    "Foundation bootstrap completed. The runtime executed a real "
                    "browser-backed bootstrap flow and captured a structured "
                    "observation, then stopped honestly because a full planner "
                    "is not wired yet."
                ),
                "next_steps": [
                    "Wire a real LLM planner into the runtime loop.",
                    "Add more generic browser skills for richer interaction coverage.",
                    "Improve progress detection for multi-step autonomous execution.",
                ],
            },
            risk_level=RiskLevel.LOW,
        )
        return PlannerDecision(thought=thought, action=action)
