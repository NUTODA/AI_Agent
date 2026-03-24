"""Browser adapter exports."""

from __future__ import annotations

__all__ = [
    "BrowserEngine",
    "BrowserRuntimeError",
    "PageState",
    "PlaywrightBrowserEngine",
    "StubBrowserEngine",
]


def __getattr__(name: str):
    if name in {
        "BrowserEngine",
        "BrowserRuntimeError",
        "PlaywrightBrowserEngine",
        "StubBrowserEngine",
    }:
        from browser_agent.browser.engine import (
            BrowserEngine,
            BrowserRuntimeError,
            PlaywrightBrowserEngine,
            StubBrowserEngine,
        )

        return {
            "BrowserEngine": BrowserEngine,
            "BrowserRuntimeError": BrowserRuntimeError,
            "PlaywrightBrowserEngine": PlaywrightBrowserEngine,
            "StubBrowserEngine": StubBrowserEngine,
        }[name]
    if name == "PageState":
        from browser_agent.browser.page_state import PageState

        return PageState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
