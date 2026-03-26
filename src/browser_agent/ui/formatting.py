"""Shared text formatting for console display (no task-specific logic)."""

from __future__ import annotations

from typing import Any

from browser_agent.ui.models import TimelineStepView


def truncate_text(text: str, max_len: int, *, suffix: str = "...") -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - len(suffix))] + suffix


def summarize_skill_input(action_input: dict[str, Any]) -> str | None:
    """Concise parameter line for UI (mirrors trace input priority)."""
    if not action_input:
        return None
    priority_fields = [
        "selector",
        "element_id",
        "url",
        "text",
        "key",
        "direction",
        "option_text",
        "option_value",
        "file_path",
    ]
    parts: list[str] = []
    for field in priority_fields:
        if field in action_input and action_input[field]:
            value = str(action_input[field])
            if len(value) > 40:
                value = value[:37] + "..."
            parts.append(f"{field}={value}")
            if len(parts) >= 3:
                break
    return ", ".join(parts) if parts else None


def format_tool_target(skill_name: str, parameters: dict[str, Any]) -> str | None:
    summary = summarize_skill_input(parameters)
    if summary:
        return summary
    if not parameters:
        return None
    return str(parameters)[:80]


def format_step_card_plain(step: TimelineStepView) -> str:
    """Plain-text step card for tests and non-Rich consumers."""
    exp = step.expected_outcome or "—"
    lines = [
        f"[Step {step.step_number + 1}] {step.phase_label}",
        f"Reason:\n{step.rationale_summary}",
        f"Expected outcome:\n{exp}",
        f"Skill:\n{step.skill_name or '—'}",
        f"Target:\n{step.target_summary or '—'}",
        f"Result:\n{step.result_status or '—'}",
        f"Progress:\n{step.progress_note or '—'}",
    ]
    return "\n".join(lines)
