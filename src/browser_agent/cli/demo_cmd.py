"""`browser-agent demo` — local pages + optional auto HTTP server."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from browser_agent.cli.runner import parse_run_args, run_cli_from_args
from browser_agent.cli.ux import log_error, log_ok, log_setup, log_warn
from browser_agent.runtime.models import RuntimeStatus

DEMO_SCENARIOS: dict[str, tuple[str, str]] = {
    "food": (
        "food_demo.html",
        "Order a Classic Burger and a Soft Drink",
    ),
    "jobs": (
        "jobs_demo.html",
        "Filter for remote full-time jobs and show me the Senior Frontend Developer listing",
    ),
    "spam": (
        "inbox_demo.html",
        "Mark the suspicious emails as spam. Look for obvious spam indicators "
        "like suspicious sender names or unrealistic offers.",
    ),
}


def _health_url(port: int, page: str) -> str:
    return f"http://127.0.0.1:{port}/{page}"


def _server_ready(port: int, page: str, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    url = _health_url(port, page)
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.2)
    return False


def _pick_port_and_server(page: str) -> tuple[subprocess.Popen | None, int]:
    """Return (server_process_or_none_if_reused, port)."""

    preferred = 8765
    if _server_ready(preferred, page, timeout=1.0):
        log_ok(f"Using existing demo server at http://127.0.0.1:{preferred}/")
        return None, preferred

    for port in range(preferred, preferred + 30):
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "browser_agent.demos.http_server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if _server_ready(port, page, timeout=20.0):
            log_ok(f"Demo server listening on http://127.0.0.1:{port}/")
            return proc, port
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    raise RuntimeError("Could not start a local demo server on a free port.")


def run_demo(
    name: str,
    *,
    ui: bool = False,
    headed: bool = False,
    max_steps: int = 25,
) -> int:
    if name not in DEMO_SCENARIOS:
        log_error(f"Unknown demo `{name}`. Choose: {', '.join(DEMO_SCENARIOS)}")
        return 2

    page, task = DEMO_SCENARIOS[name]
    proc: subprocess.Popen | None = None
    try:
        log_setup("Starting local demo server if needed…")
        proc, port = _pick_port_and_server(page)
        start_url = _health_url(port, page)

        argv: list[str] = [
            "--start-url",
            start_url,
            "--max-steps",
            str(max_steps),
        ]
        if ui:
            argv.append("--ui")
        if headed:
            argv.append("--headed")

        args = parse_run_args(argv)
        report = run_cli_from_args(args, task_override=task)
        if report.status == RuntimeStatus.FAILED:
            return 1
        return 0
    except Exception as exc:
        log_warn(f"Demo failed: {exc}")
        log_error("Could not run the packaged demo.")
        print("  Run: browser-agent doctor")
        print("  Run: browser-agent setup")
        return 1
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


