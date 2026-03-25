"""Smoke tests for the CLI entrypoint."""

from __future__ import annotations

import json

from browser_agent.browser.engine import StubBrowserEngine
from browser_agent.browser.page_state import PageState
from browser_agent.cli.app import run_cli
from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.models import (
    PlannerDecisionType,
    PlannerProgressState,
    RuntimeStatus,
)


class QueuePlanner:
    """Return pre-seeded planner decisions in sequence."""

    def __init__(self, decisions: list[PlannerDecision]) -> None:
        self.decisions = list(decisions)

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        return self.decisions.pop(0)


def test_cli_reports_missing_planner_configuration_in_json_output(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("BROWSER_AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("BROWSER_AGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_ENABLED", "false")

    report = run_cli(["--json", "Review my inbox for spam"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert report.status == RuntimeStatus.STOPPED
    assert payload["status"] == RuntimeStatus.STOPPED.value
    assert payload["actions_taken"] == []
    assert "Planner is not configured" in payload["summary"]


def test_cli_runs_multistep_runtime_with_configured_planner(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("BROWSER_AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("BROWSER_AGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        "browser_agent.cli.app.build_planner",
        lambda settings, skill_registry: (
            QueuePlanner(
                [
                    PlannerDecision(
                        decision_type=PlannerDecisionType.ACT,
                        rationale="Read the current page text before finishing.",
                        chosen_skill="extract_page_text",
                        skill_input={"max_chars": 200},
                        expected_outcome="The runtime captures visible text.",
                        completion_confidence=0.6,
                        progress_assessment=PlannerProgressState.PARTIAL_PROGRESS,
                    ),
                    PlannerDecision(
                        decision_type=PlannerDecisionType.FINISH,
                        rationale="The observation and extracted text are enough.",
                        finish_reason="The CLI executed multiple planner-driven steps.",
                        completion_confidence=0.9,
                        progress_assessment=PlannerProgressState.SUBSTANTIAL_PROGRESS,
                    ),
                ]
            ),
            None,
        ),
    )
    monkeypatch.setattr(
        "browser_agent.cli.app.build_browser_engine",
        lambda settings: StubBrowserEngine(
            PageState(
                url="https://example.com/fixture",
                title="Smoke Fixture",
                summary="Smoke fixture page is ready for observation.",
                text_excerpt="Smoke fixture text excerpt.",
            )
        ),
    )

    report = run_cli(["--json", "Inspect the current page"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert report.status == RuntimeStatus.COMPLETED
    assert payload["status"] == RuntimeStatus.COMPLETED.value
    assert payload["actions_taken"] == ["extract_page_text", "finish_task"]
    assert payload["step_count"] == 2
