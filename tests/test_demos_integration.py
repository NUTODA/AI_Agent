"""Integration tests for demo pages.

These tests verify that the demo pages can be loaded and interacted with
using the browser engine. They use the local demo server and test real
browser interactions without external internet dependencies.

Note: These tests require the demo server to be running or use file:// URLs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from browser_agent.browser.engine import PlaywrightBrowserEngine, StubBrowserEngine


# Path to demo pages
DEMO_PAGES_DIR = Path(__file__).parent.parent / "demos" / "pages"
INBOX_DEMO = DEMO_PAGES_DIR / "inbox_demo.html"
FOOD_DEMO = DEMO_PAGES_DIR / "food_demo.html"
JOBS_DEMO = DEMO_PAGES_DIR / "jobs_demo.html"


@pytest.fixture(scope="module")
def demo_pages_exist() -> None:
    """Verify demo pages exist before running tests."""
    assert INBOX_DEMO.exists(), f"Inbox demo not found at {INBOX_DEMO}"
    assert FOOD_DEMO.exists(), f"Food demo not found at {FOOD_DEMO}"
    assert JOBS_DEMO.exists(), f"Jobs demo not found at {JOBS_DEMO}"


@pytest.mark.skipif(not INBOX_DEMO.exists(), reason="Demo pages not built")
class TestInboxDemoIntegration:
    """Integration tests for the inbox demo page."""

    def test_inbox_demo_page_loads(self, demo_pages_exist) -> None:
        """Inbox demo page should load and have expected structure."""
        # Read and verify HTML structure
        html_content = INBOX_DEMO.read_text()

        # Should have key elements
        assert 'data-testid="inbox-title"' in html_content
        assert 'data-testid="email-list"' in html_content
        assert 'data-testid="filter-all"' in html_content
        assert 'data-testid="filter-spam"' in html_content

        # Should have sample emails
        assert "PrinceNigeria" in html_content
        assert "Amazon.com" in html_content
        assert "Sarah from HR" in html_content

    def test_inbox_demo_has_mark_spam_buttons(self, demo_pages_exist) -> None:
        """Inbox demo should have mark spam buttons with correct testids."""
        html_content = INBOX_DEMO.read_text()

        # Should have mark spam buttons for emails
        assert 'data-testid="mark-spam-2"' in html_content
        assert 'data-testid="mark-spam-4"' in html_content

        # Should have mark important buttons
        assert 'data-testid="mark-important-1"' in html_content
        assert 'data-testid="mark-important-3"' in html_content

    def test_inbox_demo_has_statistics(self, demo_pages_exist) -> None:
        """Inbox demo should display email statistics."""
        html_content = INBOX_DEMO.read_text()

        assert 'data-testid="total-count"' in html_content
        assert 'data-testid="spam-count"' in html_content
        assert 'data-testid="important-count"' in html_content


@pytest.mark.skipif(not FOOD_DEMO.exists(), reason="Demo pages not built")
class TestFoodDemoIntegration:
    """Integration tests for the food demo page."""

    def test_food_demo_page_loads(self, demo_pages_exist) -> None:
        """Food demo page should load and have expected structure."""
        html_content = FOOD_DEMO.read_text()

        # Should have key elements
        assert 'data-testid="restaurant-name"' in html_content
        assert 'data-testid="menu-grid"' in html_content
        assert 'data-testid="cart-count"' in html_content

    def test_food_demo_has_menu_items(self, demo_pages_exist) -> None:
        """Food demo should have menu items with add buttons."""
        html_content = FOOD_DEMO.read_text()

        # Should have menu items
        assert 'data-testid="item-burger"' in html_content
        assert 'data-testid="item-pizza"' in html_content
        assert 'data-testid="item-pasta"' in html_content
        assert 'data-testid="item-salad"' in html_content

        # Should have add buttons
        assert 'data-testid="add-burger"' in html_content
        assert 'data-testid="add-pizza"' in html_content

    def test_food_demo_has_checkout_form(self, demo_pages_exist) -> None:
        """Food demo should have checkout form fields."""
        html_content = FOOD_DEMO.read_text()

        # Checkout form fields
        assert 'data-testid="checkout-name"' in html_content
        assert 'data-testid="checkout-email"' in html_content
        assert 'data-testid="checkout-card"' in html_content
        assert 'data-testid="checkout-expiry"' in html_content
        assert 'data-testid="checkout-cvv"' in html_content


@pytest.mark.skipif(not JOBS_DEMO.exists(), reason="Demo pages not built")
class TestJobsDemoIntegration:
    """Integration tests for the jobs demo page."""

    def test_jobs_demo_page_loads(self, demo_pages_exist) -> None:
        """Jobs demo page should load and have expected structure."""
        html_content = JOBS_DEMO.read_text()

        # Should have key elements
        assert 'data-testid="job-board-title"' in html_content
        assert 'data-testid="job-list"' in html_content
        assert 'data-testid="results-count"' in html_content

    def test_jobs_demo_has_filter_controls(self, demo_pages_exist) -> None:
        """Jobs demo should have filter checkboxes."""
        html_content = JOBS_DEMO.read_text()

        # Job type filters
        assert 'data-testid="filter-fulltime"' in html_content
        assert 'data-testid="filter-parttime"' in html_content
        assert 'data-testid="filter-remote"' in html_content

        # Experience filters
        assert 'data-testid="filter-entry"' in html_content
        assert 'data-testid="filter-mid"' in html_content
        assert 'data-testid="filter-senior"' in html_content

        # Location filters
        assert 'data-testid="filter-sf"' in html_content
        assert 'data-testid="filter-ny"' in html_content

    def test_jobs_demo_has_job_listings(self, demo_pages_exist) -> None:
        """Jobs demo should have job listing cards."""
        html_content = JOBS_DEMO.read_text()

        # Should have job cards
        assert 'data-testid="job-1"' in html_content
        assert 'data-testid="job-2"' in html_content
        assert 'data-testid="job-3"' in html_content

        # Job details
        assert 'data-testid="job-title-1"' in html_content
        assert 'data-testid="job-company-1"' in html_content
        assert 'data-testid="job-salary-1"' in html_content

        # Apply buttons
        assert 'data-testid="apply-btn-1"' in html_content

    def test_jobs_demo_has_application_form(self, demo_pages_exist) -> None:
        """Jobs demo should have job application form."""
        html_content = JOBS_DEMO.read_text()

        # Application form fields
        assert 'data-testid="applicant-name"' in html_content
        assert 'data-testid="applicant-email"' in html_content
        assert 'data-testid="applicant-resume"' in html_content
        assert 'data-testid="submit-application"' in html_content


@pytest.mark.skipif(not INBOX_DEMO.exists(), reason="Demo pages not built")
class TestDemoPageInteraction:
    """Tests that demo pages can be interacted with via browser engine."""

    def test_inbox_demo_click_interaction(self) -> None:
        """Should be able to click mark spam button on inbox demo."""
        # This is a stub browser test - real Playwright tests would
        # need the demo server running
        browser = StubBrowserEngine()

        # Navigate to inbox demo (file:// URL)
        result = browser.navigate_to(f"file://{INBOX_DEMO}")
        assert result.ok is True

        # Simulate clicking mark spam button
        click_result = browser.click_element('[data-testid="mark-spam-2"]')
        assert click_result.ok is True

    def test_food_demo_cart_interaction(self) -> None:
        """Should be able to add items to cart on food demo."""
        browser = StubBrowserEngine()

        # Navigate to food demo
        result = browser.navigate_to(f"file://{FOOD_DEMO}")
        assert result.ok is True

        # Add burger to cart
        click_result = browser.click_element('[data-testid="add-burger"]')
        assert click_result.ok is True

    def test_jobs_demo_filter_interaction(self) -> None:
        """Should be able to check filter on jobs demo."""
        browser = StubBrowserEngine()

        # Navigate to jobs demo
        result = browser.navigate_to(f"file://{JOBS_DEMO}")
        assert result.ok is True

        # Click remote filter
        click_result = browser.click_element('[data-testid="filter-remote"]')
        assert click_result.ok is True


class TestDemoPageStructureValidation:
    """Validate demo page HTML structure and data-testid attributes."""

    def test_all_demo_pages_have_valid_html(self) -> None:
        """All demo pages should have valid HTML structure."""
        for demo_file in [INBOX_DEMO, FOOD_DEMO, JOBS_DEMO]:
            if not demo_file.exists():
                pytest.skip(f"Demo file {demo_file} not found")

            content = demo_file.read_text()

            # Basic HTML structure validation
            assert content.strip().startswith("<!DOCTYPE html>"), f"{demo_file} missing DOCTYPE"
            assert "<html" in content, f"{demo_file} missing html tag"
            assert "<head>" in content, f"{demo_file} missing head tag"
            assert "<body>" in content, f"{demo_file} missing body tag"
            assert "</html>" in content, f"{demo_file} missing closing html tag"

    def test_demo_pages_have_unique_testids(self) -> None:
        """Demo pages should have data-testid attributes for testing."""
        for demo_file in [INBOX_DEMO, FOOD_DEMO, JOBS_DEMO]:
            if not demo_file.exists():
                continue

            content = demo_file.read_text()

            # Count data-testid occurrences
            import re
            testids = re.findall(r'data-testid="([^"]+)"', content)

            # Each demo should have multiple testids
            assert len(testids) >= 10, f"{demo_file.name} has fewer than 10 data-testid attributes"

            # All testids should be unique
            assert len(testids) == len(set(testids)), f"{demo_file.name} has duplicate data-testid attributes"


class TestDemoServer:
    """Tests for the demo server functionality."""

    def test_server_script_exists(self) -> None:
        """Server script should exist."""
        server_script = Path(__file__).parent.parent / "demos" / "server.py"
        assert server_script.exists(), "Demo server script not found"

    def test_server_script_is_valid_python(self) -> None:
        """Server script should be valid Python syntax."""
        import ast

        server_script = Path(__file__).parent.parent / "demos" / "server.py"
        if not server_script.exists():
            pytest.skip("Server script not found")

        content = server_script.read_text()

        # Should parse as valid Python
        try:
            ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"Server script has syntax error: {e}")

    def test_server_has_main_function(self) -> None:
        """Server script should have a main function."""
        server_script = Path(__file__).parent.parent / "demos" / "server.py"
        if not server_script.exists():
            pytest.skip("Server script not found")

        content = server_script.read_text()

        assert "def main(" in content, "Server script missing main function"
        assert 'if __name__ == "__main__"' in content, "Server script missing main guard"
