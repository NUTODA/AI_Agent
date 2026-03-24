"""Selector planning helpers for the future Playwright adapter."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from browser_agent.browser.page_state import InteractiveElementState


class SelectorStrategy(str, Enum):
    """Preferred selector strategies in descending readability order."""

    ROLE = "role"
    LABEL = "label"
    TEXT = "text"
    CSS = "css"


class SelectorCandidate(BaseModel):
    """A possible selector representation for a target element."""

    strategy: SelectorStrategy
    value: str
    confidence: float
    notes: str = ""


def build_selector_candidates(
    element: InteractiveElementState,
) -> list[SelectorCandidate]:
    """Return a small set of selector candidates for later engine use.

    The current foundation does not resolve live Playwright locators yet, but it
    documents the intended selector preference order for future implementation.
    """

    candidates = [
        SelectorCandidate(
            strategy=SelectorStrategy.TEXT,
            value=element.name,
            confidence=0.55,
            notes="Readable default derived from visible element name.",
        ),
        SelectorCandidate(
            strategy=SelectorStrategy.CSS,
            value=element.selector,
            confidence=0.45,
            notes="Fallback selector supplied by the browser engine.",
        ),
    ]
    if element.role.value != SelectorStrategy.CSS.value:
        candidates.insert(
            0,
            SelectorCandidate(
                strategy=SelectorStrategy.ROLE,
                value=f"{element.role.value}:{element.name}",
                confidence=0.8,
                notes="Preferred when stable semantic roles are available.",
            ),
        )
    return candidates
