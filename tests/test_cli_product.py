"""Tests for product CLI entry (`browser-agent` commands)."""

from __future__ import annotations

import sys
from argparse import Namespace

from browser_agent.cli.bootstrap import BootstrapDecision, infer_explicit_start_url
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
        captured["ui"] = args.ui
        captured["headed"] = args.headed
        captured["start_url"] = args.start_url
        return object()

    monkeypatch.setattr(
        "browser_agent.cli.bootstrap.resolve_bootstrap_decision",
        lambda task_text, settings: BootstrapDecision(
            mode="direct_url",
            target_url="https://example.com/food",
            confidence=0.91,
            reason_summary=f"Bootstrap picked a site for: {task_text}",
        ),
    )
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
    assert captured["ui"] is True
    assert captured["headed"] is True
    assert captured["start_url"] == "https://example.com/food"


def test_bare_unquoted_task_words_are_joined_into_single_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_cli_from_args(args: Namespace, *, task_override: str | None = None) -> object:
        captured["task"] = args.task
        captured["task_override"] = task_override
        captured["ui"] = args.ui
        captured["headed"] = args.headed
        captured["start_url"] = args.start_url
        return object()

    monkeypatch.setattr(
        "browser_agent.cli.bootstrap.resolve_bootstrap_decision",
        lambda task_text, settings: BootstrapDecision(
            mode="search_url",
            target_url="https://search.example/?q=test",
            confidence=0.55,
            reason_summary=f"Bootstrap chose search for: {task_text}",
        ),
    )
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
    assert captured["ui"] is True
    assert captured["headed"] is True
    assert captured["start_url"] == "https://search.example/?q=test"


def test_run_subcommand_keeps_explicit_non_ui_defaults(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_cli_from_args(args: Namespace, *, task_override: str | None = None) -> object:
        captured["ui"] = args.ui
        captured["headed"] = args.headed
        captured["start_url"] = args.start_url
        return object()

    monkeypatch.setattr("browser_agent.cli.main.run_cli_from_args", fake_run_cli_from_args)

    old = sys.argv
    try:
        sys.argv = ["browser-agent", "run", "Inspect", "the", "page"]
        code = app()
        assert code == 0
    finally:
        sys.argv = old

    assert captured["ui"] is False
    assert captured["headed"] is False
    assert captured["start_url"] is None


def test_infer_explicit_start_url_only_for_url_or_domain() -> None:
    assert infer_explicit_start_url("Найди вакансии на hh.ru") == "https://hh.ru"
    assert infer_explicit_start_url("Open https://example.com/docs please") == "https://example.com/docs"
    assert infer_explicit_start_url("Глянь лучшие суши рядом") is None
