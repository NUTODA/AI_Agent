"""Observation-oriented runtime skills."""

from __future__ import annotations

from pydantic import BaseModel, Field

from browser_agent.runtime.models import AgentObservation, InteractiveElement
from browser_agent.skills.base import (
    BaseSkill,
    SkillContext,
    SkillExecutionError,
    raise_for_browser_result,
)


class ObservePageInput(BaseModel):
    """Input contract for observing the current page."""

    include_text_excerpt: bool = True
    include_interactive_elements: bool = True


class ObservePageOutput(BaseModel):
    """Output contract for the `observe_page` skill."""

    observation: AgentObservation


class ObservePageSkill(BaseSkill):
    """Capture the current page state through the browser adapter."""

    name = "observe_page"
    description = "Capture the current page snapshot for planning."
    input_schema = ObservePageInput
    output_schema = ObservePageOutput

    def execute(self, context: SkillContext, payload: ObservePageInput) -> ObservePageOutput:
        try:
            page_state = context.browser.observe_page()
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to observe the current page.",
                error_code="observe_page_failed",
                data={"details": str(exc)},
            ) from exc
        observation = page_state.to_agent_observation()
        if not payload.include_text_excerpt:
            observation.visible_text_excerpt = ""
        if not payload.include_interactive_elements:
            observation.interactive_elements = []
        return ObservePageOutput(observation=observation)


class GetInteractiveElementsInput(BaseModel):
    """Input contract for extracting visible controls."""

    max_elements: int = 25


class GetInteractiveElementsOutput(BaseModel):
    """Output contract for interactive element extraction."""

    elements: list[InteractiveElement] = Field(default_factory=list)
    observation: AgentObservation | None = None


class GetInteractiveElementsSkill(BaseSkill):
    """Return the current page's interactive elements."""

    name = "get_interactive_elements"
    description = "List interactive elements visible on the current page."
    input_schema = GetInteractiveElementsInput
    output_schema = GetInteractiveElementsOutput

    def execute(
        self,
        context: SkillContext,
        payload: GetInteractiveElementsInput,
    ) -> GetInteractiveElementsOutput:
        try:
            elements = context.browser.get_interactive_elements(
                max_elements=payload.max_elements
            )
            page_state = context.browser.observe_page()
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to collect interactive elements from the current page.",
                error_code="get_interactive_elements_failed",
                data={"details": str(exc)},
            ) from exc
        observation = page_state.to_agent_observation()
        observation.interactive_elements = elements[: payload.max_elements]
        return GetInteractiveElementsOutput(
            elements=observation.interactive_elements[: payload.max_elements],
            observation=observation,
        )


class ExtractPageTextInput(BaseModel):
    """Input contract for extracting readable page text."""

    max_chars: int = 4000


class ExtractPageTextOutput(BaseModel):
    """Output contract for the `extract_page_text` skill."""

    text: str
    truncated: bool
    page_url: str


class ExtractPageTextSkill(BaseSkill):
    """Read the current page's visible text."""

    name = "extract_page_text"
    description = "Extract readable text from the current page."
    input_schema = ExtractPageTextInput
    output_schema = ExtractPageTextOutput

    def execute(
        self,
        context: SkillContext,
        payload: ExtractPageTextInput,
    ) -> ExtractPageTextOutput:
        try:
            page_state = context.browser.observe_page()
            text = context.browser.get_page_text(max_chars=payload.max_chars)
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to extract page text.",
                error_code="extract_page_text_failed",
                data={"details": str(exc)},
            ) from exc
        original_text_length = int(page_state.metadata.get("visible_text_length", len(text)))
        return ExtractPageTextOutput(
            text=text,
            truncated=original_text_length > payload.max_chars,
            page_url=page_state.url,
        )


class WaitForElementInput(BaseModel):
    """Input contract for waiting for an element to appear."""

    selector: str
    timeout_ms: int = 5000
    state: str = "visible"  # visible, hidden, attached, detached


class WaitForElementOutput(BaseModel):
    """Output contract for wait execution."""

    found: bool
    selector: str
    waited_ms: int
    state: str
    message: str
    observation: AgentObservation | None = None


class WaitForElementSkill(BaseSkill):
    """Wait for an element to reach a specific state (visible, hidden, etc.)."""

    name = "wait_for_element"
    description = "Wait for an element to appear, disappear, or reach a specific state."
    input_schema = WaitForElementInput
    output_schema = WaitForElementOutput

    def execute(
        self,
        context: SkillContext,
        payload: WaitForElementInput,
    ) -> WaitForElementOutput:
        try:
            result = raise_for_browser_result(
                context.browser.wait_for_element(
                    selector=payload.selector,
                    timeout_ms=payload.timeout_ms,
                    state=payload.state,
                ),
                default_error_code="wait_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message=f"Failed to wait for element `{payload.selector}`.",
                error_code="wait_failed",
                data={
                    "selector": payload.selector,
                    "timeout_ms": payload.timeout_ms,
                    "state": payload.state,
                    "details": str(exc),
                },
            ) from exc
        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )
        metadata = result.metadata or {}
        return WaitForElementOutput(
            found=metadata.get("found", False),
            selector=payload.selector,
            waited_ms=metadata.get("waited_ms", 0),
            state=payload.state,
            message=result.message,
            observation=observation,
        )
