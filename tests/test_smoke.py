"""Smoke tests for the foundation CLI and runtime bootstrap."""

from __future__ import annotations

import json

from browser_agent.browser.engine import StubBrowserEngine
from browser_agent.browser.page_state import PageState
from browser_agent.cli.app import run_cli
from browser_agent.runtime.models import RuntimeStatus


def test_cli_bootstrap_json_output(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BROWSER_AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("BROWSER_AGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        "browser_agent.cli.app.build_browser_engine",
        lambda settings: StubBrowserEngine(
            PageState(
                title="Smoke Fixture",
                summary="Smoke fixture page is ready for observation.",
                text_excerpt="Smoke fixture text excerpt.",
            )
        ),
    )

    report = run_cli(["--json", "Review my inbox for spam"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert report.status == RuntimeStatus.STOPPED
    assert payload["status"] == RuntimeStatus.STOPPED.value
    assert payload["actions_taken"] == ["observe_page", "finish_task"]
    assert "Foundation bootstrap completed" in payload["summary"]
