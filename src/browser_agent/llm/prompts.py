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

    CRITICAL - Element targeting policy for click_element, type_text, select_option, press_key:
    1. If the target element appears in the Current observation's interactive_elements list:
       - YOU MUST use the element_id field (e.g., "element_abc123")
       - Never construct your own selector when a stable element_id is available
    2. Only use the selector field as a fallback when:
       - The element is NOT present in the current observation
       - You need to interact with an element that wasn't captured
    3. NEVER use generic text selectors (text="...") for repeated controls like:
       - "Mark Spam" buttons in email lists
       - "Add to Cart" buttons on product listing pages
       - "Delete" buttons in table rows
       These are ambiguous and will click the wrong element.
    4. NEVER use unsupported jQuery-style selectors like :contains()
    5. Playwright selector formats: CSS selectors, text="exact text", role=button[name="label"]

    Decision types (decision_type must be EXACTLY one word from this list):
    - act: execute exactly one registered skill next.
    - ask_user: pause and ask the operator a concrete blocking question.
    - request_confirmation: pause and request confirmation for a specific risky skill action.
    - finish: stop because the task is complete with evidence.
    - fail: stop because the task cannot continue safely or honestly.

    Required JSON shape (example values — do not paste alternatives into one string):
    {
      "decision_type": "act",
      "rationale": "short reasoning summary",
      "chosen_skill": "registered skill name or null",
      "skill_input": {},
      "expected_outcome": "non-empty: what observable change you expect after this skill (required for act and request_confirmation)",
      "risk_level": "low",
      "destructive": false,
      "completion_confidence": 0.0,
      "progress_assessment": "partial_progress",
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
    lines = [
        f"- page_url: {observation.page_url}",
        f"- page_title: {observation.page_title}",
        f"- summary: {observation.summary}",
        f"- visible_text_excerpt: {visible_text}",
    ]

    # Render interactive elements with element_id prominently displayed
    if observation.interactive_elements:
        lines.append("- interactive_elements (USE element_id from this list):")
        for element in observation.interactive_elements[:15]:
            element_line = _format_interactive_element(element)
            lines.append(f"  {element_line}")
    else:
        lines.append("- interactive_elements: none")

    # Render form fields with field_id
    if observation.form_fields:
        lines.append("- form_fields:")
        for field in observation.form_fields[:10]:
            field_line = _format_form_field(field)
            lines.append(f"  {field_line}")
    else:
        lines.append("- form_fields: none")

    if observation.observation_errors:
        lines.append(
            f"- observation_errors: {', '.join(observation.observation_errors[:4])}"
        )
    return "\n".join(lines)


def _format_interactive_element(element) -> str:
    """Format an interactive element for the planner with element_id first."""
    parts = [f"[{element.element_id}]"]

    # Tag and role
    tag_info = element.tag or "element"
    if element.role and element.role != "other":
        tag_info = f"{element.tag} ({element.role})"
    parts.append(tag_info)

    # Text/label content
    display_text = element.text or element.label or ""
    if display_text:
        # Truncate long text
        if len(display_text) > 40:
            display_text = display_text[:37] + "..."
        parts.append(f'"{display_text}"')

    # Stable attributes for reference
    attrs = []
    if element.attributes:
        testid = element.attributes.get("data-testid") or element.attributes.get("testid")
        if testid:
            attrs.append(f"testid={testid}")
        if element.aria_label:
            attrs.append(f"aria-label={element.aria_label[:30]}")
        if element.attributes.get("name"):
            attrs.append(f"name={element.attributes.get('name')}")

    if attrs:
        parts.append(f"| {' | '.join(attrs)}")

    # State indicators
    states = []
    if not element.is_visible:
        states.append("hidden")
    if not element.is_enabled:
        states.append("disabled")
    if element.is_clickable:
        states.append("clickable")
    if element.is_input:
        states.append("input")

    if states:
        parts.append(f"[{', '.join(states)}]")

    return " ".join(parts)


def _format_form_field(field) -> str:
    """Format a form field for the planner with field_id first."""
    parts = [f"[{field.field_id}]"]

    # Field type and label
    label = field.label or field.name or "unnamed"
    if len(label) > 30:
        label = label[:27] + "..."
    parts.append(f"{field.field_type or 'input'}: \"{label}\"")

    # State indicators
    states = []
    if field.required:
        states.append("required")
    if field.filled:
        states.append("filled")
    if not field.is_visible:
        states.append("hidden")
    if not field.is_enabled:
        states.append("disabled")

    if states:
        parts.append(f"[{', '.join(states)}]")

    return " ".join(parts)


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
