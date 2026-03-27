"""Shared text formatting for console display (no task-specific logic)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from browser_agent.ui.models import TimelineStepView


def truncate_text(text: str, max_len: int, *, suffix: str = "...") -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - len(suffix))] + suffix


def humanize_skill_name(skill_name: str | None) -> str:
    """Turn snake_case registry names into Title Case labels."""
    if not skill_name or skill_name == "—":
        return "—"
    parts = skill_name.replace("-", "_").split("_")
    return " ".join(p.capitalize() if p else "" for p in parts).strip() or skill_name


def humanize_result_status(status: str | None) -> str:
    if not status or status == "—":
        return "—"
    return " ".join(w.capitalize() for w in status.lower().split("_") if w)


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


def infer_error_block(
    *,
    status: str | None,
    message: str,
) -> tuple[str, str, str | None] | None:
    """If this skill outcome should surface as ERROR in the UI, return title, body, hint."""
    if not status:
        return None
    st = status.lower()
    if st not in {"error", "blocked"}:
        return None
    msg = (message or "").strip()
    low = msg.lower()
    title = "Tool execution failed" if st == "error" else "Action blocked"
    if "ambiguous" in low or "ambiguous_target" in low:
        title = "Ambiguous target"
        hint = "Use element_id from the observation, or a more specific selector."
    elif st == "blocked":
        hint = "Adjust the task or approve if a confirmation prompt appears."
    else:
        hint = "Check the trace and page state; the planner may replan on the next step."
    explanation = truncate_text(msg, 220) if msg else ("Execution did not succeed." if st == "error" else "Guardrails blocked this action.")
    return title, explanation, hint


def generate_human_summary(
    *,
    event_kind: str,
    decision_type: str | None = None,
    rationale: str | None = None,
    expected_outcome: str | None = None,
    skill_name: str | None = None,
    target_summary: str | None = None,
    guardrail_reason: str | None = None,
    requires_confirmation: bool | None = None,
    confirm_action: str | None = None,
    question: str | None = None,
    observation_snippet: str | None = None,
    progress_summary: str | None = None,
    skill_message: str | None = None,
    skill_status: str | None = None,
) -> str:
    """One or two short lines for the operator; avoids raw chain-of-thought."""
    r = (rationale or "").strip()
    exp = (expected_outcome or "").strip()

    if event_kind == "observation_ready":
        base = "Analyzing page structure to identify actionable elements."
        if observation_snippet:
            return truncate_text(f"{base} {observation_snippet}", 160)
        return base

    if event_kind == "planner_decision":
        dt = (decision_type or "").lower()
        if dt == "fail":
            return truncate_text(r or "Planner could not continue safely.", 160)
        if dt == "ask_user":
            return truncate_text(r or "The agent needs a detail from you to continue.", 160)
        if dt == "request_confirmation":
            return truncate_text(
                r or "Preparing a step that needs your approval before it runs.", 160
            )
        if dt == "finish":
            return truncate_text(r or "Wrapping up and preparing the final report.", 160)
        line = r or "Choosing the next browser action."
        if exp:
            line = truncate_text(f"{line} Expected: {exp}", 160)
        elif skill_name:
            sk = humanize_skill_name(skill_name)
            line = truncate_text(f"{line} Next: {sk}.", 160)
        return truncate_text(line, 160)

    if event_kind == "guardrail":
        if requires_confirmation:
            return truncate_text(
                guardrail_reason
                or "Safety check: confirmation required before this action can run.",
                160,
            )
        return truncate_text(guardrail_reason or "Evaluating action against safety rules.", 160)

    if event_kind == "skill_started":
        sk = humanize_skill_name(skill_name)
        if skill_name == "observe_page":
            return "Capturing the current page state and interactive elements."
        tgt = (target_summary or "").strip()
        if tgt:
            return truncate_text(f"Running {sk}: {tgt}", 160)
        return truncate_text(f"Running {sk}.", 160)

    if event_kind == "skill_completed":
        st = (skill_status or "").lower()
        sk = humanize_skill_name(skill_name)
        if st == "success":
            return truncate_text(f"{sk} completed.", 120)
        if st in {"error", "blocked"}:
            msg = truncate_text((skill_message or "").strip(), 120)
            if msg:
                return f"{sk}: {msg}"
            return f"{sk} did not succeed."
        if st == "waiting_for_confirmation":
            return truncate_text(
                skill_message or "Waiting for confirmation before an irreversible action.",
                160,
            )
        return truncate_text(skill_message or f"{sk} finished ({skill_status}).", 160)

    if event_kind == "confirmation":
        act = humanize_skill_name(confirm_action) if confirm_action else "this action"
        return truncate_text(
            f"Waiting for confirmation before: {act}.", 160
        )

    if event_kind == "user_input":
        return truncate_text(question or "Waiting for your answer.", 160)

    if event_kind == "step_completed":
        return truncate_text(progress_summary or "Step recorded.", 160)

    if event_kind == "run_started":
        return "Starting run and loading the browser session."

    return truncate_text(r or "Working…", 120)


def compute_timeline_phase_label(
    *,
    session_status: str,
    step_had_non_observe_skill: bool,
) -> str:
    """Map terminal session status + step activity to a canonical phase label for step cards."""
    if session_status == "waiting_for_confirmation":
        return "WAITING_CONFIRMATION"
    if session_status == "waiting_for_user":
        return "WAITING_USER"
    if session_status == "failed" and not step_had_non_observe_skill:
        return "PLAN"
    if step_had_non_observe_skill:
        return "ACT"
    return "OBSERVE"


@dataclass
class FinalSummaryInput:
    """Inputs for building the post-run summary text (testable without Rich)."""

    task: str
    status: str
    outcome_label: str
    step_count: int
    llm_request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    tokens_approximate: bool
    estimated_cost_usd: float | None
    latency_avg_ms: str
    duration_mmss: str
    summary: str
    visited_urls: list[str]
    trace_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    key_actions: list[str]
    failure_reason: str | None = None


def build_final_summary_lines(data: FinalSummaryInput) -> list[str]:
    """Plain lines for the final Rich panel (and unit tests)."""
    approx = " (estimated)" if data.tokens_approximate else ""
    cost = (
        f"${data.estimated_cost_usd:.4f}{approx}"
        if data.estimated_cost_usd is not None
        else f"N/A{approx}"
    )
    st = data.status.lower()
    if st == "failed":
        headline = "RUN FAILED"
    elif st == "completed":
        headline = "RUN COMPLETED"
    else:
        headline = "RUN STOPPED"

    artifact_refs = list(dict.fromkeys([*data.artifact_refs, *data.trace_refs]))
    lines: list[str] = [
        headline,
        "",
        f"Task: {truncate_text(data.task, 220)}",
        f"Outcome: {data.outcome_label}",
        f"Steps: {data.step_count}",
        f"LLM calls: {data.llm_request_count}",
        f"Tokens (total): {data.total_tokens:,}{approx}",
        f"  Prompt: {data.prompt_tokens:,}{approx}",
        f"  Completion: {data.completion_tokens:,}{approx}",
        f"Est. cost: {cost}",
        f"Avg LLM latency: {data.latency_avg_ms}",
        f"Duration: {data.duration_mmss}",
        "",
        f"Summary: {truncate_text(data.summary, 320)}",
    ]
    if data.failure_reason:
        lines.extend(["", f"Why it stopped: {truncate_text(data.failure_reason, 240)}"])
    lines.extend(["", "Key actions:"])
    if data.key_actions:
        for a in data.key_actions[:5]:
            lines.append(f"  • {truncate_text(a, 100)}")
    else:
        lines.append("  —")
    lines.extend(["", "Visited URLs:"])
    if data.visited_urls:
        for u in data.visited_urls[:12]:
            lines.append(f"  • {truncate_text(u, 100)}")
    else:
        lines.append("  —")
    lines.extend(["", "Artifacts (traces & files):"])
    if artifact_refs:
        for a in artifact_refs[:6]:
            lines.append(f"  • {truncate_text(a, 120)}")
        if len(artifact_refs) > 6:
            lines.append(f"  • … and {len(artifact_refs) - 6} more")
    else:
        lines.append("  —")
    return lines


def format_step_card_plain(step: TimelineStepView) -> str:
    """Plain-text step card for tests and non-Rich consumers."""
    exp = step.expected_outcome or "—"
    sk = step.skill_display or humanize_skill_name(step.skill_name)
    res = step.result_display or humanize_result_status(step.result_status)
    lines = [
        f"[Step {step.step_number + 1}] {step.phase_label}",
        f"Reason:\n{step.rationale_summary}",
        f"Expected outcome:\n{exp}",
        f"Skill:\n{sk}",
        f"Target:\n{step.target_summary or '—'}",
        f"Result:\n{res}",
        f"Progress:\n{step.progress_note or '—'}",
    ]
    return "\n".join(lines)


def format_step_line_compact(step: TimelineStepView) -> str:
    """Single-line step summary for narrow demo layouts."""
    result = (step.result_display or humanize_result_status(step.result_status) or "—").strip()
    progress = (step.progress_note or step.expected_outcome or step.rationale_summary or "—").strip()
    return (
        f"{step.step_number + 1}. {truncate_text(result, 10)}  "
        f"{truncate_text(progress, 60)}"
    )
