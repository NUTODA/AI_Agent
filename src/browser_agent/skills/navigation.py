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


class ScrollViewportInput(BaseModel):
    """Input contract for scrolling the page or an element."""

    direction: str = "down"  # up, down, left, right
    amount: int = 500  # pixels
    selector: str | None = None  # if None, scrolls the main viewport


class ScrollViewportOutput(BaseModel):
    """Output contract for scroll execution."""

    direction: str
    amount: int
    target: str | None = None
    scroll_x: int = 0
    scroll_y: int = 0
    message: str
    page_title: str | None = None
    observation: AgentObservation | None = None


class ScrollViewportSkill(BaseSkill):
    """Scroll the page viewport or a specific element."""

    name = "scroll_viewport"
    description = "Scroll the page or a specific element up, down, left, or right by a specified amount of pixels."
    input_schema = ScrollViewportInput
    output_schema = ScrollViewportOutput

    def execute(
        self,
        context: SkillContext,
        payload: ScrollViewportInput,
    ) -> ScrollViewportOutput:
        try:
            result = raise_for_browser_result(
                context.browser.scroll_viewport(
                    direction=payload.direction,
                    amount=payload.amount,
                    target=payload.selector,
                ),
                default_error_code="scroll_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message=f"Failed to scroll {payload.direction}.",
                error_code="scroll_failed",
                data={
                    "direction": payload.direction,
                    "amount": payload.amount,
                    "target": payload.selector,
                    "details": str(exc),
                },
            ) from exc
        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )
        metadata = result.metadata or {}
        return ScrollViewportOutput(
            direction=payload.direction,
            amount=payload.amount,
            target=payload.selector,
            scroll_x=metadata.get("scroll_x", 0),
            scroll_y=metadata.get("scroll_y", 0),
            message=result.message,
            page_title=result.page_state.title if result.page_state else None,
            observation=observation,
        )
