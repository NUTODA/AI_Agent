"""Typed page-state models exposed by the browser adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from browser_agent.runtime.models import AgentObservation, InteractiveElement, new_id


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class ElementRole(str, Enum):
    """Common interactive element roles used in page snapshots."""

    BUTTON = "button"
    LINK = "link"
    INPUT = "input"
    TEXTAREA = "textarea"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    COMBOBOX = "combobox"
    MENU_ITEM = "menuitem"
    OTHER = "other"


class InteractiveElementState(BaseModel):
    """Low-level element information discovered by the browser engine."""

    element_id: str = Field(default_factory=lambda: new_id("element"))
    name: str
    role: ElementRole = ElementRole.OTHER
    selector: str
    visible: bool = True
    enabled: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)

    def to_runtime_model(self) -> InteractiveElement:
        """Convert the browser representation into a runtime observation item."""

        return InteractiveElement(
            element_id=self.element_id,
            label=self.name,
            role=self.role.value,
            selector=self.selector,
            is_visible=self.visible,
            is_enabled=self.enabled,
            attributes=self.attributes,
        )


class PageState(BaseModel):
    """Concise browser snapshot used by observation skills."""

    url: str = "about:blank"
    title: str = "Blank Page"
    summary: str = "No browser page has been observed yet."
    text_excerpt: str = ""
    interactive_elements: list[InteractiveElementState] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=utc_now)

    def to_agent_observation(self) -> AgentObservation:
        """Convert the snapshot to the runtime observation contract."""

        return AgentObservation(
            page_url=self.url,
            page_title=self.title,
            summary=self.summary,
            visible_text_excerpt=self.text_excerpt,
            interactive_elements=[
                element.to_runtime_model() for element in self.interactive_elements
            ],
            metadata=self.metadata,
        )
