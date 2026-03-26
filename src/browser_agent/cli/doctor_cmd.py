"""`browser-agent doctor` — non-fatal diagnostics."""

from __future__ import annotations

from browser_agent.cli.diagnostics import (
    Severity,
    check_api_key_present,
    check_chromium_launch,
    check_config_exists,
    check_llm_reachable,
    check_planner_settings,
    check_playwright_import,
    check_python_version,
    check_sys_executable,
)
from browser_agent.cli.ux import log_fail, log_ok, log_warn


def run_doctor() -> int:
    checks = [
        check_python_version,
        check_sys_executable,
        check_playwright_import,
        check_chromium_launch,
        check_config_exists,
        check_api_key_present,
        check_planner_settings,
        check_llm_reachable,
    ]

    exit_code = 0
    for fn in checks:
        r = fn()
        prefix = "[OK]" if r.severity == Severity.OK else (
            "[WARN]" if r.severity == Severity.WARN else "[FAIL]"
        )
        if r.severity == Severity.OK:
            log_ok(f"{r.name}: {r.message}")
        elif r.severity == Severity.WARN:
            log_warn(f"{r.name}: {r.message}")
            exit_code = max(exit_code, 0)
        else:
            log_fail(f"{r.name}: {r.message}")
            exit_code = 1
        for line in r.fix:
            print(f"  → {line}")

    if exit_code == 0:
        print()
        print("All critical checks passed.")
    else:
        print()
        print("Fix failures above, then run: browser-agent doctor")

    return exit_code
