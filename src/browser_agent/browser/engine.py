"""Browser engine interfaces and Playwright-backed implementations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from browser_agent.browser.page_state import (
    ElementRole,
    FormFieldState,
    InteractiveElementState,
    PageState,
    stable_snapshot_id,
)
from browser_agent.browser.selectors import (
    build_selector_candidates,
    resolve_target_candidates,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright


ALLOWED_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}
ALLOWED_URL_SCHEMES = {"http", "https", "file", "data", "about"}


def _scroll_coord_to_int(value: Any) -> int:
    """Normalize browser scroll coordinates (often float) to int for pydantic schemas."""

    if value is None:
        return 0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0

PAGE_SNAPSHOT_SCRIPT = """
([maxTextChars, maxElements]) => {
  const normalizeText = (value) => {
    if (typeof value !== "string") {
      return "";
    }
    return value.replace(/\\s+/g, " ").trim();
  };

  const isVisible = (element) => {
    if (!element || !element.isConnected) {
      return false;
    }
    const style = window.getComputedStyle(element);
    if (!style) {
      return false;
    }
    if (
      style.display === "none" ||
      style.visibility === "hidden" ||
      style.opacity === "0"
    ) {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const isEnabled = (element) =>
    !element.hasAttribute("disabled") &&
    element.getAttribute("aria-disabled") !== "true";

  const hasClosest = (element, selector) => {
    try {
      return Boolean(element.closest(selector));
    } catch {
      return false;
    }
  };

  const cleanObject = (value) =>
    Object.fromEntries(
      Object.entries(value).filter(([, item]) => item !== null && item !== "")
    );

  const cssPath = (element) => {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return "";
    }
    const parts = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 5) {
      const tag = current.tagName.toLowerCase();
      if (current.id) {
        parts.unshift(`${tag}[id="${current.id.replace(/"/g, '\\"')}"]`);
        break;
      }
      const parent = current.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const siblings = Array.from(parent.children).filter(
        (candidate) => candidate.tagName === current.tagName
      );
      if (siblings.length === 1) {
        parts.unshift(tag);
      } else {
        const index = siblings.indexOf(current) + 1;
        parts.unshift(`${tag}:nth-of-type(${index})`);
      }
      current = parent;
    }
    return parts.join(" > ");
  };

  const textContent = (element) =>
    normalizeText(element.innerText || element.textContent || "");

  const labelledByText = (element) => {
    const labelledBy = normalizeText(element.getAttribute("aria-labelledby"));
    if (!labelledBy) {
      return "";
    }
    return normalizeText(
      labelledBy
        .split(/\\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((node) => node.innerText || node.textContent || "")
        .join(" ")
    );
  };

  const labelText = (element) => {
    if (element.labels && element.labels.length > 0) {
      const label = normalizeText(
        Array.from(element.labels)
          .map((node) => node.innerText || node.textContent || "")
          .join(" ")
      );
      if (label) {
        return label;
      }
    }
    const ariaLabel = normalizeText(element.getAttribute("aria-label"));
    if (ariaLabel) {
      return ariaLabel;
    }
    const labelledBy = labelledByText(element);
    if (labelledBy) {
      return labelledBy;
    }
    const placeholder = normalizeText(element.getAttribute("placeholder"));
    if (placeholder) {
      return placeholder;
    }
    const text = textContent(element);
    if (text) {
      return text;
    }
    return (
      normalizeText(element.getAttribute("name")) ||
      normalizeText(element.getAttribute("id")) ||
      normalizeText(element.getAttribute("value")) ||
      element.tagName.toLowerCase()
    );
  };

  const roleFor = (element) => {
    const explicitRole = normalizeText(element.getAttribute("role"));
    if (explicitRole) {
      return explicitRole;
    }
    const tag = element.tagName.toLowerCase();
    const type = normalizeText(element.getAttribute("type"));
    if (tag === "button") {
      return "button";
    }
    if (tag === "a") {
      return "link";
    }
    if (tag === "textarea") {
      return "textarea";
    }
    if (tag === "select") {
      return "combobox";
    }
    if (tag === "input") {
      if (type === "checkbox") {
        return "checkbox";
      }
      if (type === "radio") {
        return "radio";
      }
      return "input";
    }
    return "other";
  };

  const isInputLike = (element, tag, role) =>
    ["input", "textarea", "select"].includes(tag) ||
    ["input", "textarea", "checkbox", "radio", "combobox"].includes(role) ||
    element.getAttribute("contenteditable") === "true";

  const isClickable = (element, tag, role) =>
    ["button", "a"].includes(tag) ||
    ["button", "link", "menuitem", "checkbox", "radio"].includes(role) ||
    element.hasAttribute("onclick");

  const candidateSelector = [
    "button",
    "a[href]",
    "input",
    "textarea",
    "select",
    "[role='button']",
    "[role='link']",
    "[role='menuitem']",
    "[role='checkbox']",
    "[role='radio']",
    "[role='combobox']",
    "[contenteditable='true']",
    "[tabindex]:not([tabindex='-1'])"
  ].join(", ");

  const scoreInteractiveElement = (element, tag, role, text, ariaLabel, attrs) => {
    let score = 0;
    const label = normalizeText(
      [text, ariaLabel, attrs.name, attrs.placeholder].filter(Boolean).join(" ")
    ).toLowerCase();
    const href = normalizeText(attrs.href);

    if (tag === "a" || role === "link") {
      score += 8;
    }
    if (href && !href.startsWith("#") && !href.startsWith("javascript:")) {
      score += 12;
    }
    if (hasClosest(element, "main, article, [role='main']")) {
      score += 10;
    }
    if (
      hasClosest(
        element,
        "header, nav, footer, [role='navigation'], [role='banner'], [role='contentinfo']"
      )
    ) {
      score -= 12;
    }
    if (text && text.length >= 18) {
      score += 2;
    }
    if (attrs["data-testid"]) {
      score += 1;
    }
    if (/\\+\\d+/.test(label)) {
      score -= 4;
    }
    if (
      /^(settings|tools|sign in|voice search|search by image)$/i.test(label) ||
      /^(настройки|инструменты|войти|голосовой поиск|поиск по картинке)$/i.test(label)
    ) {
      score -= 6;
    }
    return score;
  };

  const interactiveElements = [];
  const seen = new Set();
  let discoveryIndex = 0;
  for (const element of document.querySelectorAll(candidateSelector)) {
    if (seen.has(element)) {
      continue;
    }
    seen.add(element);
    if (!isVisible(element)) {
      continue;
    }
    const tag = element.tagName.toLowerCase();
    const role = roleFor(element);
    const text = textContent(element);
    const ariaLabel = normalizeText(element.getAttribute("aria-label"));
    const placeholder = normalizeText(element.getAttribute("placeholder"));
    const name = labelText(element);
    const attrs = cleanObject({
      id: normalizeText(element.getAttribute("id")),
      name: normalizeText(element.getAttribute("name")),
      "data-testid": normalizeText(element.getAttribute("data-testid")),
      "aria-label": ariaLabel,
      placeholder,
      type: normalizeText(element.getAttribute("type")),
      href: normalizeText(element.getAttribute("href"))
    });
    interactiveElements.push({
      _priority: scoreInteractiveElement(element, tag, role, text, ariaLabel, attrs),
      _index: discoveryIndex++,
      name,
      tag,
      role,
      text: text || null,
      aria_label: ariaLabel || null,
      placeholder: placeholder || null,
      selector: cssPath(element),
      visible: true,
      enabled: isEnabled(element),
      clickable: isClickable(element, tag, role),
      input_like: isInputLike(element, tag, role),
      attributes: attrs
    });
  }

  interactiveElements.sort((left, right) => {
    if (right._priority !== left._priority) {
      return right._priority - left._priority;
    }
    return left._index - right._index;
  });
  const prioritizedInteractiveElements = interactiveElements
    .slice(0, maxElements)
    .map(({ _priority, _index, ...item }) => item);

  const formFields = [];
  for (const element of document.querySelectorAll("input, textarea, select, [contenteditable='true']")) {
    if (!isVisible(element)) {
      continue;
    }
    const tag = element.tagName.toLowerCase();
    const type = normalizeText(element.getAttribute("type")) || tag;
    const value =
      type === "password"
        ? ""
        : normalizeText(
            tag === "select"
              ? element.value || ""
              : element.value || element.textContent || ""
          );
    formFields.push({
      label: labelText(element) || null,
      name: normalizeText(element.getAttribute("name")) || null,
      selector: cssPath(element),
      field_type: type,
      placeholder: normalizeText(element.getAttribute("placeholder")) || null,
      required: element.required === true || element.getAttribute("aria-required") === "true",
      filled:
        type === "checkbox" || type === "radio"
          ? Boolean(element.checked)
          : Boolean(value),
      visible: true,
      enabled: isEnabled(element),
      attributes: cleanObject({
        id: normalizeText(element.getAttribute("id")),
        name: normalizeText(element.getAttribute("name")),
        "data-testid": normalizeText(element.getAttribute("data-testid")),
        autocomplete: normalizeText(element.getAttribute("autocomplete")),
        type
      })
    });
  }

  const bodyText = normalizeText(document.body ? document.body.innerText : "");
  return {
    url: window.location.href,
    title: document.title || "Untitled Page",
    text_excerpt: bodyText.slice(0, maxTextChars),
    interactive_elements: prioritizedInteractiveElements,
    form_fields: formFields,
    metadata: {
      visible_text_length: bodyText.length,
      interactive_count: prioritizedInteractiveElements.length,
      form_field_count: formFields.length,
      document_ready_state: document.readyState
    }
  };
}
"""


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class BrowserRuntimeError(RuntimeError):
    """Raised when the Playwright runtime cannot be prepared or accessed."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = metadata or {}


class BrowserOperationResult(BaseModel):
    """Structured outcome of a low-level browser operation."""

    ok: bool = True
    message: str
    page_state: PageState | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    artifacts: list[str] = Field(default_factory=list)


class BrowserEngine(Protocol):
    """Abstract browser engine contract used by runtime skills."""

    def start(self) -> None:
        """Prepare the browser runtime."""

    def stop(self) -> None:
        """Cleanly shut down the browser runtime."""

    def new_page(self) -> Any:
        """Create and activate a new browser page."""

    def get_page(self) -> Any:
        """Return the current active browser page."""

    def observe_page(self) -> PageState:
        """Capture a compact page snapshot."""

    def get_page_state(self) -> PageState:
        """Return the current page snapshot."""

    def get_page_text(self, max_chars: int = 4000) -> str:
        """Extract page text for reasoning or reporting."""

    def get_interactive_elements(
        self,
        max_elements: int = 25,
    ) -> list[InteractiveElementState]:
        """Return interactive elements from the current page."""

    def navigate(
        self,
        url: str,
        *,
        wait_for: str | None = None,
    ) -> BrowserOperationResult:
        """Navigate to a new URL."""

    def click(self, target: str) -> BrowserOperationResult:
        """Click an element identified by selector or element reference."""

    def type_text(
        self,
        target: str,
        text: str,
        *,
        clear_first: bool = True,
        submit: bool = False,
    ) -> BrowserOperationResult:
        """Type text into the given element."""

    def extract_page_text(self, max_chars: int = 4000) -> str:
        """Backward-compatible alias for page text extraction."""

    def select_option(
        self,
        target: str,
        value: str | None = None,
        label: str | None = None,
    ) -> BrowserOperationResult:
        """Select an option from a dropdown by value or label."""

    def scroll_viewport(
        self,
        direction: str,
        amount: int,
        target: str | None = None,
    ) -> BrowserOperationResult:
        """Scroll the page or an element."""

    def press_key(
        self,
        key: str,
        target: str | None = None,
    ) -> BrowserOperationResult:
        """Press a keyboard key, optionally targeting an element."""

    def wait_for_element(
        self,
        selector: str,
        timeout_ms: int,
        state: str,
    ) -> BrowserOperationResult:
        """Wait for an element to reach a specific state."""

    def upload_file(
        self,
        target: str,
        file_path: str,
    ) -> BrowserOperationResult:
        """Upload a file to a file input element."""

    def inspect_dialog(
        self,
        timeout_ms: int = 100,
    ) -> BrowserOperationResult:
        """Check for and read any active dialog."""


class StubBrowserEngine:
    """In-memory browser stub kept for smoke tests and isolated unit tests."""

    def __init__(self, initial_state: PageState | None = None) -> None:
        self._started = False
        self._state = initial_state or PageState()

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def new_page(self) -> None:
        self._state = PageState()
        return None

    def get_page(self) -> None:
        if not self._started:
            self.start()
        return None

    def observe_page(self) -> PageState:
        if not self._started:
            self.start()
        return self._state

    def get_page_state(self) -> PageState:
        return self.observe_page()

    def get_page_text(self, max_chars: int = 4000) -> str:
        return self.observe_page().text_excerpt[:max_chars]

    def get_interactive_elements(
        self,
        max_elements: int = 25,
    ) -> list[InteractiveElementState]:
        return self.observe_page().interactive_elements[:max_elements]

    def navigate(
        self,
        url: str,
        *,
        wait_for: str | None = None,
    ) -> BrowserOperationResult:
        self._state = PageState(
            url=url,
            title="Stub Browser Page",
            summary="Stub browser navigated to the requested URL.",
            text_excerpt=f"Stub page loaded at {url}.",
            metadata={"wait_for": wait_for or "load"},
        )
        return BrowserOperationResult(
            message=f"Navigated to {url}.",
            page_state=self._state,
            metadata={"wait_for": wait_for or "load"},
        )

    def click(self, target: str) -> BrowserOperationResult:
        page_state = self.observe_page().model_copy(
            update={
                "summary": f"Stub browser registered a click on {target}.",
                "metadata": {"last_clicked_target": target},
            },
        )
        self._state = page_state
        return BrowserOperationResult(
            message=f"Clicked {target}.",
            page_state=page_state,
            metadata={"resolved_target": target},
        )

    def type_text(
        self,
        target: str,
        text: str,
        *,
        clear_first: bool = True,
        submit: bool = False,
    ) -> BrowserOperationResult:
        page_state = self.observe_page().model_copy(
            update={
                "summary": f"Stub browser entered text into {target}.",
                "metadata": {
                    "last_typed_target": target,
                    "submitted": submit,
                    "characters_entered": len(text),
                    "clear_first": clear_first,
                },
            },
        )
        self._state = page_state
        return BrowserOperationResult(
            message=f"Typed into {target}.",
            page_state=page_state,
            metadata={
                "resolved_target": target,
                "submitted": submit,
                "characters_entered": len(text),
                "clear_first": clear_first,
            },
        )

    def extract_page_text(self, max_chars: int = 4000) -> str:
        return self.get_page_text(max_chars=max_chars)

    def select_option(
        self,
        target: str,
        value: str | None = None,
        label: str | None = None,
    ) -> BrowserOperationResult:
        self._state = self._state.model_copy(
            update={
                "summary": f"Stub browser selected option from {target}.",
                "metadata": {
                    "target": target,
                    "selected_value": value,
                    "selected_text": label,
                },
            },
        )
        return BrowserOperationResult(
            message=f"Selected option from {target}.",
            page_state=self._state,
            metadata={
                "target": target,
                "selected_value": value,
                "selected_text": label,
            },
        )

    def scroll_viewport(
        self,
        direction: str,
        amount: int,
        target: str | None = None,
    ) -> BrowserOperationResult:
        self._state = self._state.model_copy(
            update={
                "summary": f"Stub browser scrolled {direction} by {amount}px.",
                "metadata": {
                    "direction": direction,
                    "amount": amount,
                    "target": target,
                    "scroll_x": 0,
                    "scroll_y": amount if direction == "down" else -amount if direction == "up" else 0,
                },
            },
        )
        return BrowserOperationResult(
            message=f"Scrolled {direction} by {amount}px.",
            page_state=self._state,
            metadata={
                "direction": direction,
                "amount": amount,
                "target": target,
                "scroll_x": 0,
                "scroll_y": amount if direction == "down" else -amount if direction == "up" else 0,
            },
        )

    def press_key(
        self,
        key: str,
        target: str | None = None,
    ) -> BrowserOperationResult:
        self._state = self._state.model_copy(
            update={
                "summary": f"Stub browser pressed key '{key}' on {target or 'page'}.",
                "metadata": {
                    "key": key,
                    "target": target,
                },
            },
        )
        return BrowserOperationResult(
            message=f"Pressed key '{key}'.",
            page_state=self._state,
            metadata={
                "key": key,
                "target": target,
            },
        )

    def wait_for_element(
        self,
        selector: str,
        timeout_ms: int,
        state: str,
    ) -> BrowserOperationResult:
        return BrowserOperationResult(
            message=f"Stub browser waited for {selector} to be {state}.",
            page_state=self._state,
            metadata={
                "selector": selector,
                "waited_ms": 0,
                "found": True,
                "state": state,
            },
        )

    def upload_file(
        self,
        target: str,
        file_path: str,
    ) -> BrowserOperationResult:
        self._state = self._state.model_copy(
            update={
                "summary": f"Stub browser uploaded file to {target}.",
                "metadata": {
                    "target": target,
                    "file_path": file_path,
                },
            },
        )
        return BrowserOperationResult(
            message=f"Uploaded file to {target}.",
            page_state=self._state,
            metadata={
                "target": target,
                "file_path": file_path,
            },
        )

    def inspect_dialog(
        self,
        timeout_ms: int = 100,
    ) -> BrowserOperationResult:
        return BrowserOperationResult(
            message="No dialog visible on stub page.",
            page_state=self._state,
            metadata={
                "dialog_visible": False,
                "dialog_type": None,
                "dialog_message": None,
            },
        )


class PlaywrightBrowserEngine:
    """Real browser engine backed by Playwright."""

    def __init__(
        self,
        *,
        headless: bool = True,
        default_timeout_ms: int = 5_000,
        max_text_chars: int = 4_000,
        max_interactive_elements: int = 25,
        artifact_dir: Path | str | None = None,
        capture_screenshots: bool = False,
        action_delay_ms: int = 0,
        highlight_actions: bool = False,
    ) -> None:
        self.headless = headless
        self.default_timeout_ms = default_timeout_ms
        self.max_text_chars = max_text_chars
        self.max_interactive_elements = max_interactive_elements
        self.capture_screenshots = capture_screenshots
        self.action_delay_ms = max(0, action_delay_ms)
        self.highlight_actions = highlight_actions
        self.artifact_dir = Path(artifact_dir) if artifact_dir is not None else None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_page_state: PageState | None = None
        self._element_cache: dict[str, InteractiveElementState] = {}

    def start(self) -> None:
        """Prepare the Playwright runtime."""

        if self._playwright is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserRuntimeError(
                "playwright_missing",
                "Playwright is not installed in the current environment.",
                metadata={"details": str(exc)},
            ) from exc

        try:
            self._playwright = sync_playwright().start()
            launch_kwargs: dict[str, Any] = {"headless": self.headless}
            if self.action_delay_ms > 0:
                launch_kwargs["slow_mo"] = self.action_delay_ms
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            self._context = self._browser.new_context()
            self._context.set_default_timeout(self.default_timeout_ms)
            self._context.set_default_navigation_timeout(self.default_timeout_ms)
            self._page = self._context.new_page()
            self._page.set_default_timeout(self.default_timeout_ms)
        except Exception as exc:
            self.stop()
            message = "Failed to start the Playwright browser runtime."
            code = "browser_start_failed"
            details = str(exc)
            if "Executable doesn't exist" in details:
                code = "browser_executable_missing"
                message = (
                    "Failed to start the Playwright browser runtime because browser "
                    "binaries are missing. Run: python -m playwright install chromium "
                    "(or: browser-agent setup)."
                )
            raise BrowserRuntimeError(
                code,
                message,
                metadata={"details": details},
            ) from exc

    def stop(self) -> None:
        """Cleanly shut down the browser runtime."""

        for resource in (self._page, self._context, self._browser):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._last_page_state = None
        self._element_cache = {}

    def new_page(self) -> Page:
        """Create and activate a new browser page."""

        if self._playwright is None:
            self.start()
        if self._context is None:
            raise BrowserRuntimeError(
                "browser_context_unavailable",
                "Browser context is unavailable after startup.",
            )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.default_timeout_ms)
        return self._page

    def get_page(self) -> Page:
        """Return the current active browser page."""

        self.start()
        if self._page is None or self._page.is_closed():
            return self.new_page()
        return self._page

    def _click_locator_resilient(self, locator: Any) -> None:
        """Scroll the element into view, then click (reduces off-viewport / overlay flakes)."""

        locator.scroll_into_view_if_needed(timeout=self.default_timeout_ms)
        self._highlight_locator(locator)
        locator.click(timeout=self.default_timeout_ms)

    def _highlight_locator(self, locator: Any) -> None:
        """Flash a target element so headed runs are easier to follow."""

        if self.headless or not self.highlight_actions:
            return
        try:
            locator.evaluate(
                """el => {
                    const prevOutline = el.style.outline;
                    const prevOffset = el.style.outlineOffset;
                    const prevShadow = el.style.boxShadow;
                    const prevTransition = el.style.transition;
                    el.style.transition = "outline 120ms ease, box-shadow 120ms ease";
                    el.style.outline = "3px solid #ff7a18";
                    el.style.outlineOffset = "2px";
                    el.style.boxShadow = "0 0 0 6px rgba(255, 122, 24, 0.22)";
                    setTimeout(() => {
                        el.style.outline = prevOutline;
                        el.style.outlineOffset = prevOffset;
                        el.style.boxShadow = prevShadow;
                        el.style.transition = prevTransition;
                    }, 700);
                }"""
            )
            self.get_page().wait_for_timeout(180)
        except Exception:
            return

    def observe_page(self) -> PageState:
        """Capture a compact page snapshot."""

        return self._observe_page(reason="observe_page")

    def get_page_state(self) -> PageState:
        """Backward-compatible alias for observation calls."""

        if self._last_page_state is not None:
            return self._last_page_state
        return self.observe_page()

    def get_page_text(self, max_chars: int = 4000) -> str:
        """Extract visible page text using the live browser page."""

        page = self.get_page()
        try:
            text = page.evaluate(
                "() => document.body ? (document.body.innerText || '') : ''"
            )
        except Exception as exc:
            raise BrowserRuntimeError(
                "page_text_extraction_failed",
                "Failed to extract visible page text.",
                metadata={"details": str(exc)},
            ) from exc
        return self._truncate_text(text or "", max_chars=max_chars)

    def get_interactive_elements(
        self,
        max_elements: int = 25,
    ) -> list[InteractiveElementState]:
        """Return interactive elements from a fresh page snapshot."""

        return self._observe_page(
            reason="get_interactive_elements",
            max_elements=max_elements,
        ).interactive_elements[:max_elements]

    def navigate(
        self,
        url: str,
        *,
        wait_for: str | None = None,
    ) -> BrowserOperationResult:
        """Navigate to a new URL."""

        start = perf_counter()
        try:
            wait_until = self._normalize_wait_for(wait_for)
        except BrowserRuntimeError as exc:
            return self._result_from_exception(
                action="navigate",
                exc=exc,
                start=start,
                metadata={"url": url, "wait_for": wait_for},
            )
        if not self._is_supported_url(url):
            return self._result_error(
                action="navigate",
                message=f"Unsupported or invalid URL: {url}",
                error_code="invalid_url",
                duration_ms=self._elapsed_ms(start),
                metadata={"url": url},
            )

        page = self.get_page()
        try:
            response = page.goto(
                url,
                wait_until=wait_until,
                timeout=self.default_timeout_ms,
            )
            page_state = self._observe_page(reason="navigate")
            metadata = {
                "url": url,
                "wait_for": wait_until,
                "http_status": response.status if response is not None else None,
            }
            return BrowserOperationResult(
                message=f"Navigated to {page_state.url}.",
                page_state=page_state,
                metadata=metadata,
                duration_ms=self._elapsed_ms(start),
                artifacts=page_state.artifact_refs,
            )
        except Exception as exc:
            return self._result_from_exception(
                action="navigate",
                exc=exc,
                start=start,
                metadata={"url": url, "wait_for": wait_until},
            )

    def click(self, target: str) -> BrowserOperationResult:
        """Click an element identified by selector or element reference."""

        start = perf_counter()
        page = self.get_page()
        resolution = resolve_target_candidates(target, self._element_cache)
        if resolution.used_element_reference and not resolution.candidates:
            return self._result_error(
                action="click",
                message=f"Element reference `{target}` is no longer available.",
                error_code="element_reference_not_found",
                duration_ms=self._elapsed_ms(start),
                metadata={"target": target},
            )

        # If using raw selector (not element_id), check for ambiguity
        if not resolution.used_element_reference:
            is_ambiguous, match_count = self._detect_ambiguous_selector(page, target)
            if is_ambiguous:
                return self._result_error(
                    action="click",
                    message=f"Selector `{target}` is ambiguous and matches {match_count} elements.",
                    error_code="ambiguous_target",
                    error_message=f"The selector matches {match_count} elements. Use element_id for precise targeting.",
                    duration_ms=self._elapsed_ms(start),
                    metadata={
                        "target": target,
                        "matched_candidates_count": match_count,
                        "suggestion": "Use element_id from observation for precise targeting",
                    },
                )

        errors: list[str] = []
        for candidate in resolution.candidates:
            try:
                locator = page.locator(candidate.value).first
                self._click_locator_resilient(locator)
                page_state = self._observe_page(reason="click")
                return BrowserOperationResult(
                    message=f"Clicked target `{target}`.",
                    page_state=page_state,
                    metadata={
                        "target": target,
                        "resolved_selector": candidate.value,
                        "selector_strategy": candidate.strategy.value,
                        "used_element_reference": resolution.used_element_reference,
                    },
                    duration_ms=self._elapsed_ms(start),
                    artifacts=page_state.artifact_refs,
                )
            except Exception as exc:
                errors.append(f"{candidate.value}: {exc}")

        return self._result_error(
            action="click",
            message=f"Failed to click target `{target}`.",
            error_code="click_failed",
            error_message=" | ".join(errors),
            duration_ms=self._elapsed_ms(start),
            metadata={
                "target": target,
                "attempted_selectors": [candidate.value for candidate in resolution.candidates],
                "used_element_reference": resolution.used_element_reference,
            },
        )

    def type_text(
        self,
        target: str,
        text: str,
        *,
        clear_first: bool = True,
        submit: bool = False,
    ) -> BrowserOperationResult:
        """Type text into an editable control."""

        start = perf_counter()
        page = self.get_page()
        resolution = resolve_target_candidates(target, self._element_cache)
        if resolution.used_element_reference and not resolution.candidates:
            return self._result_error(
                action="type_text",
                message=f"Element reference `{target}` is no longer available.",
                error_code="element_reference_not_found",
                duration_ms=self._elapsed_ms(start),
                metadata={"target": target},
            )

        # If using raw selector (not element_id), check for ambiguity
        if not resolution.used_element_reference:
            is_ambiguous, match_count = self._detect_ambiguous_selector(page, target)
            if is_ambiguous:
                return self._result_error(
                    action="type_text",
                    message=f"Selector `{target}` is ambiguous and matches {match_count} elements.",
                    error_code="ambiguous_target",
                    error_message=f"The selector matches {match_count} elements. Use element_id for precise targeting.",
                    duration_ms=self._elapsed_ms(start),
                    metadata={
                        "target": target,
                        "matched_candidates_count": match_count,
                        "suggestion": "Use element_id from observation for precise targeting",
                    },
                )

        errors: list[str] = []
        for candidate in resolution.candidates:
            try:
                locator = page.locator(candidate.value).first
                self._click_locator_resilient(locator)
                if clear_first:
                    locator.fill(text, timeout=self.default_timeout_ms)
                else:
                    self._highlight_locator(locator)
                    locator.type(text, timeout=self.default_timeout_ms)
                if submit:
                    self._highlight_locator(locator)
                    locator.press("Enter", timeout=self.default_timeout_ms)
                page_state = self._observe_page(reason="type_text")
                return BrowserOperationResult(
                    message=f"Entered text into target `{target}`.",
                    page_state=page_state,
                    metadata={
                        "target": target,
                        "resolved_selector": candidate.value,
                        "selector_strategy": candidate.strategy.value,
                        "used_element_reference": resolution.used_element_reference,
                        "clear_first": clear_first,
                        "submitted": submit,
                        "characters_entered": len(text),
                    },
                    duration_ms=self._elapsed_ms(start),
                    artifacts=page_state.artifact_refs,
                )
            except Exception as exc:
                errors.append(f"{candidate.value}: {exc}")

        return self._result_error(
            action="type_text",
            message=f"Failed to enter text into target `{target}`.",
            error_code="type_text_failed",
            error_message=" | ".join(errors),
            duration_ms=self._elapsed_ms(start),
            metadata={
                "target": target,
                "attempted_selectors": [candidate.value for candidate in resolution.candidates],
                "used_element_reference": resolution.used_element_reference,
                "clear_first": clear_first,
                "submitted": submit,
                "characters_entered": len(text),
            },
        )

    def extract_page_text(self, max_chars: int = 4000) -> str:
        """Backward-compatible alias for page text extraction."""

        return self.get_page_text(max_chars=max_chars)

    def select_option(
        self,
        target: str,
        value: str | None = None,
        label: str | None = None,
    ) -> BrowserOperationResult:
        """Select an option from a dropdown by value or label."""

        start = perf_counter()
        page = self.get_page()
        resolution = resolve_target_candidates(target, self._element_cache)

        if resolution.used_element_reference and not resolution.candidates:
            return self._result_error(
                action="select_option",
                message=f"Element reference `{target}` is no longer available.",
                error_code="element_reference_not_found",
                duration_ms=self._elapsed_ms(start),
                metadata={"target": target},
            )

        # If using raw selector (not element_id), check for ambiguity
        if not resolution.used_element_reference:
            is_ambiguous, match_count = self._detect_ambiguous_selector(page, target)
            if is_ambiguous:
                return self._result_error(
                    action="select_option",
                    message=f"Selector `{target}` is ambiguous and matches {match_count} elements.",
                    error_code="ambiguous_target",
                    error_message=f"The selector matches {match_count} elements. Use element_id for precise targeting.",
                    duration_ms=self._elapsed_ms(start),
                    metadata={
                        "target": target,
                        "matched_candidates_count": match_count,
                        "suggestion": "Use element_id from observation for precise targeting",
                    },
                )

        errors: list[str] = []
        for candidate in resolution.candidates:
            try:
                locator = page.locator(candidate.value).first
                self._highlight_locator(locator)
                select_params: dict[str, str | None] = {}
                if value is not None:
                    select_params["value"] = value
                if label is not None:
                    select_params["label"] = label

                locator.select_option(**select_params, timeout=self.default_timeout_ms)
                page_state = self._observe_page(reason="select_option")

                metadata: dict[str, object] = {
                    "target": target,
                    "resolved_selector": candidate.value,
                    "selector_strategy": candidate.strategy.value,
                    "used_element_reference": resolution.used_element_reference,
                }
                if value:
                    metadata["selected_value"] = value
                if label:
                    metadata["selected_text"] = label

                return BrowserOperationResult(
                    message=f"Selected option from target `{target}`.",
                    page_state=page_state,
                    metadata=metadata,
                    duration_ms=self._elapsed_ms(start),
                    artifacts=page_state.artifact_refs,
                )
            except Exception as exc:
                errors.append(f"{candidate.value}: {exc}")

        return self._result_error(
            action="select_option",
            message=f"Failed to select option from target `{target}`.",
            error_code="select_option_failed",
            error_message=" | ".join(errors),
            duration_ms=self._elapsed_ms(start),
            metadata={
                "target": target,
                "attempted_selectors": [c.value for c in resolution.candidates],
                "used_element_reference": resolution.used_element_reference,
            },
        )

    def scroll_viewport(
        self,
        direction: str,
        amount: int,
        target: str | None = None,
    ) -> BrowserOperationResult:
        """Scroll the page or an element."""

        start = perf_counter()
        page = self.get_page()

        direction_map = {
            "up": (0, -amount),
            "down": (0, amount),
            "left": (-amount, 0),
            "right": (amount, 0),
        }

        if direction not in direction_map:
            return self._result_error(
                action="scroll_viewport",
                message=f"Invalid scroll direction: {direction}",
                error_code="invalid_scroll_direction",
                duration_ms=self._elapsed_ms(start),
                metadata={"direction": direction, "amount": amount},
            )

        dx, dy = direction_map[direction]

        try:
            if target:
                # Scroll a specific element
                resolution = resolve_target_candidates(target, self._element_cache)
                if resolution.used_element_reference and not resolution.candidates:
                    return self._result_error(
                        action="scroll_viewport",
                        message=f"Element reference `{target}` is no longer available.",
                        error_code="element_reference_not_found",
                        duration_ms=self._elapsed_ms(start),
                        metadata={"target": target},
                    )

                for candidate in resolution.candidates:
                    try:
                        locator = page.locator(candidate.value).first
                        locator.evaluate(f"el => el.scrollBy({dx}, {dy})")
                        break
                    except Exception as exc:
                        continue
            else:
                # Scroll the main viewport
                page.evaluate(f"() => window.scrollBy({dx}, {dy})")

            page_state = self._observe_page(reason="scroll_viewport")
            scroll_x = _scroll_coord_to_int(page.evaluate("() => window.scrollX"))
            scroll_y = _scroll_coord_to_int(page.evaluate("() => window.scrollY"))

            return BrowserOperationResult(
                message=f"Scrolled {direction} by {amount}px.",
                page_state=page_state,
                metadata={
                    "direction": direction,
                    "amount": amount,
                    "target": target,
                    "scroll_x": scroll_x,
                    "scroll_y": scroll_y,
                },
                duration_ms=self._elapsed_ms(start),
                artifacts=page_state.artifact_refs,
            )
        except Exception as exc:
            return self._result_from_exception(
                action="scroll_viewport",
                exc=exc,
                start=start,
                metadata={"direction": direction, "amount": amount, "target": target},
            )

    def press_key(
        self,
        key: str,
        target: str | None = None,
    ) -> BrowserOperationResult:
        """Press a keyboard key, optionally targeting an element."""

        start = perf_counter()
        page = self.get_page()

        try:
            if target:
                resolution = resolve_target_candidates(target, self._element_cache)
                if resolution.used_element_reference and not resolution.candidates:
                    return self._result_error(
                        action="press_key",
                        message=f"Element reference `{target}` is no longer available.",
                        error_code="element_reference_not_found",
                        duration_ms=self._elapsed_ms(start),
                        metadata={"key": key, "target": target},
                    )

                # If using raw selector (not element_id), check for ambiguity
                if not resolution.used_element_reference:
                    is_ambiguous, match_count = self._detect_ambiguous_selector(page, target)
                    if is_ambiguous:
                        return self._result_error(
                            action="press_key",
                            message=f"Selector `{target}` is ambiguous and matches {match_count} elements.",
                            error_code="ambiguous_target",
                            error_message=f"The selector matches {match_count} elements. Use element_id for precise targeting.",
                            duration_ms=self._elapsed_ms(start),
                            metadata={
                                "key": key,
                                "target": target,
                                "matched_candidates_count": match_count,
                                "suggestion": "Use element_id from observation for precise targeting",
                            },
                        )

                errors: list[str] = []
                for candidate in resolution.candidates:
                    try:
                        locator = page.locator(candidate.value).first
                        self._highlight_locator(locator)
                        locator.press(key, timeout=self.default_timeout_ms)
                        page_state = self._observe_page(reason="press_key")

                        return BrowserOperationResult(
                            message=f"Pressed key `{key}` on target `{target}`.",
                            page_state=page_state,
                            metadata={
                                "key": key,
                                "target": target,
                                "resolved_selector": candidate.value,
                                "selector_strategy": candidate.strategy.value,
                                "used_element_reference": resolution.used_element_reference,
                            },
                            duration_ms=self._elapsed_ms(start),
                            artifacts=page_state.artifact_refs,
                        )
                    except Exception as exc:
                        errors.append(f"{candidate.value}: {exc}")

                return self._result_error(
                    action="press_key",
                    message=f"Failed to press key `{key}` on target `{target}`.",
                    error_code="press_key_failed",
                    error_message=" | ".join(errors),
                    duration_ms=self._elapsed_ms(start),
                    metadata={
                        "key": key,
                        "target": target,
                        "attempted_selectors": [c.value for c in resolution.candidates],
                        "used_element_reference": resolution.used_element_reference,
                    },
                )
            else:
                # Global key press
                page.keyboard.press(key)
                page_state = self._observe_page(reason="press_key")

                return BrowserOperationResult(
                    message=f"Pressed key `{key}`.",
                    page_state=page_state,
                    metadata={"key": key},
                    duration_ms=self._elapsed_ms(start),
                    artifacts=page_state.artifact_refs,
                )
        except Exception as exc:
            return self._result_from_exception(
                action="press_key",
                exc=exc,
                start=start,
                metadata={"key": key, "target": target},
            )

    def wait_for_element(
        self,
        selector: str,
        timeout_ms: int,
        state: str,
    ) -> BrowserOperationResult:
        """Wait for an element to reach a specific state."""

        start = perf_counter()
        page = self.get_page()

        state_map = {
            "visible": "visible",
            "hidden": "hidden",
            "attached": "attached",
            "detached": "detached",
        }

        if state not in state_map:
            return self._result_error(
                action="wait_for_element",
                message=f"Invalid wait state: {state}",
                error_code="invalid_wait_state",
                duration_ms=self._elapsed_ms(start),
                metadata={"selector": selector, "state": state},
            )

        try:
            locator = page.locator(selector).first
            locator.wait_for(
                state=state_map[state],
                timeout=timeout_ms,
            )
            page_state = self._observe_page(reason="wait_for_element")

            return BrowserOperationResult(
                message=f"Element `{selector}` is now {state}.",
                page_state=page_state,
                metadata={
                    "selector": selector,
                    "state": state,
                    "found": True,
                    "waited_ms": self._elapsed_ms(start),
                },
                duration_ms=self._elapsed_ms(start),
                artifacts=page_state.artifact_refs,
            )
        except Exception as exc:
            # Element not found within timeout - this is expected behavior
            page_state = self._observe_page(reason="wait_for_element")

            return BrowserOperationResult(
                ok=False,
                message=f"Element `{selector}` did not become {state} within {timeout_ms}ms.",
                page_state=page_state,
                metadata={
                    "selector": selector,
                    "state": state,
                    "found": False,
                    "waited_ms": timeout_ms,
                },
                duration_ms=self._elapsed_ms(start),
                artifacts=page_state.artifact_refs,
            )

    def upload_file(
        self,
        target: str,
        file_path: str,
    ) -> BrowserOperationResult:
        """Upload a file to a file input element."""

        start = perf_counter()
        page = self.get_page()
        resolution = resolve_target_candidates(target, self._element_cache)

        if resolution.used_element_reference and not resolution.candidates:
            return self._result_error(
                action="upload_file",
                message=f"Element reference `{target}` is no longer available.",
                error_code="element_reference_not_found",
                duration_ms=self._elapsed_ms(start),
                metadata={"target": target, "file_path": file_path},
            )

        errors: list[str] = []
        for candidate in resolution.candidates:
            try:
                locator = page.locator(candidate.value).first
                locator.set_input_files(file_path, timeout=self.default_timeout_ms)
                page_state = self._observe_page(reason="upload_file")

                return BrowserOperationResult(
                    message=f"Uploaded file to target `{target}`.",
                    page_state=page_state,
                    metadata={
                        "target": target,
                        "file_path": file_path,
                        "resolved_selector": candidate.value,
                        "selector_strategy": candidate.strategy.value,
                        "used_element_reference": resolution.used_element_reference,
                    },
                    duration_ms=self._elapsed_ms(start),
                    artifacts=page_state.artifact_refs,
                )
            except Exception as exc:
                errors.append(f"{candidate.value}: {exc}")

        return self._result_error(
            action="upload_file",
            message=f"Failed to upload file to target `{target}`.",
            error_code="upload_file_failed",
            error_message=" | ".join(errors),
            duration_ms=self._elapsed_ms(start),
            metadata={
                "target": target,
                "file_path": file_path,
                "attempted_selectors": [c.value for c in resolution.candidates],
                "used_element_reference": resolution.used_element_reference,
            },
        )

    def inspect_dialog(
        self,
        timeout_ms: int = 100,
    ) -> BrowserOperationResult:
        """Check for and read any active dialog."""

        start = perf_counter()
        page = self.get_page()

        # Check if there's a visible dialog using JavaScript
        try:
            dialog_info = page.evaluate("""
                () => {
                    const dialog = document.querySelector('dialog[open], [role="dialog"], [role="alertdialog"]');
                    if (dialog) {
                        return {
                            visible: true,
                            type: dialog.tagName.toLowerCase() === 'dialog' ? 'dialog' : 'alert',
                            message: dialog.textContent?.slice(0, 200) || null,
                        };
                    }
                    // Check for native alert/confirm/prompt (they block, so we can't detect them directly)
                    // But we can check if there's a modal overlay
                    const modal = document.querySelector('.modal, .overlay, [class*="modal"], [class*="dialog"]');
                    if (modal) {
                        return {
                            visible: true,
                            type: 'modal',
                            message: modal.textContent?.slice(0, 200) || null,
                        };
                    }
                    return { visible: false };
                }
            """)

            page_state = self._observe_page(reason="inspect_dialog")

            if dialog_info and dialog_info.get("visible"):
                return BrowserOperationResult(
                    message=f"Found {dialog_info.get('type')} dialog.",
                    page_state=page_state,
                    metadata={
                        "dialog_visible": True,
                        "dialog_type": dialog_info.get("type"),
                        "dialog_message": dialog_info.get("message"),
                        "dialog_default_value": None,
                    },
                    duration_ms=self._elapsed_ms(start),
                    artifacts=page_state.artifact_refs,
                )
            else:
                return BrowserOperationResult(
                    message="No dialog visible on the page.",
                    page_state=page_state,
                    metadata={
                        "dialog_visible": False,
                        "dialog_type": None,
                        "dialog_message": None,
                        "dialog_default_value": None,
                    },
                    duration_ms=self._elapsed_ms(start),
                    artifacts=page_state.artifact_refs,
                )
        except Exception as exc:
            return self._result_from_exception(
                action="inspect_dialog",
                exc=exc,
                start=start,
                metadata={"timeout_ms": timeout_ms},
            )

    def _observe_page(
        self,
        *,
        reason: str,
        max_elements: int | None = None,
    ) -> PageState:
        page = self.get_page()

        try:
            raw_snapshot = page.evaluate(
                PAGE_SNAPSHOT_SCRIPT,
                [self.max_text_chars, max_elements or self.max_interactive_elements],
            )
        except Exception as exc:
            page_url = getattr(page, "url", "about:blank")
            try:
                page_title = page.title()
            except Exception:
                page_title = "Untitled Page"
            raise BrowserRuntimeError(
                "page_observation_failed",
                "Failed to observe the current page.",
                metadata={
                    "details": str(exc),
                    "captured_reason": reason,
                    "page_url": page_url,
                    "page_title": page_title,
                },
            ) from exc

        interactive_elements = [
            self._build_interactive_element(item)
            for item in raw_snapshot.get("interactive_elements", [])
        ]
        self._element_cache = {
            element.element_id: element for element in interactive_elements
        }

        form_fields = [
            self._build_form_field(item)
            for item in raw_snapshot.get("form_fields", [])
        ]
        artifacts = self._maybe_capture_screenshot(reason=reason)
        page_state = PageState(
            url=raw_snapshot.get("url") or page.url,
            title=raw_snapshot.get("title") or page.title() or "Untitled Page",
            summary=self._summarize_snapshot(
                raw_snapshot.get("title") or page.title() or "Untitled Page",
                raw_snapshot.get("url") or page.url,
                interactive_elements,
                form_fields,
            ),
            text_excerpt=self._truncate_text(
                raw_snapshot.get("text_excerpt") or "",
                max_chars=self.max_text_chars,
            ),
            interactive_elements=interactive_elements,
            form_fields=form_fields,
            observation_errors=[],
            artifact_refs=artifacts,
            metadata={
                **raw_snapshot.get("metadata", {}),
                "captured_reason": reason,
            },
            captured_at=utc_now(),
        )
        self._last_page_state = page_state
        return page_state

    def _build_interactive_element(self, raw: dict[str, Any]) -> InteractiveElementState:
        role = self._map_role(raw.get("role"))
        attributes = raw.get("attributes", {})
        stable_attributes = {
            key: attributes.get(key)
            for key in (
                "id",
                "name",
                "data-testid",
                "href",
                "type",
                "aria-label",
                "placeholder",
            )
            if attributes.get(key)
        }
        element = InteractiveElementState(
            element_id=raw.get("element_id")
            or stable_snapshot_id(
                "element",
                signature={
                    "selector": raw.get("selector") or "",
                    "tag": raw.get("tag") or "div",
                    "role": role.value,
                    "name": raw.get("name") or raw.get("text") or "",
                    "stable_attributes": stable_attributes,
                },
            ),
            name=raw.get("name") or raw.get("text") or raw.get("selector") or "element",
            tag=raw.get("tag") or "div",
            role=role,
            selector=raw.get("selector") or "",
            text=raw.get("text"),
            aria_label=raw.get("aria_label"),
            placeholder=raw.get("placeholder"),
            visible=bool(raw.get("visible", True)),
            enabled=bool(raw.get("enabled", True)),
            clickable=bool(raw.get("clickable", False)),
            input_like=bool(raw.get("input_like", False)),
            attributes=attributes,
        )
        candidates = [candidate.value for candidate in build_selector_candidates(element)]
        primary_selector = candidates[0] if candidates else element.selector
        return element.model_copy(
            update={
                "selector": primary_selector,
                "selector_candidates": candidates,
            }
        )

    def _build_form_field(self, raw: dict[str, Any]) -> FormFieldState:
        attributes = raw.get("attributes", {})
        stable_attributes = {
            key: attributes.get(key)
            for key in ("id", "name", "data-testid", "autocomplete", "type")
            if attributes.get(key)
        }
        return FormFieldState(
            field_id=raw.get("field_id")
            or stable_snapshot_id(
                "field",
                signature={
                    "selector": raw.get("selector") or "",
                    "label": raw.get("label") or "",
                    "name": raw.get("name") or "",
                    "field_type": raw.get("field_type") or "",
                    "stable_attributes": stable_attributes,
                },
            ),
            label=raw.get("label"),
            name=raw.get("name"),
            selector=raw.get("selector") or "",
            field_type=raw.get("field_type"),
            placeholder=raw.get("placeholder"),
            required=bool(raw.get("required", False)),
            filled=bool(raw.get("filled", False)),
            visible=bool(raw.get("visible", True)),
            enabled=bool(raw.get("enabled", True)),
            attributes=attributes,
        )

    def _map_role(self, raw_role: str | None) -> ElementRole:
        if raw_role is None:
            return ElementRole.OTHER
        normalized = raw_role.lower().strip()
        role_map = {
            "button": ElementRole.BUTTON,
            "link": ElementRole.LINK,
            "input": ElementRole.INPUT,
            "textbox": ElementRole.INPUT,
            "textarea": ElementRole.TEXTAREA,
            "checkbox": ElementRole.CHECKBOX,
            "radio": ElementRole.RADIO,
            "combobox": ElementRole.COMBOBOX,
            "menuitem": ElementRole.MENU_ITEM,
        }
        return role_map.get(normalized, ElementRole.OTHER)

    def _summarize_snapshot(
        self,
        title: str,
        url: str,
        interactive_elements: list[InteractiveElementState],
        form_fields: list[FormFieldState],
    ) -> str:
        parts = [f"Observed page `{title}` at {url}."]
        if interactive_elements:
            parts.append(
                f"Captured {len(interactive_elements)} interactive elements."
            )
        else:
            parts.append("No visible interactive elements were captured.")
        if form_fields:
            parts.append(f"Detected {len(form_fields)} form fields.")
        return " ".join(parts)

    def _normalize_wait_for(self, wait_for: str | None) -> str:
        if wait_for is None:
            return "load"
        if wait_for not in ALLOWED_WAIT_UNTIL:
            raise BrowserRuntimeError(
                "invalid_wait_for",
                (
                    "Unsupported wait condition. Expected one of "
                    f"{sorted(ALLOWED_WAIT_UNTIL)}."
                ),
                metadata={"wait_for": wait_for},
            )
        return wait_for

    def _is_supported_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ALLOWED_URL_SCHEMES

    def _truncate_text(self, text: str, *, max_chars: int) -> str:
        normalized = " ".join(text.split()).strip()
        return normalized[:max_chars]

    def _maybe_capture_screenshot(self, *, reason: str) -> list[str]:
        if not self.capture_screenshots or self.artifact_dir is None:
            return []
        page = self.get_page()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
        screenshot_path = self.artifact_dir / f"{reason}_{timestamp}.png"
        try:
            page.screenshot(path=str(screenshot_path))
        except Exception:
            return []
        return [str(screenshot_path)]

    def _result_from_exception(
        self,
        *,
        action: str,
        exc: Exception,
        start: float,
        metadata: dict[str, Any] | None = None,
    ) -> BrowserOperationResult:
        message = f"Browser action `{action}` failed."
        error_code = f"{action}_failed"
        details = str(exc)
        if "Timeout" in exc.__class__.__name__ or "Timeout" in details:
            error_code = f"{action}_timeout"
            message = f"Browser action `{action}` timed out."
        if isinstance(exc, BrowserRuntimeError):
            error_code = exc.code
            message = str(exc)
            metadata = {**(metadata or {}), **exc.metadata}
        return self._result_error(
            action=action,
            message=message,
            error_code=error_code,
            error_message=details,
            duration_ms=self._elapsed_ms(start),
            metadata=metadata,
        )

    def _result_error(
        self,
        *,
        action: str,
        message: str,
        error_code: str,
        duration_ms: int,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BrowserOperationResult:
        page_state = self._safe_last_page_state()
        artifacts = page_state.artifact_refs if page_state is not None else []
        return BrowserOperationResult(
            ok=False,
            message=message,
            page_state=page_state,
            metadata=metadata or {},
            error_code=error_code,
            error_message=error_message,
            duration_ms=duration_ms,
            artifacts=artifacts,
        )

    def _safe_last_page_state(self) -> PageState | None:
        if self._last_page_state is not None:
            return self._last_page_state
        try:
            return self._observe_page(reason="error_context")
        except Exception:
            return None

    def _elapsed_ms(self, start: float) -> int:
        return int((perf_counter() - start) * 1000)

    def _detect_ambiguous_selector(
        self,
        page,
        selector: str,
    ) -> tuple[bool, int]:
        """Check if a selector matches multiple elements on the page.

        Returns:
            Tuple of (is_ambiguous, match_count)
        """
        try:
            locator = page.locator(selector)
            count = locator.count()
            return count > 1, count
        except Exception:
            return False, 0
