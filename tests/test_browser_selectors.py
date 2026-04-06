"""Tests for selector generation and target resolution helpers."""

from __future__ import annotations

from browser_agent.browser.page_state import (
    ElementRole,
    FormFieldState,
    InteractiveElementState,
)
from browser_agent.browser.selectors import (
    SelectorStrategy,
    build_form_field_selector_candidates,
    build_selector_candidates,
    resolve_target_candidates,
)


def test_build_selector_candidates_prefers_testid_then_semantics() -> None:
    element = InteractiveElementState(
        name="Submit order",
        tag="button",
        role=ElementRole.BUTTON,
        selector="form > button:nth-of-type(1)",
        text="Submit order",
        attributes={
            "data-testid": "submit-order",
            "id": "submit-button",
            "name": "submit",
        },
        clickable=True,
    )

    candidates = build_selector_candidates(element)

    assert [candidate.strategy for candidate in candidates[:3]] == [
        SelectorStrategy.DATA_TESTID,
        SelectorStrategy.ROLE,
        SelectorStrategy.LABEL,
    ]
    assert candidates[0].value == '[data-testid="submit-order"]'
    assert candidates[-1].strategy == SelectorStrategy.CSS


def test_resolve_target_candidates_uses_observed_element_reference() -> None:
    element = InteractiveElementState(
        element_id="element_submit",
        name="Submit order",
        tag="button",
        role=ElementRole.BUTTON,
        selector="form > button:nth-of-type(1)",
        text="Submit order",
        attributes={"data-testid": "submit-order"},
        clickable=True,
    )

    resolution = resolve_target_candidates(element.element_id, {element.element_id: element})

    assert resolution.used_element_reference is True
    assert resolution.matched_element_id == element.element_id
    assert resolution.candidates[0].value == '[data-testid="submit-order"]'


def test_resolve_target_candidates_keeps_stale_element_reference_structured() -> None:
    resolution = resolve_target_candidates("element_missing", {})

    assert resolution.used_element_reference is True
    assert resolution.matched_element_id == "element_missing"
    assert resolution.candidates == []


def test_resolve_target_candidates_returns_all_candidate_types() -> None:
    """Should return multiple candidate types for an element with rich attributes."""
    element = InteractiveElementState(
        element_id="element_rich",
        name="Search Products",
        tag="input",
        role=ElementRole.INPUT,
        selector="form.search > input",
        text="",
        aria_label="Search products",
        placeholder="Type to search...",
        attributes={
            "data-testid": "search-input",
            "id": "product-search",
            "name": "q",
        },
        input_like=True,
    )

    resolution = resolve_target_candidates("element_rich", {"element_rich": element})

    assert resolution.used_element_reference is True
    strategies = [c.strategy for c in resolution.candidates]

    # Should include high-priority selectors
    assert SelectorStrategy.DATA_TESTID in strategies
    assert SelectorStrategy.ROLE in strategies
    assert SelectorStrategy.ARIA_LABEL in strategies
    assert SelectorStrategy.PLACEHOLDER in strategies


def test_resolve_target_candidates_prioritizes_stable_selectors() -> None:
    """data-testid should be the first/highest priority candidate."""
    element = InteractiveElementState(
        element_id="element_priority",
        name="Add to Cart",
        tag="button",
        role=ElementRole.BUTTON,
        selector="div.product > button",
        text="Add to Cart",
        attributes={
            "data-testid": "add-cart-btn",
            "id": "cart-button",
        },
        clickable=True,
    )

    resolution = resolve_target_candidates("element_priority", {"element_priority": element})

    # First candidate should be data-testid
    assert resolution.candidates[0].strategy == SelectorStrategy.DATA_TESTID
    assert resolution.candidates[0].value == '[data-testid="add-cart-btn"]'
    # Should have high confidence
    assert resolution.candidates[0].confidence >= 0.9


def test_resolve_target_candidates_handles_raw_selector() -> None:
    """Raw selectors not in cache should be treated as-is."""
    resolution = resolve_target_candidates(
        'button[data-testid="direct-selector"]',
        {}  # Empty cache
    )

    assert resolution.used_element_reference is False
    assert resolution.matched_element_id is None
    assert len(resolution.candidates) == 1
    assert resolution.candidates[0].value == 'button[data-testid="direct-selector"]'
    assert resolution.candidates[0].strategy == SelectorStrategy.RAW


def test_resolve_target_candidates_maintains_element_id_format() -> None:
    """element_id that starts with 'element_' but isn't in cache should be marked as stale."""
    resolution = resolve_target_candidates("element_stale_but_formatted", {})

    # Should recognize this as an element reference format
    assert resolution.used_element_reference is True
    assert resolution.matched_element_id == "element_stale_but_formatted"
    assert resolution.candidates == []


def test_build_selector_candidates_skips_fragile_long_text_selectors() -> None:
    """Long search-result snippets should fall back to CSS instead of huge role/text selectors."""
    long_title = (
        "Ёбидоёби - Доставка суши и роллов в Санкт-Петербурге "
        "yobidoyobi.ru https://spb.yobidoyobi.ru"
    )
    element = InteractiveElementState(
        element_id="element_search_result",
        name=long_title,
        tag="a",
        role=ElementRole.LINK,
        selector="div:nth-of-type(1) > div > div > span > a",
        text=long_title,
        clickable=True,
    )

    candidates = build_selector_candidates(element)

    assert [candidate.value for candidate in candidates] == [
        "div:nth-of-type(1) > div > div > span > a"
    ]
    assert candidates[0].strategy == SelectorStrategy.CSS


def test_resolve_target_candidates_preserves_cached_css_fallback_order() -> None:
    """Resolver should reuse cached selector_candidates instead of rebuilding from the primary selector."""
    element = InteractiveElementState(
        element_id="element_cached",
        name="Result",
        tag="a",
        role=ElementRole.LINK,
        selector='role=link[name="Result"]',
        selector_candidates=[
            'role=link[name="Result"]',
            'text="Result"',
            "div:nth-of-type(1) > div > div > span > a",
        ],
        text="Result",
        clickable=True,
    )

    resolution = resolve_target_candidates("element_cached", {"element_cached": element})

    assert [candidate.value for candidate in resolution.candidates] == [
        'role=link[name="Result"]',
        'text="Result"',
        "div:nth-of-type(1) > div > div > span > a",
    ]


def test_build_selector_candidates_skips_volatile_id_attributes() -> None:
    element = InteractiveElementState(
        element_id="element_search",
        name="Search",
        tag="input",
        role=ElementRole.INPUT,
        selector='input[id="mat-input-12345"]',
        attributes={"id": "mat-input-12345", "name": "q"},
        input_like=True,
    )

    candidates = build_selector_candidates(element)

    assert SelectorStrategy.ID not in [c.strategy for c in candidates]
    assert 'input[name="q"]' in [c.value for c in candidates]


def test_build_form_field_selector_candidates_prefer_semantics_over_volatile_id() -> None:
    field = FormFieldState(
        field_id="field_search",
        label="Искать блюда",
        selector='input[id="mat-input-12345"]',
        field_type="text",
        attributes={"id": "mat-input-12345", "type": "text"},
    )

    candidates = build_form_field_selector_candidates(field)

    assert candidates[0].strategy == SelectorStrategy.ROLE
    assert candidates[0].value.startswith('role=textbox[name=')
    assert 'input[id="mat-input-12345"]' in [c.value for c in candidates]
