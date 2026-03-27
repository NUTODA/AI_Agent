"""Tests for product CLI entry (`browser-agent` commands)."""

from __future__ import annotations

import sys
from argparse import Namespace

from browser_agent.cli.main import app


def test_version_flag(capsys) -> None:
    old = sys.argv
    try:
        sys.argv = ["browser-agent", "--version"]
        code = app()
        assert code == 0
        out = capsys.readouterr().out.strip()
        assert out and out[0].isdigit()
    finally:
        sys.argv = old


def test_demo_help_exits_zero() -> None:
    old = sys.argv
    try:
        sys.argv = ["browser-agent", "demo", "-h"]
        code = app()
        assert code == 0
    finally:
        sys.argv = old


def test_demo_invalid_scenario_returns_nonzero() -> None:
    old = sys.argv
    try:
        sys.argv = ["browser-agent", "demo", "pizza"]
        code = app()
        assert code == 2
    finally:
        sys.argv = old


def test_bare_quoted_task_dispatches_to_run(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_cli_from_args(args: Namespace, *, task_override: str | None = None) -> object:
        captured["task"] = args.task
        captured["task_override"] = task_override
        return object()

    monkeypatch.setattr("browser_agent.cli.main.run_cli_from_args", fake_run_cli_from_args)

    old = sys.argv
    try:
        sys.argv = ["browser-agent", "закажи роллов на 1500р в Ёбидоёби"]
        code = app()
        assert code == 0
    finally:
        sys.argv = old

    assert captured["task"] == ["закажи роллов на 1500р в Ёбидоёби"]
    assert captured["task_override"] is None


def test_bare_unquoted_task_words_are_joined_into_single_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_cli_from_args(args: Namespace, *, task_override: str | None = None) -> object:
        captured["task"] = args.task
        captured["task_override"] = task_override
        return object()

    monkeypatch.setattr("browser_agent.cli.main.run_cli_from_args", fake_run_cli_from_args)

    old = sys.argv
    try:
        sys.argv = [
            "browser-agent",
            "закажи",
            "роллов",
            "на",
            "1500р",
            "в",
            "Ёбидоёби",
        ]
        code = app()
        assert code == 0
    finally:
        sys.argv = old

    assert captured["task"] == ["закажи", "роллов", "на", "1500р", "в", "Ёбидоёби"]
    assert captured["task_override"] is None
