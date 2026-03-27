"""Interaction-oriented runtime skills."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from browser_agent.runtime.models import AgentObservation, FormFieldSummary
from browser_agent.skills.base import (
    BaseSkill,
    SkillContext,
    SkillExecutionError,
    raise_for_browser_result,
)


def _resolve_target(selector: str | None, element_id: str | None) -> str:
    target = element_id or selector
    if target is None:
        raise ValueError("One of `selector` or `element_id` must be provided.")
    return target


def _find_form_field_by_id(
    observation: AgentObservation | None,
    field_id: str,
) -> FormFieldSummary | None:
    if observation is None:
        return None
    for field in observation.form_fields:
        if field.field_id == field_id:
            return field
    return None


def _resolve_text_target(
    context: SkillContext,
    *,
    selector: str | None,
    element_id: str | None,
    field_id: str | None,
) -> str:
    if field_id:
        field = _find_form_field_by_id(context.session.latest_observation, field_id)
        if field is None or not field.selector:
            raise SkillExecutionError(
                message=f"Form field reference `{field_id}` is no longer available.",
                error_code="field_reference_not_found",
                data={"field_id": field_id},
            )
        return field.selector

    if element_id and element_id.startswith("field_"):
        field = _find_form_field_by_id(context.session.latest_observation, element_id)
        if field is None or not field.selector:
            raise SkillExecutionError(
                message=f"Form field reference `{element_id}` is no longer available.",
                error_code="field_reference_not_found",
                data={"field_id": element_id},
            )
        return field.selector

    return _resolve_target(selector, element_id)


class ClickElementInput(BaseModel):
    """Input contract for clicking an element.

    Prefer `element_id` when the target is present in the current observation.
    Use `selector` only as a fallback when the target is not observed.
    """

    element_id: str | None = Field(
        default=None,
        description="Primary target. Use the exact observed `element_id` from the current page when available.",
    )
    selector: str | None = Field(
        default=None,
        description="Fallback CSS or Playwright selector only when no reliable observed `element_id` is available. Avoid broad or text-only selectors when multiple controls may match.",
    )
    element_name: str | None = Field(
        default=None,
        description="Optional label for logs only. Not used for targeting or matching.",
    )

    @model_validator(mode="after")
    def validate_target(self) -> "ClickElementInput":
        _resolve_target(self.selector, self.element_id)
        return self


class ClickElementOutput(BaseModel):
    """Output contract for click execution."""

    target: str
    message: str
    page_title: str | None = None
    observation: AgentObservation | None = None


class ClickElementSkill(BaseSkill):
    """Click a single interactive element."""

    name = "click_element"
    description = "Click one intended control. Prefer observed `element_id`; use `selector` only as a fallback when the target is not reliably observed."
    input_schema = ClickElementInput
    output_schema = ClickElementOutput

    def execute(
        self,
        context: SkillContext,
        payload: ClickElementInput,
    ) -> ClickElementOutput:
        target = _resolve_target(payload.selector, payload.element_id)
        try:
            result = raise_for_browser_result(
                context.browser.click(target),
                default_error_code="click_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to click the requested page element.",
                error_code="click_failed",
                data={"target": target, "details": str(exc)},
            ) from exc
        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )
        return ClickElementOutput(
            target=target,
            message=result.message,
            page_title=result.page_state.title if result.page_state else None,
            observation=observation,
        )


class TypeTextInput(BaseModel):
    """Input contract for entering text into an element.

    Prefer `element_id` when the target is present in the current observation.
    Use `field_id` for observed form fields and `selector` only as a fallback.
    """

    element_id: str | None = Field(
        default=None,
        description="Primary target for an observed editable control. Use the exact visible `element_id` when available.",
    )
    selector: str | None = Field(
        default=None,
        description="Fallback CSS or Playwright selector only when no reliable observed `element_id` or `field_id` is available. Avoid broad selectors that may hit the wrong field.",
    )
    field_id: str | None = Field(
        default=None,
        description="Observed form field identifier from `form_fields`. Prefer this over guessing a selector for form inputs.",
    )
    text: str = Field(description="Literal text to enter into the target control.")
    clear_first: bool = Field(default=True, description="Clear the existing value before typing. Use `False` only when appending is intentional.")
    submit: bool = Field(default=False, description="Press Enter after typing only when submission or confirmation is the intended next action.")
    sensitive: bool = Field(default=False, description="Set to `True` for secrets or personal data so logs mask the value.")

    @model_validator(mode="after")
    def validate_target(self) -> "TypeTextInput":
        if self.field_id is None:
            _resolve_target(self.selector, self.element_id)
        return self


class TypeTextOutput(BaseModel):
    """Output contract for text entry."""

    target: str
    characters_entered: int
    clear_first: bool
    submitted: bool
    message: str
    observation: AgentObservation | None = None


class TypeTextSkill(BaseSkill):
    """Type text into an editable control."""

    name = "type_text"
    description = "Enter text into one intended field. Prefer observed `field_id` or `element_id`, mark sensitive values, and avoid typing into search or filter inputs unless the task needs it."
    input_schema = TypeTextInput
    output_schema = TypeTextOutput

    def execute(
        self,
        context: SkillContext,
        payload: TypeTextInput,
    ) -> TypeTextOutput:
        target = _resolve_text_target(
            context,
            selector=payload.selector,
            element_id=payload.element_id,
            field_id=payload.field_id,
        )
        try:
            result = raise_for_browser_result(
                context.browser.type_text(
                    target,
                    payload.text,
                    clear_first=payload.clear_first,
                    submit=payload.submit,
                ),
                default_error_code="type_text_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to enter text into the requested page element.",
                error_code="type_text_failed",
                data={"target": target, "details": str(exc)},
            ) from exc
        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )
        return TypeTextOutput(
            target=target,
            characters_entered=len(payload.text),
            clear_first=payload.clear_first,
            submitted=payload.submit,
            message=result.message,
            observation=observation,
        )


class SelectOptionInput(BaseModel):
    """Input contract for selecting an option from a dropdown.

    Prefer `element_id` when the select control is present in the current observation.
    Provide `option_value` or `option_text` for an actual option from that control.
    """

    element_id: str | None = Field(
        default=None,
        description="Primary target for an observed select control. Use the exact visible `element_id` when available.",
    )
    selector: str | None = Field(
        default=None,
        description="Fallback CSS or Playwright selector only when no reliable observed `element_id` is available.",
    )
    option_value: str | None = Field(
        default=None,
        description="Preferred option identifier when known. Use an actual option `value` from the target control.",
    )
    option_text: str | None = Field(
        default=None,
        description="Fallback visible option label. Use an exact label from the target control when `option_value` is not known.",
    )

    @model_validator(mode="after")
    def validate_target(self) -> "SelectOptionInput":
        _resolve_target(self.selector, self.element_id)
        if self.option_value is None and self.option_text is None:
            raise ValueError("One of `option_value` or `option_text` must be provided.")
        return self


class SelectOptionOutput(BaseModel):
    """Output contract for select option execution."""

    target: str
    selected_value: str | None = None
    selected_text: str | None = None
    message: str
    page_title: str | None = None
    observation: AgentObservation | None = None


class SelectOptionSkill(BaseSkill):
    """Select an option from a dropdown or select element."""

    name = "select_option"
    description = "Select one option in a dropdown. Prefer observed `element_id`; prefer `option_value` over visible text when both are possible."
    input_schema = SelectOptionInput
    output_schema = SelectOptionOutput

    def execute(
        self,
        context: SkillContext,
        payload: SelectOptionInput,
    ) -> SelectOptionOutput:
        target = _resolve_target(payload.selector, payload.element_id)
        try:
            result = raise_for_browser_result(
                context.browser.select_option(
                    target,
                    value=payload.option_value,
                    label=payload.option_text,
                ),
                default_error_code="select_option_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to select the requested option.",
                error_code="select_option_failed",
                data={"target": target, "details": str(exc)},
            ) from exc
        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )
        metadata = result.metadata or {}
        return SelectOptionOutput(
            target=target,
            selected_value=metadata.get("selected_value"),
            selected_text=metadata.get("selected_text"),
            message=result.message,
            page_title=result.page_state.title if result.page_state else None,
            observation=observation,
        )


class PressKeyInput(BaseModel):
    """Input contract for pressing a keyboard key.

    Prefer `element_id` when the target is present in the current observation.
    Leave both targeting fields empty for a global key press.
    """

    key: str = Field(description="Key to press, for example `Enter`, `Escape`, or `Tab`. Use the smallest key action that advances the task.")
    element_id: str | None = Field(
        default=None,
        description="Primary target for a focused key press. Use the exact visible `element_id` when available.",
    )
    selector: str | None = Field(
        default=None,
        description="Fallback CSS or Playwright selector only when no reliable observed `element_id` is available. Leave empty for a global key press.",
    )


class PressKeyOutput(BaseModel):
    """Output contract for key press execution."""

    key: str
    target: str | None = None
    message: str
    page_title: str | None = None
    observation: AgentObservation | None = None


class PressKeySkill(BaseSkill):
    """Press a keyboard key, optionally targeting a specific element."""

    name = "press_key"
    description = "Press a keyboard key as a focused action. Prefer observed `element_id` for targeted input; use a global press only when page-level handling is intended."
    input_schema = PressKeyInput
    output_schema = PressKeyOutput

    def execute(
        self,
        context: SkillContext,
        payload: PressKeyInput,
    ) -> PressKeyOutput:
        target = None
        if payload.selector or payload.element_id:
            target = _resolve_target(payload.selector, payload.element_id)

        try:
            result = raise_for_browser_result(
                context.browser.press_key(payload.key, target=target),
                default_error_code="press_key_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message=f"Failed to press key `{payload.key}`.",
                error_code="press_key_failed",
                data={"key": payload.key, "target": target, "details": str(exc)},
            ) from exc
        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )
        return PressKeyOutput(
            key=payload.key,
            target=target,
            message=result.message,
            page_title=result.page_state.title if result.page_state else None,
            observation=observation,
        )
