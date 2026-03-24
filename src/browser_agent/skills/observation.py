"""Observation-oriented runtime skills."""

from __future__ import annotations

from pydantic import BaseModel, Field

from browser_agent.runtime.models import AgentObservation, InteractiveElement
from browser_agent.skills.base import BaseSkill, SkillContext


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
        page_state = context.browser.get_page_state()
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
        elements = context.browser.get_page_state().to_agent_observation().interactive_elements
        return GetInteractiveElementsOutput(elements=elements[: payload.max_elements])


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
        page_state = context.browser.get_page_state()
        text = context.browser.extract_page_text(max_chars=payload.max_chars)
        original_excerpt = page_state.text_excerpt
        return ExtractPageTextOutput(
            text=text,
            truncated=len(original_excerpt) > payload.max_chars,
            page_url=page_state.url,
        )
