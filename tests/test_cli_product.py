"""Tests for product CLI entry (`browser-agent` commands)."""

from __future__ import annotations

import sys

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
