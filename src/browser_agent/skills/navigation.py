"""Navigation-related runtime skills."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from browser_agent.runtime.models import AgentObservation
from browser_agent.skills.base import (
    BaseSkill,
    SkillContext,
    SkillExecutionError,
    raise_for_browser_result,
)


class NavigateInput(BaseModel):
    """Input contract for the `navigate` skill."""

    url: str
    wait_for: Literal["load", "domcontentloaded", "networkidle", "commit"] | None = None


class NavigateOutput(BaseModel):
    """Output contract for browser navigation."""

    url: str
    page_title: str
    message: str
    observation: AgentObservation


class NavigateSkill(BaseSkill):
    """Navigate the active browser page to a URL."""

    name = "navigate"
    description = "Navigate the browser to a new URL."
    input_schema = NavigateInput
    output_schema = NavigateOutput

    def execute(self, context: SkillContext, payload: NavigateInput) -> NavigateOutput:
        try:
            result = raise_for_browser_result(
                context.browser.navigate(payload.url, wait_for=payload.wait_for),
                default_error_code="navigate_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to navigate the browser.",
                error_code="navigate_failed",
                data={"url": payload.url, "details": str(exc)},
            ) from exc
        page_state = result.page_state or context.browser.observe_page()
        return NavigateOutput(
            url=page_state.url,
            page_title=page_state.title,
            message=result.message,
            observation=page_state.to_agent_observation(),
        )
