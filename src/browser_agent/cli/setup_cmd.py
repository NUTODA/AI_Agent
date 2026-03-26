"""`browser-agent setup` — bootstrap Chromium, config, and smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum

from rich.console import Console
from rich.prompt import Prompt

from browser_agent.cli.diagnostics import (
    Severity,
    check_network_quick,
    check_python_version,
    check_sys_executable,
)
from browser_agent.cli.ux import log_fail, log_install, log_ok, log_setup, log_warn
from browser_agent.config import (
    UserHomeConfig,
    default_base_url_for_provider,
    provider_presets,
    save_home_config,
)
from browser_agent.llm.provider import (
    GoogleGenerativeLanguageProvider,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    OpenAICompatibleProvider,
)


class StepStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class StepOutcome:
    label: str
    status: StepStatus
    detail: str = ""
    notes: list[str] = field(default_factory=list)


def _run_playwright_install_chromium() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out[-4000:]


def _playwright_page_smoke() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto("about:blank")
                page.close()
            finally:
                browser.close()
        finally:
            pw.stop()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _llm_smoke(cfg: UserHomeConfig) -> tuple[bool, str]:
    settings_provider = cfg.planner_backend()
    try:
        if settings_provider == "openai_compatible":
            p = OpenAICompatibleProvider(
                base_url=cfg.base_url,
                model_name=cfg.model,
                api_key=cfg.api_key or None,
                timeout_seconds=20.0,
                temperature=0.0,
            )
        else:
            p = GoogleGenerativeLanguageProvider(
                base_url=cfg.base_url,
                model_name=cfg.model,
                api_key=cfg.api_key or None,
                timeout_seconds=20.0,
                temperature=0.0,
            )
        p.complete(
            LLMRequest(messages=[LLMMessage(role="user", content="Say OK.")]),
        )
        return True, ""
    except LLMProviderError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def run_setup() -> int:
    console = Console()
    outcomes: list[StepOutcome] = []

    log_setup("Checking environment…")
    for chk in (check_python_version, check_sys_executable, check_network_quick):
        r = chk()
        tag = StepStatus.OK if r.severity == Severity.OK else (
            StepStatus.WARN if r.severity == Severity.WARN else StepStatus.FAIL
        )
        outcomes.append(StepOutcome(r.name, tag, r.message, r.fix))
        if r.severity == Severity.OK:
            log_ok(r.message)
        elif r.severity == Severity.WARN:
            log_warn(r.message)
        else:
            log_fail(r.message)
            for f in r.fix:
                console.print(f"  → {f}")
            _print_summary(outcomes)
            return 1

    log_install("Installing Chromium (this may take a minute)…")
    code, tail = _run_playwright_install_chromium()
    if code != 0:
        outcomes.append(
            StepOutcome(
                "chromium_install",
                StepStatus.FAIL,
                f"playwright install exited {code}",
                [f"{sys.executable} -m playwright install chromium"],
            ),
        )
        log_fail("Chromium install failed.")
        if tail.strip():
            console.print(f"[dim]{tail}[/dim]")
        _print_summary(outcomes)
        return 1
    outcomes.append(StepOutcome("chromium_install", StepStatus.OK, "Chromium installed"))
    log_ok("Chromium install completed")

    log_setup("Testing Playwright (open blank page)…")
    ok, err = _playwright_page_smoke()
    if not ok:
        outcomes.append(StepOutcome("test_playwright", StepStatus.FAIL, err))
        log_fail("Playwright smoke test failed.")
        console.print("  → Run: browser-agent doctor")
        _print_summary(outcomes)
        return 1
    outcomes.append(StepOutcome("test_playwright", StepStatus.OK, "Blank page OK"))
    log_ok("Playwright OK")

    console.print()
    console.print("[bold]Planner API configuration[/bold] (stored in ~/.browser-agent/config.yaml)")
    presets = {p[0]: p for p in provider_presets()}
    provider = Prompt.ask(
        "Provider",
        choices=list(presets.keys()),
        default="openrouter",
    )
    default_url = presets[provider][1] if provider != "custom" else ""
    default_model = presets[provider][2] if provider != "custom" else ""
    if provider == "custom":
        base_url = Prompt.ask("Base URL (OpenAI-compatible or Gemini v1beta root)")
    else:
        base_url = Prompt.ask(
            "Base URL",
            default=default_url or default_base_url_for_provider(provider),
        )
    api_key = Prompt.ask("API key", password=True)
    model = Prompt.ask(
        "Model id",
        default=default_model or "gpt-4o-mini",
    )

    cfg = UserHomeConfig(provider=provider, base_url=base_url.strip(), api_key=api_key.strip(), model=model.strip())
    try:
        save_home_config(cfg)
    except OSError as exc:
        outcomes.append(StepOutcome("save_config", StepStatus.FAIL, str(exc)))
        log_fail(f"Could not save config: {exc}")
        _print_summary(outcomes)
        return 1

    outcomes.append(StepOutcome("save_config", StepStatus.OK, "Saved ~/.browser-agent/config.yaml"))
    log_ok("Config saved (API key not printed)")

    # Apply for this process so LLM test sees it
    os.environ.setdefault("BROWSER_AGENT_PLANNER_ENABLED", "true")
    os.environ.setdefault("BROWSER_AGENT_PLANNER_PROVIDER", cfg.planner_backend())
    os.environ.setdefault("BROWSER_AGENT_PLANNER_BASE_URL", cfg.base_url)
    os.environ.setdefault("BROWSER_AGENT_PLANNER_MODEL", cfg.model)
    os.environ.setdefault("BROWSER_AGENT_PLANNER_API_KEY", cfg.api_key)

    log_setup("Testing LLM (best effort)…")
    llm_ok, llm_err = _llm_smoke(cfg)
    if llm_ok:
        outcomes.append(StepOutcome("test_llm", StepStatus.OK, "LLM responded"))
        log_ok("LLM OK")
    else:
        outcomes.append(
            StepOutcome(
                "test_llm",
                StepStatus.WARN,
                llm_err,
                ["You can still run local demos if the planner works later."],
            ),
        )
        log_warn("LLM test failed (network/API issue).")
        console.print("  You can still run demos after fixing API settings.")
        console.print(f"  [dim]{llm_err[:200]}[/dim]")

    _print_summary(outcomes)
    return 0


def _print_summary(outcomes: list[StepOutcome]) -> None:
    console = Console()
    console.print()
    console.print("[bold]Summary[/bold]")
    for o in outcomes:
        color = {"OK": "green", "WARN": "yellow", "FAIL": "red"}[o.status.value]
        console.print(f"  [{color}][{o.status.value}][/{color}] {o.label}: {o.detail}")
