"""Prompt-building helpers for the future planner implementation."""

from __future__ import annotations

from textwrap import dedent


PLANNER_SYSTEM_PROMPT = dedent(
    """
    You are the planner for a browser automation agent.

    Core rules:
    - Never use hardcoded task-specific workflows.
    - Decide from the current observation and execution trace.
    - Return exactly one next action at a time.
    - Ask the user when intent is ambiguous or a risky action needs approval.
    - Prefer transparent reasoning over fake certainty.
    """
).strip()


PLANNER_OUTPUT_NOTES = dedent(
    """
    Return a structured object containing:
    - thought.summary
    - thought.rationale
    - thought.missing_information
    - action.tool_name
    - action.parameters
    - action.expected_outcome
    - action.risk_level
    - action.requires_confirmation
    """
).strip()


def build_planner_context(
    *,
    task_request: str,
    session_summary: dict[str, object],
) -> str:
    """Build a compact planner context string.

    This helper is intentionally small for the foundation stage. A later
    integration can replace it with richer prompt assembly and truncation logic.
    """

    return dedent(
        f"""
        Task:
        {task_request}

        Session summary:
        {session_summary}
        """
    ).strip()
