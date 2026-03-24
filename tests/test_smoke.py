"""Smoke tests for the foundation CLI and runtime bootstrap."""

from __future__ import annotations

import json

from browser_agent.cli.app import run_cli
from browser_agent.runtime.models import RuntimeStatus


def test_cli_bootstrap_json_output(capsys) -> None:
    report = run_cli(["--json", "Review my inbox for spam"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert report.status == RuntimeStatus.STOPPED
    assert payload["status"] == RuntimeStatus.STOPPED.value
    assert payload["actions_taken"] == ["observe_page", "finish_task"]
    assert "Foundation bootstrap completed" in payload["summary"]
