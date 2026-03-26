"""Consistent Rich-backed CLI status lines for product commands."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

_console = Console(stderr=False)


def console_err() -> Console:
    return Console(stderr=True)


def log(tag: str, message: str, *, err: bool = False) -> None:
    """Print a tagged line; message is literal text (no Rich markup parsing)."""
    c = console_err() if err else _console
    line = Text()
    line.append(tag, style="bold")
    line.append(" ")
    line.append(message)
    c.print(line)


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
    head = Text()
    head.append(title, style="bold")
    _console.print(head)
    for line in lines:
        _console.print(Text(f"  {line}"))


def exit_with_hint(code: int, message: str, hint_lines: list[str]) -> None:
    log_error(message)
    for h in hint_lines:
        _console.print(Text(f"  {h}"))
    raise SystemExit(code)
