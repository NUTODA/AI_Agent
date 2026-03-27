"""Contract-level tests for browser page-state normalization."""

from __future__ import annotations

from browser_agent.browser.engine import PlaywrightBrowserEngine
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
