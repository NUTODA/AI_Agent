"""Deterministic selector helpers for the Playwright browser adapter."""

from __future__ import annotations

import json
from enum import Enum
from typing import Mapping

from pydantic import BaseModel, Field

from browser_agent.browser.page_state import FormFieldState, InteractiveElementState


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


_MAX_SEMANTIC_TEXT_SELECTOR_CHARS = 80


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _looks_volatile_id(value: str | None) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    return normalized.startswith(
        (
            "mat-input-",
            "mat-mdc-",
            "cdk-",
            "headlessui-",
            "react-select-",
            "radix-",
        )
    )


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


def _supports_semantic_text_selector(value: str | None) -> bool:
    normalized = _normalize_text(value)
    return bool(normalized and len(normalized) <= _MAX_SEMANTIC_TEXT_SELECTOR_CHARS)


def _strategy_for_selector_value(value: str) -> SelectorStrategy:
    if value.startswith("role="):
        return SelectorStrategy.ROLE
    if value.startswith("text="):
        return SelectorStrategy.TEXT
    if "[data-testid=" in value:
        return SelectorStrategy.DATA_TESTID
    if "[aria-label=" in value:
        return SelectorStrategy.ARIA_LABEL
    if "[placeholder=" in value:
        return SelectorStrategy.PLACEHOLDER
    if "[name=" in value:
        return SelectorStrategy.NAME
    if "[id=" in value:
        return SelectorStrategy.ID
    return SelectorStrategy.CSS


def _candidates_from_cached_selectors(
    selector_values: list[str],
) -> list[SelectorCandidate]:
    candidates: list[SelectorCandidate] = []
    confidence = 0.98
    for value in selector_values:
        if not value:
            continue
        candidates.append(
            SelectorCandidate(
                strategy=_strategy_for_selector_value(value),
                value=value,
                confidence=max(confidence, 0.35),
                notes="Selector candidate restored from the observed element cache.",
            )
        )
        confidence -= 0.08
    return _dedupe_candidates(candidates)


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
    if (
        playwright_role
        and playwright_role != "other"
        and _supports_semantic_text_selector(accessible_name)
    ):
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
    if _supports_semantic_text_selector(label):
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.LABEL,
                value=_playwright_text_selector(label),
                confidence=0.8,
                notes="Readable text selector derived from the resolved label.",
            )
        )

    text_value = _normalize_text(element.text)
    if (
        _supports_semantic_text_selector(text_value)
        and text_value != label
    ):
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
    if id_attr and not _looks_volatile_id(id_attr):
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


def build_form_field_selector_candidates(
    field: FormFieldState,
) -> list[SelectorCandidate]:
    """Return stable selector candidates for an observed form field."""

    attributes = field.attributes
    candidates: list[SelectorCandidate] = []

    data_testid = _normalize_text(
        str(attributes.get("data-testid") or attributes.get("testid") or "")
    )
    if data_testid:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.DATA_TESTID,
                value='input[data-testid=%s]' % _quote_css_attribute(data_testid),
                confidence=0.98,
                notes="Stable form-field selector from data-testid.",
            )
        )

    aria_label = _normalize_text(str(attributes.get("aria-label") or ""))
    if aria_label:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ARIA_LABEL,
                value=_attr_selector("aria-label", aria_label, "input"),
                confidence=0.9,
                notes="Form field selector derived from aria-label.",
            )
        )

    accessible_name = _normalize_text(field.label or field.placeholder or field.name)
    role = "combobox" if (field.field_type or "").lower() == "select" else "textbox"
    if _supports_semantic_text_selector(accessible_name):
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ROLE,
                value=_playwright_role_selector(role, accessible_name),
                confidence=0.88,
                notes="Semantic role selector for the observed field.",
            )
        )

    placeholder = _normalize_text(
        field.placeholder or str(attributes.get("placeholder") or "")
    )
    if placeholder:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.PLACEHOLDER,
                value=_attr_selector("placeholder", placeholder, "input"),
                confidence=0.8,
                notes="Form field selector using placeholder text.",
            )
        )

    name_attr = _normalize_text(str(attributes.get("name") or field.name or ""))
    if name_attr:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.NAME,
                value=_attr_selector("name", name_attr, "input"),
                confidence=0.74,
                notes="Form field selector using the name attribute.",
            )
        )

    id_attr = _normalize_text(str(attributes.get("id") or ""))
    if id_attr and not _looks_volatile_id(id_attr):
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ID,
                value=_attr_selector("id", id_attr, "input"),
                confidence=0.62,
                notes="Fallback form field selector using a stable id attribute.",
            )
        )

    if field.selector:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.CSS,
                value=field.selector,
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

    cached_selector_values = list(element.selector_candidates or [])
    candidates = (
        _candidates_from_cached_selectors(cached_selector_values)
        if cached_selector_values
        else build_selector_candidates(element)
    )

    return SelectorResolution(
        target=target,
        candidates=candidates,
        matched_element_id=element.element_id,
        used_element_reference=True,
    )
