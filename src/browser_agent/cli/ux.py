"""Consistent Rich-backed CLI status lines for product commands."""

from __future__ import annotations

import sys

from rich.console import Console

_console = Console(stderr=False)


def console_err() -> Console:
    return Console(stderr=True)


def log(tag: str, message: str, *, err: bool = False) -> None:
    c = console_err() if err else _console
    c.print(f"[bold]{tag}[/bold] {message}")


def log_ok(message: str) -> None:
    log("[OK]", message)


def log_warn(message: str) -> None:
    log("[WARN]", message, err=True)


def log_fail(message: str) -> None:
    log("[FAIL]", message, err=True)


def log_error(message: str) -> None:
    log("[ERROR]", message, err=True)


def log_setup(message: str) -> None:
    log("[SETUP]", message)


def log_install(message: str) -> None:
    log("[INSTALL]", message)


def log_doctor(message: str) -> None:
    log("[DOCTOR]", message)


def print_actionable(title: str, lines: list[str]) -> None:
    _console.print(f"[bold]{title}[/bold]")
    for line in lines:
        _console.print(f"  {line}")


def exit_with_hint(code: int, message: str, hint_lines: list[str]) -> None:
    log_error(message)
    for h in hint_lines:
        _console.print(f"  {h}")
    raise SystemExit(code)
