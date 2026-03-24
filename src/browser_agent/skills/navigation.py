"""Navigation-related runtime skills."""

from __future__ import annotations

from pydantic import BaseModel

from browser_agent.skills.base import BaseSkill, SkillContext


class NavigateInput(BaseModel):
    """Input contract for the `navigate` skill."""

    url: str
    wait_for: str | None = None


class NavigateOutput(BaseModel):
    """Output contract for browser navigation."""

    url: str
    page_title: str
    message: str


class NavigateSkill(BaseSkill):
    """Navigate the active browser page to a URL."""

    name = "navigate"
    description = "Navigate the browser to a new URL."
    input_schema = NavigateInput
    output_schema = NavigateOutput

    def execute(self, context: SkillContext, payload: NavigateInput) -> NavigateOutput:
        result = context.browser.navigate(payload.url)
        page_state = result.page_state or context.browser.get_page_state()
        return NavigateOutput(
            url=page_state.url,
            page_title=page_state.title,
            message=result.message,
        )
