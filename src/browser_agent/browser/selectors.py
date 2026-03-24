"""Deterministic selector helpers for the Playwright browser adapter."""

from __future__ import annotations

import json
from enum import Enum
from typing import Mapping

from pydantic import BaseModel, Field

from browser_agent.browser.page_state import InteractiveElementState


class SelectorStrategy(str, Enum):
    """Preferred selector strategies in descending readability order."""

    DATA_TESTID = "data-testid"
    ROLE = "role"
    ARIA_LABEL = "aria-label"
    LABEL = "label"
    TEXT = "text"
    PLACEHOLDER = "placeholder"
    NAME = "name"
    ID = "id"
    CSS = "css"
    RAW = "raw"


class SelectorCandidate(BaseModel):
    """A possible selector representation for a target element."""

    strategy: SelectorStrategy
    value: str
    confidence: float
    notes: str = ""


class SelectorResolution(BaseModel):
    """Resolved selector candidates for a raw selector or element reference."""

    target: str
    candidates: list[SelectorCandidate] = Field(default_factory=list)
    matched_element_id: str | None = None
    used_element_reference: bool = False


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _quote_css_attribute(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _attr_selector(attribute: str, value: str, tag: str | None = None) -> str:
    prefix = tag if tag else ""
    return f'{prefix}[{attribute}={_quote_css_attribute(value)}]'


def _playwright_text_selector(text: str) -> str:
    return f"text={json.dumps(text)}"


def _playwright_role_selector(role: str, name: str) -> str:
    return f"role={role}[name={json.dumps(name)}]"


def _dedupe_candidates(
    candidates: list[SelectorCandidate],
) -> list[SelectorCandidate]:
    deduped: list[SelectorCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.value in seen:
            continue
        seen.add(candidate.value)
        deduped.append(candidate)
    return deduped


def build_selector_candidates(
    element: InteractiveElementState,
) -> list[SelectorCandidate]:
    """Return deterministic selector candidates in strict priority order."""

    attributes = element.attributes
    candidates: list[SelectorCandidate] = []

    data_testid = _normalize_text(
        str(attributes.get("data-testid") or attributes.get("testid") or "")
    )
    if data_testid:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.DATA_TESTID,
                value=_attr_selector("data-testid", data_testid),
                confidence=0.98,
                notes="Highest-priority stable selector from data-testid.",
            )
        )

    accessible_name = (
        _normalize_text(element.name)
        or _normalize_text(element.aria_label)
        or _normalize_text(element.text)
        or _normalize_text(element.placeholder)
    )
    role = element.role.value if hasattr(element.role, "value") else str(element.role)
    playwright_role = {"input": "textbox", "textarea": "textbox"}.get(role, role)
    if playwright_role and playwright_role != "other" and accessible_name:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ROLE,
                value=_playwright_role_selector(playwright_role, accessible_name),
                confidence=0.93,
                notes="Semantic role selector with accessible name.",
            )
        )

    aria_label = _normalize_text(element.aria_label or attributes.get("aria-label"))
    if aria_label:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ARIA_LABEL,
                value=_attr_selector("aria-label", aria_label, element.tag),
                confidence=0.88,
                notes="ARIA label selector derived from accessibility metadata.",
            )
        )

    label = _normalize_text(element.name)
    if label:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.LABEL,
                value=_playwright_text_selector(label),
                confidence=0.8,
                notes="Readable text selector derived from the resolved label.",
            )
        )

    text_value = _normalize_text(element.text)
    if text_value and text_value != label:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.TEXT,
                value=_playwright_text_selector(text_value),
                confidence=0.74,
                notes="Visible text selector fallback.",
            )
        )

    placeholder = _normalize_text(element.placeholder or attributes.get("placeholder"))
    if placeholder:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.PLACEHOLDER,
                value=_attr_selector("placeholder", placeholder, element.tag),
                confidence=0.7,
                notes="Useful for input-like controls with placeholders.",
            )
        )

    name_attr = _normalize_text(str(attributes.get("name") or ""))
    if name_attr:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.NAME,
                value=_attr_selector("name", name_attr, element.tag),
                confidence=0.65,
                notes="Fallback selector using the name attribute.",
            )
        )

    id_attr = _normalize_text(str(attributes.get("id") or ""))
    if id_attr:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ID,
                value=_attr_selector("id", id_attr, element.tag),
                confidence=0.62,
                notes="Fallback selector using the id attribute.",
            )
        )

    if element.selector:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.CSS,
                value=element.selector,
                confidence=0.45,
                notes="Last-resort CSS fallback generated from the DOM path.",
            )
        )

    return _dedupe_candidates(candidates)


def primary_selector_for(element: InteractiveElementState) -> str:
    """Return the highest-priority selector for the given element."""

    candidates = build_selector_candidates(element)
    if not candidates:
        return element.selector
    return candidates[0].value


def resolve_target_candidates(
    target: str,
    element_cache: Mapping[str, InteractiveElementState],
) -> SelectorResolution:
    """Resolve either a raw selector or an observed element reference."""

    element = element_cache.get(target)
    if element is None:
        if target.startswith("element_"):
            return SelectorResolution(
                target=target,
                matched_element_id=target,
                used_element_reference=True,
            )
        return SelectorResolution(
            target=target,
            candidates=[
                SelectorCandidate(
                    strategy=SelectorStrategy.RAW,
                    value=target,
                    confidence=1.0,
                    notes="Target provided directly as a selector string.",
                )
            ],
        )

    return SelectorResolution(
        target=target,
        candidates=build_selector_candidates(element),
        matched_element_id=element.element_id,
        used_element_reference=True,
    )
