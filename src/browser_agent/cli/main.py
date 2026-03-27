"""Console script entry: `browser-agent` → `app()`."""

from __future__ import annotations

import argparse
import sys

from browser_agent import __version__
from browser_agent.cli.bootstrap import apply_smart_bootstrap
from browser_agent.cli.runner import parse_run_args, run_cli_from_args
from browser_agent.cli.demo_cmd import run_demo
from browser_agent.cli.doctor_cmd import run_doctor
from browser_agent.cli.reset_cmd import run_reset
from browser_agent.cli.setup_cmd import run_setup
from browser_agent.cli.status_cmd import run_status
from browser_agent.cli.ux import log_error


def _print_root_help() -> None:
    print(
        """usage: browser-agent [--version] <command> ...

LLM-driven browser agent (Playwright).

Commands:
  setup       Install Chromium, configure API keys, smoke tests
  doctor      Check Python, Playwright, config, and LLM (best effort)
  demo        Run a bundled offline demo (food, jobs, spam)
  status      Show version and configuration summary
  reset       Remove ~/.browser-agent/config.yaml
  run         Run a task (optional; bare arguments imply 'run')

Examples:
  browser-agent setup
  browser-agent doctor
  browser-agent demo food --ui
  browser-agent run --ui --start-url http://localhost:8765/food_demo.html "Order a burger"
  browser-agent "Review this page" --start-url https://example.com

For help on a command:
  browser-agent demo -h
"""
    )


def app() -> int:
    argv = sys.argv[1:]

    if not argv:
        _print_root_help()
        return 0

    if argv[0] in ("--version", "-V"):
        print(__version__)
        return 0

    if argv[0] in ("--help", "-h") and len(argv) == 1:
        _print_root_help()
        return 0

    subcommands = {"setup", "doctor", "demo", "status", "reset", "run"}

    if argv[0] not in subcommands:
        return _dispatch_run(argv, bare_mode=True)

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "setup":
        return run_setup()

    if cmd == "doctor":
        if rest in (["-h"], ["--help"]):
            print("usage: browser-agent doctor")
            return 0
        return run_doctor()

    if cmd == "status":
        if rest in (["-h"], ["--help"]):
            print("usage: browser-agent status")
            return 0
        return run_status()

    if cmd == "reset":
        return run_reset(rest)

    if cmd == "demo":
        p = argparse.ArgumentParser(prog="browser-agent demo")
        p.add_argument("demo_name", choices=["food", "jobs", "spam"])
        p.add_argument("--ui", action="store_true")
        p.add_argument("--headed", action="store_true")
        p.add_argument("--max-steps", type=int, default=50)
        try:
            args = p.parse_args(rest)
        except SystemExit as e:
            return int(e.code) if isinstance(e.code, int) else 2
        return run_demo(
            args.demo_name,
            ui=args.ui,
            headed=args.headed,
            max_steps=args.max_steps,
        )

    if cmd == "run":
        return _dispatch_run(rest, bare_mode=False)

    log_error(f"Unknown command {cmd!r}")
    return 2


def _dispatch_run(rest: list[str], *, bare_mode: bool) -> int:
    try:
        args = parse_run_args(rest)
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 2
    args = apply_smart_bootstrap(args, bare_mode=bare_mode)
    run_cli_from_args(args)
    return 0
