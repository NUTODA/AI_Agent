"""Lightweight integration tests for the Playwright browser engine."""

from __future__ import annotations

from urllib.parse import quote

import pytest

from browser_agent.browser.engine import PlaywrightBrowserEngine

HTML_FIXTURE = """
<!doctype html>
<html>
  <head>
    <title>Fixture Page</title>
  </head>
  <body>
    <main>
      <label for="email">Email</label>
      <input
        id="email"
        name="email"
        placeholder="Email address"
        data-testid="email-input"
      />
      <button
        data-testid="submit-button"
        onclick="document.getElementById('status').textContent = 'Clicked';"
      >
        Submit
      </button>
      <p id="status">Idle</p>
    </main>
  </body>
</html>
"""

FIXTURE_URL = f"data:text/html,{quote(HTML_FIXTURE)}"

PRIORITIZATION_FIXTURE = """
<!doctype html>
<html>
  <head>
    <title>Prioritized Elements</title>
  </head>
  <body>
    <header>
      <button>Settings</button>
      <button>Sign in</button>
      <button>Tools</button>
      <button>Voice Search</button>
      <button>Search by image</button>
      <button>Notifications</button>
    </header>
    <main>
      <p>Search results</p>
      <a href="https://spb.yobidoyobi.ru/nabory">Ёбидоёби - наборы роллов</a>
    </main>
  </body>
</html>
"""

PRIORITIZATION_URL = f"data:text/html,{quote(PRIORITIZATION_FIXTURE)}"


def _start_engine(tmp_path) -> PlaywrightBrowserEngine:
    engine = PlaywrightBrowserEngine(
        headless=True,
        artifact_dir=tmp_path / "artifacts",
        capture_screenshots=True,
    )
    try:
        engine.start()
    except Exception as exc:
        pytest.skip(f"Playwright browser unavailable: {exc}")
    return engine


@pytest.mark.integration
def test_playwright_engine_can_navigate_observe_and_interact(tmp_path) -> None:
    engine = _start_engine(tmp_path)

    try:
        navigation = engine.navigate(FIXTURE_URL, wait_for="load")

        assert navigation.ok is True
        assert navigation.page_state is not None
        assert navigation.page_state.title == "Fixture Page"
        assert navigation.page_state.form_fields[0].name == "email"

        elements = engine.get_interactive_elements()
        input_element = next(
            element for element in elements if element.attributes.get("name") == "email"
        )

        type_result = engine.type_text(
            input_element.element_id,
            "test@example.com",
            clear_first=True,
        )

        assert type_result.ok is True

        elements = engine.get_interactive_elements()
        button_element = next(
            element
            for element in elements
            if element.attributes.get("data-testid") == "submit-button"
        )

        click_result = engine.click(button_element.element_id)
        assert click_result.ok is True

        page_state = engine.observe_page()

        assert "Clicked" in page_state.text_excerpt
        assert page_state.artifact_refs
    finally:
        engine.stop()


@pytest.mark.integration
def test_playwright_engine_prioritizes_main_links_over_header_controls(tmp_path) -> None:
    engine = _start_engine(tmp_path)

    try:
        navigation = engine.navigate(PRIORITIZATION_URL, wait_for="load")
        assert navigation.ok is True

        elements = engine.get_interactive_elements(max_elements=3)
        hrefs = [element.attributes.get("href") for element in elements]

        assert "https://spb.yobidoyobi.ru/nabory" in hrefs
        assert hrefs[0] == "https://spb.yobidoyobi.ru/nabory"
    finally:
        engine.stop()
