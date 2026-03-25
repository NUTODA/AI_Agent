"""Prompt-building helpers for the structured planner."""

from __future__ import annotations

from textwrap import dedent

from browser_agent.llm.planner import AvailableSkill, PlannerContext
from browser_agent.llm.provider import LLMMessage


PLANNER_SYSTEM_PROMPT = dedent(
    """
    You are the planner for a browser automation agent.

    Your job is to choose the single best next atomic step based on:
    - the user task;
    - the current browser observation;
    - the recent execution trace summary;
    - the typed skill catalog;
    - the current runtime session state.

    Hard rules:
    - Return exactly one JSON object and nothing else.
    - Never invent tools or skill names.
    - Never control the browser directly.
    - Never generate code, scripts, selectors, or workflows outside the provided action space.
    - Never use task-specific or site-specific assumptions.
    - Never claim success without evidence from the observation or trace.
    - Choose only one next atomic step per iteration.
    - Ask the user only when required information is genuinely missing.
    - Request confirmation before risky or destructive actions.
    - Finish only when the task is sufficiently supported by observed evidence.

    IMPORTANT - Selector usage for click_element and type_text:
    - ALWAYS use the exact selector values provided in the Current observation's interactive_elements.
    - Prefer data-testid selectors when available (e.g., '[data-testid="add-burger"]').
    - Playwright does NOT support jQuery selectors like :contains().
    - Valid selector formats: CSS selectors, text selectors (text="..."), role selectors.
    - When multiple elements match, use the most specific selector from the observation.

    Decision types:
    - act: execute exactly one registered skill next.
    - ask_user: pause and ask the operator a concrete blocking question.
    - request_confirmation: pause and request confirmation for a specific risky skill action.
    - finish: stop because the task is complete with evidence.
    - fail: stop because the task cannot continue safely or honestly.

    Required JSON shape:
    {
      "decision_type": "act | ask_user | request_confirmation | finish | fail",
      "rationale": "short reasoning summary",
      "chosen_skill": "registered skill name or null",
      "skill_input": {},
      "expected_outcome": "what should happen after the skill runs or null",
      "risk_level": "low | medium | high | critical",
      "destructive": false,
      "completion_confidence": 0.0,
      "progress_assessment": "unknown | no_progress | partial_progress | substantial_progress",
      "requires_confirmation": false,
      "user_question": null,
      "finish_reason": null,
      "failure_reason": null
    }
    """
).strip()


def build_planner_messages(planner_context: PlannerContext) -> list[LLMMessage]:
    """Build the chat messages sent to the planner provider."""

    return [
        LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
        LLMMessage(role="user", content=build_planner_context(planner_context)),
    ]


def build_planner_context(planner_context: PlannerContext) -> str:
    """Render a compact prompt context for the planner."""

    session_state = planner_context.session_state
    return dedent(
        f"""
        Task:
        - request: {planner_context.task.request}
        - start_url: {planner_context.task.start_url or "none"}
        - constraints: {_render_list(planner_context.task.constraints)}
        - success_criteria: {_render_list(planner_context.task.success_criteria)}

        Session state:
        - session_id: {session_state.session_id}
        - status: {session_state.status.value}
        - step_count: {session_state.step_count}/{session_state.max_steps}
        - no_progress_streak: {session_state.no_progress_streak}
        - latest_url: {session_state.latest_url or "unknown"}
        - latest_page_title: {session_state.latest_page_title or "unknown"}
        - latest_action_name: {session_state.latest_action_name or "none"}
        - latest_tool_status: {session_state.latest_tool_status.value if session_state.latest_tool_status else "none"}

        Pending state:
        {_render_pending_state(planner_context)}

        Current observation:
        {_render_observation(planner_context)}

        Recent trace summary:
        {_render_trace_summary(planner_context.trace_summary)}

        Available skills:
        {_render_available_skills(planner_context.available_skills)}
        """
    ).strip()


def _render_pending_state(planner_context: PlannerContext) -> str:
    session_state = planner_context.session_state
    lines: list[str] = []
    if session_state.pending_confirmation is not None:
        request = session_state.pending_confirmation
        lines.append(
            f"- pending_confirmation: {request.action_name} ({request.risk_level.value})"
        )
        lines.append(f"- confirmation_reason: {request.reason}")
    else:
        lines.append("- pending_confirmation: none")

    if session_state.pending_user_question is not None:
        lines.append(
            f"- pending_user_question: {session_state.pending_user_question.question}"
        )
    else:
        lines.append("- pending_user_question: none")

    if session_state.user_responses:
        lines.append("- recent_user_answers:")
        for response in session_state.user_responses[-3:]:
            lines.append(f"  - {response.answer}")
    else:
        lines.append("- recent_user_answers: none")

    return "\n".join(lines)


def _render_observation(planner_context: PlannerContext) -> str:
    observation = planner_context.current_observation
    if observation is None:
        return "- no observation is available yet"

    visible_text = observation.visible_text_excerpt[:500] or "none"
    interactive_labels = ", ".join(
        element.label for element in observation.interactive_elements[:8]
    )
    form_labels = ", ".join(
        field.label or field.name or field.selector
        for field in observation.form_fields[:8]
    )
    lines = [
        f"- page_url: {observation.page_url}",
        f"- page_title: {observation.page_title}",
        f"- summary: {observation.summary}",
        f"- visible_text_excerpt: {visible_text}",
        f"- interactive_elements: {interactive_labels or 'none'}",
        f"- form_fields: {form_labels or 'none'}",
    ]
    if observation.observation_errors:
        lines.append(
            f"- observation_errors: {', '.join(observation.observation_errors[:4])}"
        )
    return "\n".join(lines)


def _render_trace_summary(trace_summary: list[str]) -> str:
    if not trace_summary:
        return "- no prior planner steps have been recorded"
    return "\n".join(f"- {item}" for item in trace_summary[-8:])


def _render_available_skills(available_skills: list[AvailableSkill]) -> str:
    if not available_skills:
        return "- no skills are available"

    blocks: list[str] = []
    for skill in available_skills:
        blocks.append(f"- {skill.name}: {skill.description}")
        for contract_line in skill.input_contract:
            blocks.append(f"  - {contract_line}")
    return "\n".join(blocks)


def _render_list(items: list[str]) -> str:
    if not items:
        return "none"
    return "; ".join(items)
