"""Interaction-oriented runtime skills."""

from __future__ import annotations

from pydantic import BaseModel

from browser_agent.skills.base import BaseSkill, SkillContext


class ClickElementInput(BaseModel):
    """Input contract for clicking an element."""

    selector: str
    element_name: str | None = None


class ClickElementOutput(BaseModel):
    """Output contract for click execution."""

    selector: str
    message: str
    page_title: str | None = None


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
        result = context.browser.click(payload.selector)
        return ClickElementOutput(
            selector=payload.selector,
            message=result.message,
            page_title=result.page_state.title if result.page_state else None,
        )


class TypeTextInput(BaseModel):
    """Input contract for entering text into an element."""

    selector: str
    text: str
    submit: bool = False
    sensitive: bool = False


class TypeTextOutput(BaseModel):
    """Output contract for text entry."""

    selector: str
    characters_entered: int
    submitted: bool
    message: str


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
        result = context.browser.type_text(
            payload.selector,
            payload.text,
            submit=payload.submit,
        )
        return TypeTextOutput(
            selector=payload.selector,
            characters_entered=len(payload.text),
            submitted=payload.submit,
            message=result.message,
        )
