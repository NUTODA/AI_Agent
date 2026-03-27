"""Contract-level tests for browser page-state normalization."""

from __future__ import annotations

import pytest

from browser_agent.browser.engine import BrowserRuntimeError, PlaywrightBrowserEngine
from browser_agent.browser.page_state import (
    ElementRole,
    FormFieldState,
    InteractiveElementState,
    PageState,
)


def test_page_state_to_agent_observation_preserves_browser_summary_fields() -> None:
    page_state = PageState(
        url="https://example.com/login",
        title="Login",
        summary="Observed login form.",
        text_excerpt="Please sign in to continue.",
        interactive_elements=[
            InteractiveElementState(
                element_id="element_login_button",
                name="Sign in",
                tag="button",
                role=ElementRole.BUTTON,
                selector='[data-testid="submit-button"]',
                selector_candidates=[
                    '[data-testid="submit-button"]',
                    'role=button[name="Sign in"]',
                ],
                text="Sign in",
                clickable=True,
                attributes={"data-testid": "submit-button"},
            )
        ],
        form_fields=[
            FormFieldState(
                field_id="field_email",
                label="Email",
                name="email",
                selector='input[name="email"]',
                field_type="email",
                placeholder="Email address",
                required=True,
                filled=False,
            )
        ],
        observation_errors=["Minor DOM parsing warning."],
        artifact_refs=["artifacts/observe_page.png"],
        metadata={"document_ready_state": "complete"},
    )

    observation = page_state.to_agent_observation()

    assert observation.page_url == "https://example.com/login"
    assert observation.page_title == "Login"
    assert observation.visible_text_excerpt == "Please sign in to continue."
    assert observation.observation_errors == ["Minor DOM parsing warning."]
    assert observation.artifact_refs == ["artifacts/observe_page.png"]
    assert observation.metadata["document_ready_state"] == "complete"
    assert observation.interactive_elements[0].tag == "button"
    assert observation.interactive_elements[0].selector_candidates == [
        '[data-testid="submit-button"]',
        'role=button[name="Sign in"]',
    ]
    assert observation.interactive_elements[0].is_clickable is True
    assert observation.form_fields[0].placeholder == "Email address"
    assert observation.form_fields[0].required is True


def test_engine_builds_stable_snapshot_ids_for_same_element_signature() -> None:
    engine = PlaywrightBrowserEngine()

    raw_element = {
        "name": "Buy now",
        "tag": "button",
        "role": "button",
        "selector": '[data-testid="buy-now"]',
        "text": "Buy now",
        "clickable": True,
        "attributes": {"data-testid": "buy-now"},
    }
    raw_field = {
        "label": "Email",
        "name": "email",
        "selector": 'input[name="email"]',
        "field_type": "email",
        "attributes": {"name": "email", "type": "email"},
    }

    first_element = engine._build_interactive_element(raw_element)
    second_element = engine._build_interactive_element(raw_element)
    first_field = engine._build_form_field(raw_field)
    second_field = engine._build_form_field(raw_field)

    assert first_element.element_id == second_element.element_id
    assert first_field.field_id == second_field.field_id


def test_engine_retries_transient_observation_errors() -> None:
    engine = PlaywrightBrowserEngine()

    class FakePage:
        def __init__(self) -> None:
            self.url = "https://example.com/catalog"
            self.evaluate_calls = 0
            self.wait_for_load_state_calls = 0
            self.wait_for_timeout_calls = 0

        def evaluate(self, script, args):
            del script, args
            self.evaluate_calls += 1
            if self.evaluate_calls == 1:
                raise RuntimeError(
                    "Execution context was destroyed, most likely because of a navigation."
                )
            return {
                "url": self.url,
                "title": "Catalog",
                "text_excerpt": "Affordable sets are visible.",
                "interactive_elements": [],
                "form_fields": [],
                "metadata": {"document_ready_state": "complete"},
            }

        def title(self) -> str:
            return "Catalog"

        def wait_for_load_state(self, state: str, timeout: int) -> None:
            assert state == "domcontentloaded"
            assert timeout > 0
            self.wait_for_load_state_calls += 1

        def wait_for_timeout(self, timeout_ms: int) -> None:
            assert timeout_ms > 0
            self.wait_for_timeout_calls += 1

    fake_page = FakePage()
    engine.get_page = lambda: fake_page  # type: ignore[method-assign]

    page_state = engine.observe_page()

    assert fake_page.evaluate_calls == 2
    assert fake_page.wait_for_load_state_calls == 1
    assert fake_page.wait_for_timeout_calls == 1
    assert page_state.title == "Catalog"
    assert page_state.url == "https://example.com/catalog"
    assert page_state.metadata["observation_retry_count"] == 1


def test_engine_preserves_non_transient_observation_failures() -> None:
    engine = PlaywrightBrowserEngine()

    class FakePage:
        url = "https://example.com/catalog"

        def evaluate(self, script, args):
            del script, args
            raise RuntimeError("ReferenceError: snapshot helper is not defined")

        def title(self) -> str:
            return "Catalog"

    fake_page = FakePage()
    engine.get_page = lambda: fake_page  # type: ignore[method-assign]

    with pytest.raises(BrowserRuntimeError) as exc_info:
        engine.observe_page()

    assert exc_info.value.code == "page_observation_failed"
    assert "snapshot helper is not defined" in exc_info.value.metadata["details"]
    assert exc_info.value.metadata["retry_count"] == 0
