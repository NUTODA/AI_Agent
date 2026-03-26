"""Shared environment checks for `doctor`, `setup`, and preflight."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from browser_agent.config import (
    MIN_PYTHON,
    RuntimeSettings,
    home_config_path,
    load_home_config_file,
    planner_env_configured,
)


class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    name: str
    severity: Severity
    message: str
    fix: list[str] = field(default_factory=list)


def check_python_version() -> CheckResult:
    if sys.version_info[:2] >= MIN_PYTHON:
        return CheckResult(
            "python",
            Severity.OK,
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    return CheckResult(
        "python",
        Severity.FAIL,
        f"Python {sys.version_info.major}.{sys.version_info.minor} is too old "
        f"(need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+).",
        fix=["Install Python 3.10+ from python.org or your OS package manager."],
    )


def check_sys_executable() -> CheckResult:
    path = sys.executable
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return CheckResult("executable", Severity.OK, f"Using `{path}`")
    return CheckResult(
        "executable",
        Severity.FAIL,
        "sys.executable is missing or not runnable.",
        fix=["Reinstall Python and ensure `python3` works."],
    )


def check_network_quick() -> CheckResult:
    try:
        req = urllib.request.Request(
            "https://example.com",
            headers={"User-Agent": "browser-agent-setup/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= getattr(resp, "status", 200) < 500:
                return CheckResult("network", Severity.OK, "Outbound HTTPS reachable")
    except Exception as exc:
        return CheckResult(
            "network",
            Severity.WARN,
            f"Could not verify network ({type(exc).__name__}).",
            fix=[
                "Check firewall/VPN if you need to download Chromium or call an API.",
            ],
        )
    return CheckResult("network", Severity.WARN, "Network check inconclusive.", [])


def check_playwright_import() -> CheckResult:
    try:
        import playwright  # noqa: F401

        return CheckResult("playwright_pkg", Severity.OK, "Playwright Python package importable")
    except ImportError as exc:
        return CheckResult(
            "playwright_pkg",
            Severity.FAIL,
            f"Playwright import failed: {exc}",
            fix=["Run: pip install playwright", "Or reinstall: pipx reinstall browser-agent-foundation"],
        )


def check_chromium_launch() -> CheckResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return CheckResult(
            "chromium",
            Severity.FAIL,
            f"Cannot import Playwright: {exc}",
            fix=["Run: browser-agent setup"],
        )

    try:
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto("about:blank", timeout=10_000)
                page.close()
            finally:
                browser.close()
        finally:
            pw.stop()
        return CheckResult("chromium", Severity.OK, "Chromium launches (smoke OK)")
    except Exception as exc:
        detail = str(exc)
        if "Executable doesn't exist" in detail or "browser_executable_missing" in detail:
            return CheckResult(
                "chromium",
                Severity.FAIL,
                "Chromium browser binary missing for Playwright.",
                fix=[
                    "Run: browser-agent setup",
                    f"Or: {sys.executable} -m playwright install chromium",
                ],
            )
        return CheckResult(
            "chromium",
            Severity.FAIL,
            f"Chromium check failed: {detail[:200]}",
            fix=["Run: browser-agent doctor", "Run: browser-agent setup"],
        )


def check_config_exists() -> CheckResult:
    path = home_config_path()
    if path.is_file():
        return CheckResult("config", Severity.OK, f"Found `{path}`")
    return CheckResult(
        "config",
        Severity.FAIL,
        "Global config not found.",
        fix=[
            "Run: browser-agent setup",
            "Or export BROWSER_AGENT_PLANNER_* variables (see .env.example).",
        ],
    )


def check_api_key_present() -> CheckResult:
    cfg = load_home_config_file()
    if cfg and cfg.api_key.strip():
        return CheckResult("api_key", Severity.OK, "API key present in config (value not shown)")
    if os.getenv("BROWSER_AGENT_PLANNER_API_KEY", "").strip():
        return CheckResult("api_key", Severity.OK, "API key set in environment (value not shown)")
    return CheckResult(
        "api_key",
        Severity.FAIL,
        "No API key in ~/.browser-agent/config.yaml or BROWSER_AGENT_PLANNER_API_KEY.",
        fix=["Run: browser-agent setup", "Or set BROWSER_AGENT_PLANNER_API_KEY in your environment."],
    )


def check_planner_settings() -> CheckResult:
    settings = RuntimeSettings.from_env()
    if planner_env_configured(settings):
        return CheckResult("planner_env", Severity.OK, "Planner environment variables are sufficient")
    return CheckResult(
        "planner_env",
        Severity.FAIL,
        "Planner not fully configured (enabled + provider + base URL + model).",
        fix=["Run: browser-agent setup", "Run: browser-agent doctor"],
    )


def check_llm_reachable() -> CheckResult:
    settings = RuntimeSettings.from_env()
    if not planner_env_configured(settings):
        return CheckResult(
            "llm",
            Severity.WARN,
            "Skipped LLM reachability (planner not configured).",
            fix=[],
        )

    from browser_agent.llm.provider import (
        GoogleGenerativeLanguageProvider,
        LLMMessage,
        LLMProviderError,
        LLMRequest,
        OpenAICompatibleProvider,
    )

    try:
        if settings.planner_provider == "openai_compatible":
            p = OpenAICompatibleProvider(
                base_url=settings.planner_base_url or "",
                model_name=settings.planner_model or "",
                api_key=settings.planner_api_key,
                timeout_seconds=min(settings.planner_timeout_seconds, 15.0),
                temperature=0.0,
            )
        else:
            p = GoogleGenerativeLanguageProvider(
                base_url=settings.planner_base_url or "",
                model_name=settings.planner_model or "",
                api_key=settings.planner_api_key,
                timeout_seconds=min(settings.planner_timeout_seconds, 15.0),
                temperature=0.0,
            )
        req = LLMRequest(
            messages=[
                LLMMessage(role="user", content="Reply with only the word OK."),
            ],
        )
        p.complete(req)
        return CheckResult("llm", Severity.OK, "LLM endpoint responded to a minimal request")
    except LLMProviderError as exc:
        return CheckResult(
            "llm",
            Severity.WARN,
            f"LLM not reachable or rejected the request ({str(exc)[:160]}).",
            fix=[
                "Check API key, base URL, and model id.",
                "Run: browser-agent doctor",
            ],
        )
    except Exception as exc:
        return CheckResult(
            "llm",
            Severity.WARN,
            f"LLM check failed ({type(exc).__name__}).",
            fix=["Check network and credentials."],
        )


def run_checks(checks: list[Callable[[], CheckResult]]) -> list[CheckResult]:
    return [c() for c in checks]
