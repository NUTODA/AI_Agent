"""Smoke tests for the CLI entrypoint."""

from __future__ import annotations

import json

from browser_agent.browser.engine import StubBrowserEngine
from browser_agent.browser.page_state import PageState
from browser_agent.cli.runner import parse_run_args, run_cli, run_cli_from_args
from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.models import (
    FinalReport,
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

    report = run_cli(["--json", "--skip-setup-check", "Review my inbox for spam"])
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
        "browser_agent.cli.runner.build_planner",
        lambda settings, skill_registry, session=None: (
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
        "browser_agent.cli.runner.build_browser_engine",
        lambda settings: StubBrowserEngine(
            PageState(
                url="https://example.com/fixture",
                title="Smoke Fixture",
                summary="Smoke fixture page is ready for observation.",
                text_excerpt="Smoke fixture text excerpt.",
            )
        ),
    )

    report = run_cli(["--json", "--skip-setup-check", "Inspect the current page"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert report.status == RuntimeStatus.COMPLETED
    assert payload["status"] == RuntimeStatus.COMPLETED.value
    assert payload["actions_taken"] == ["extract_page_text", "finish_task"]
    assert payload["step_count"] == 2


def test_cli_headed_mode_enables_visual_action_defaults(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("BROWSER_AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("BROWSER_AGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "browser_agent.cli.runner.build_planner",
        lambda settings, skill_registry, session=None: (
            QueuePlanner(
                [
                    PlannerDecision(
                        decision_type=PlannerDecisionType.FINISH,
                        rationale="Nothing else is needed.",
                        finish_reason="Headed run smoke test.",
                        completion_confidence=0.9,
                        progress_assessment=PlannerProgressState.SUBSTANTIAL_PROGRESS,
                    )
                ]
            ),
            None,
        ),
    )

    def fake_build_browser_engine(settings):
        captured["action_delay_ms"] = settings.action_delay_ms
        captured["highlight_actions"] = settings.highlight_actions
        return StubBrowserEngine(
            PageState(
                url="https://example.com/fixture",
                title="Smoke Fixture",
                summary="Smoke fixture page is ready for observation.",
                text_excerpt="Smoke fixture text excerpt.",
            )
        )

    monkeypatch.setattr("browser_agent.cli.runner.build_browser_engine", fake_build_browser_engine)

    report = run_cli(
        ["--json", "--headed", "--skip-setup-check", "Inspect the current page"]
    )
    captured_out = capsys.readouterr()
    payload = json.loads(captured_out.out)

    assert report.status == RuntimeStatus.COMPLETED
    assert payload["status"] == RuntimeStatus.COMPLETED.value
    assert captured["action_delay_ms"] == 350
    assert captured["highlight_actions"] is True


def test_cli_chat_mode_reuses_browser_for_follow_up_turns(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("BROWSER_AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("BROWSER_AGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_ENABLED", "true")
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_BASE_URL", "https://planner.example")
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_MODEL", "test-model")

    class CountingBrowser(StubBrowserEngine):
        def __init__(self, initial_state: PageState) -> None:
            super().__init__(initial_state=initial_state)
            self.stop_calls = 0

        def stop(self) -> None:
            self.stop_calls += 1
            super().stop()

    browser = CountingBrowser(
        PageState(
            url="https://example.com/start",
            title="Start",
            summary="Start page is open.",
            text_excerpt="Start page.",
        )
    )
    seen_turns: list[tuple[str, str | None, int, bool]] = []

    monkeypatch.setattr(
        "browser_agent.cli.runner.build_planner",
        lambda settings, skill_registry, session=None: (object(), None),
    )
    monkeypatch.setattr(
        "browser_agent.cli.runner.build_browser_engine",
        lambda settings: browser,
    )

    def fake_run_single_task(
        *,
        args,
        settings,
        skill_registry,
        browser,
        task_text,
        start_url,
        keep_browser_open,
        render_output,
    ) -> FinalReport:
        del args, settings, skill_registry, render_output
        seen_turns.append((task_text, start_url, id(browser), keep_browser_open))
        return FinalReport(
            session_id=f"session_{len(seen_turns)}",
            status=RuntimeStatus.COMPLETED,
            summary=f"Finished: {task_text}",
            completed=True,
            step_count=1,
        )

    monkeypatch.setattr("browser_agent.cli.runner.run_single_task", fake_run_single_task)

    answers = iter(["Открой hh.ru", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    args = parse_run_args(["--chat", "--skip-setup-check", "Проверь текущую страницу"])
    report = run_cli_from_args(args)

    assert report.status == RuntimeStatus.COMPLETED
    assert seen_turns == [
        ("Проверь текущую страницу", None, id(browser), True),
        ("Открой hh.ru", "https://hh.ru", id(browser), True),
    ]
    assert browser.stop_calls == 1


def test_cli_chat_mode_answers_meta_question_without_new_run(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setenv("BROWSER_AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("BROWSER_AGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_ENABLED", "true")
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_BASE_URL", "https://planner.example")
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_MODEL", "test-model")
    monkeypatch.setenv("BROWSER_AGENT_TIMEOUT_MS", "5000")

    browser = StubBrowserEngine(
        PageState(
            url="about:blank",
            title="Blank",
            summary="Blank page.",
            text_excerpt="",
        )
    )
    seen_turns: list[str] = []

    monkeypatch.setattr(
        "browser_agent.cli.runner.build_planner",
        lambda settings, skill_registry, session=None: (object(), None),
    )
    monkeypatch.setattr(
        "browser_agent.cli.runner.build_browser_engine",
        lambda settings: browser,
    )

    def fake_run_single_task(
        *,
        args,
        settings,
        skill_registry,
        browser,
        task_text,
        start_url,
        keep_browser_open,
        render_output,
    ) -> FinalReport:
        del args, settings, skill_registry, browser, start_url, keep_browser_open, render_output
        seen_turns.append(task_text)
        return FinalReport(
            session_id="session_failed",
            status=RuntimeStatus.FAILED,
            summary="Runtime failed while executing `navigate`.",
            completed=False,
            step_count=1,
            actions_taken=["navigate"],
            final_url="about:blank",
            failure_reason="Browser action `navigate` timed out.",
        )

    monkeypatch.setattr("browser_agent.cli.runner.run_single_task", fake_run_single_task)

    answers = iter(["Почему ты словил ошибку?", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    args = parse_run_args(["--chat", "--skip-setup-check", "Открой rp5.ru"])
    report = run_cli_from_args(args)
    captured = capsys.readouterr().out

    assert report.status == RuntimeStatus.FAILED
    assert seen_turns == ["Открой rp5.ru"]
    assert "Assistant: Я словил ошибку на шаге `navigate`" in captured
