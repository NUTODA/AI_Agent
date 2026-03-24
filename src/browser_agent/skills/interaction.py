"""Interaction-oriented runtime skills."""

from __future__ import annotations

from pydantic import BaseModel, model_validator

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
    """Input contract for clicking an element."""

    selector: str | None = None
    element_id: str | None = None
    element_name: str | None = None

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
    """Input contract for entering text into an element."""

    selector: str | None = None
    element_id: str | None = None
    text: str
    clear_first: bool = True
    submit: bool = False
    sensitive: bool = False

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
