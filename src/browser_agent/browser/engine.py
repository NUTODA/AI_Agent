"""Browser engine interfaces and a stub implementation.

The real Playwright adapter belongs here in a later milestone. The current
foundation ships a small in-memory engine so that the runtime, skills, and CLI
already have a coherent contract surface.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from browser_agent.browser.page_state import PageState


class BrowserOperationResult(BaseModel):
    """Structured outcome of a low-level browser operation."""

    ok: bool = True
    message: str
    page_state: PageState | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrowserEngine(Protocol):
    """Abstract browser engine contract used by runtime skills."""

    def start(self) -> None:
        """Prepare the browser runtime."""

    def stop(self) -> None:
        """Cleanly shut down the browser runtime."""

    def get_page_state(self) -> PageState:
        """Return the current page snapshot."""

    def navigate(self, url: str) -> BrowserOperationResult:
        """Navigate to a new URL."""

    def click(self, selector: str) -> BrowserOperationResult:
        """Click an element identified by the selector."""

    def type_text(
        self,
        selector: str,
        text: str,
        *,
        submit: bool = False,
    ) -> BrowserOperationResult:
        """Type text into the given element."""

    def extract_page_text(self, max_chars: int = 4000) -> str:
        """Extract page text for reasoning or reporting."""


class StubBrowserEngine:
    """In-memory browser stub used until the Playwright adapter is added."""

    def __init__(self, initial_state: PageState | None = None) -> None:
        self._started = False
        self._state = initial_state or PageState()

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def get_page_state(self) -> PageState:
        if not self._started:
            self.start()
        return self._state

    def navigate(self, url: str) -> BrowserOperationResult:
        self._state = PageState(
            url=url,
            title="Stub Browser Page",
            summary="Stub browser navigated to the requested URL.",
            text_excerpt=f"Stub page loaded at {url}.",
        )
        return BrowserOperationResult(
            message=f"Navigated to {url}.",
            page_state=self._state,
        )

    def click(self, selector: str) -> BrowserOperationResult:
        page_state = self.get_page_state().model_copy(
            update={
                "summary": f"Stub browser registered a click on {selector}.",
                "metadata": {"last_clicked_selector": selector},
            },
        )
        self._state = page_state
        return BrowserOperationResult(
            message=f"Clicked {selector}.",
            page_state=page_state,
        )

    def type_text(
        self,
        selector: str,
        text: str,
        *,
        submit: bool = False,
    ) -> BrowserOperationResult:
        page_state = self.get_page_state().model_copy(
            update={
                "summary": f"Stub browser entered text into {selector}.",
                "metadata": {
                    "last_typed_selector": selector,
                    "submitted": submit,
                    "characters_entered": len(text),
                },
            },
        )
        self._state = page_state
        return BrowserOperationResult(
            message=f"Typed into {selector}.",
            page_state=page_state,
        )

    def extract_page_text(self, max_chars: int = 4000) -> str:
        return self.get_page_state().text_excerpt[:max_chars]
