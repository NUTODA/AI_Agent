"""Interaction-oriented runtime skills."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from browser_agent.runtime.models import AgentObservation
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


class ClickElementInput(BaseModel):
    """Input contract for clicking an element.

    Either `selector` or `element_id` must be provided (at least one required).
    """

    selector: str | None = Field(
        default=None,
        description="CSS selector to find the element. REQUIRED if element_id is not provided.",
    )
    element_id: str | None = Field(
        default=None,
        description="Element ID to click. REQUIRED if selector is not provided.",
    )
    element_name: str | None = Field(
        default=None,
        description="Human-readable name for the element (optional, for logging).",
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
    description = "Click a target element using a selector."
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

    Either `selector` or `element_id` must be provided (at least one required).
    """

    selector: str | None = Field(
        default=None,
        description="CSS selector to find the element. REQUIRED if element_id is not provided.",
    )
    element_id: str | None = Field(
        default=None,
        description="Element ID to type into. REQUIRED if selector is not provided.",
    )
    text: str = Field(description="Text to type into the element.")
    clear_first: bool = Field(default=True, description="Clear existing text before typing.")
    submit: bool = Field(default=False, description="Press Enter after typing.")
    sensitive: bool = Field(default=False, description="Mark as sensitive (will be masked in logs).")

    @model_validator(mode="after")
    def validate_target(self) -> "TypeTextInput":
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
    description = "Type text into a field or editable region."
    input_schema = TypeTextInput
    output_schema = TypeTextOutput

    def execute(
        self,
        context: SkillContext,
        payload: TypeTextInput,
    ) -> TypeTextOutput:
        target = _resolve_target(payload.selector, payload.element_id)
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

    Either `selector` or `element_id` must be provided (at least one required).
    Either `option_value` or `option_text` must be provided (at least one required).
    """

    selector: str | None = Field(
        default=None,
        description="CSS selector to find the select element. REQUIRED if element_id is not provided.",
    )
    element_id: str | None = Field(
        default=None,
        description="Element ID of the select element. REQUIRED if selector is not provided.",
    )
    option_value: str | None = Field(
        default=None,
        description="Option value to select. REQUIRED if option_text is not provided.",
    )
    option_text: str | None = Field(
        default=None,
        description="Visible text of option to select. REQUIRED if option_value is not provided.",
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
    description = "Select an option from a dropdown/select element by value or visible text."
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
    """Input contract for pressing a keyboard key."""

    key: str = Field(description="Key to press (e.g., 'Enter', 'Escape', 'Tab').")
    selector: str | None = Field(
        default=None,
        description="CSS selector to target element (optional, if None key is sent globally).",
    )
    element_id: str | None = Field(
        default=None,
        description="Element ID to target (optional, if None key is sent globally).",
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
    description = "Press a keyboard key like Enter, Escape, Tab, etc. Can target a specific element or send globally."
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
