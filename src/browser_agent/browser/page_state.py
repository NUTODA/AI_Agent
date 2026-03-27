"""Typed page-state models exposed by the browser adapter."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from browser_agent.runtime.models import (
    AgentObservation,
    FormFieldSummary,
    InteractiveElement,
    new_id,
)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def stable_snapshot_id(prefix: str, *, signature: dict[str, Any]) -> str:
    """Build a deterministic identifier for a browser snapshot entity."""

    digest = hashlib.sha1(
        json.dumps(signature, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{prefix}_{digest[:12]}"


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
    tag: str = "div"
    role: ElementRole = ElementRole.OTHER
    selector: str
    selector_candidates: list[str] = Field(default_factory=list)
    text: str | None = None
    aria_label: str | None = None
    placeholder: str | None = None
    visible: bool = True
    enabled: bool = True
    clickable: bool = False
    input_like: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)

    def to_runtime_model(self) -> InteractiveElement:
        """Convert the browser representation into a runtime observation item."""

        return InteractiveElement(
            element_id=self.element_id,
            label=self.name,
            tag=self.tag,
            role=self.role.value,
            text=self.text,
            aria_label=self.aria_label,
            placeholder=self.placeholder,
            selector=self.selector,
            selector_candidates=self.selector_candidates,
            is_visible=self.visible,
            is_enabled=self.enabled,
            is_clickable=self.clickable,
            is_input=self.input_like,
            attributes=self.attributes,
        )


class FormFieldState(BaseModel):
    """Compact input summary used in browser observations."""

    field_id: str = Field(default_factory=lambda: new_id("field"))
    label: str | None = None
    name: str | None = None
    selector: str
    field_type: str | None = None
    placeholder: str | None = None
    required: bool = False
    filled: bool = False
    visible: bool = True
    enabled: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)

    def to_runtime_model(self) -> FormFieldSummary:
        """Convert the browser representation into a runtime observation item."""

        return FormFieldSummary(
            field_id=self.field_id,
            label=self.label,
            name=self.name,
            selector=self.selector,
            field_type=self.field_type,
            placeholder=self.placeholder,
            required=self.required,
            filled=self.filled,
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
    form_fields: list[FormFieldState] = Field(default_factory=list)
    observation_errors: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
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
            form_fields=[field.to_runtime_model() for field in self.form_fields],
            observation_errors=self.observation_errors,
            artifact_refs=self.artifact_refs,
            metadata=self.metadata,
            observed_at=self.captured_at,
        )
