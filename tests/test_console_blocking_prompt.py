"""Tests for Rich Live stop/start around blocking stdin prompts."""

from __future__ import annotations

from rich.console import Console

from browser_agent.config import RuntimeSettings
from browser_agent.runtime.models import FinalReport, RuntimeStatus, UserTask
from browser_agent.runtime.session import RuntimeSession
from browser_agent.ui.events import AgentRunCompleted
from browser_agent.ui.console import AgentConsoleApp, blocking_prompt_with_live


class _FakeLive:
    """Minimal stand-in for rich.live.Live (stop/start/update only)."""

    def __init__(self) -> None:
        self.stop_calls = 0
        self.start_calls = 0
        self.start_refresh: list[bool] = []

    def stop(self) -> None:
        self.stop_calls += 1

    def start(self, refresh: bool = False) -> None:
        self.start_calls += 1
        self.start_refresh.append(refresh)

    def update(self, *_a, **_k) -> None:
        pass


def test_blocking_prompt_with_live_stops_before_fn_and_restarts_after() -> None:
    settings = RuntimeSettings()
    session = RuntimeSession(task=UserTask(request="t", start_url=None), settings=settings)
    app = AgentConsoleApp(session, settings)
    live = _FakeLive()
    app._live = live

    seen: dict[str, bool] = {}

    def fn() -> str:
        seen["during"] = app._live is None
        return "ok"

    out = blocking_prompt_with_live(live, app, fn)
    assert out == "ok"
    assert seen.get("during") is True
    assert live.stop_calls == 1
    assert live.start_calls == 1
    assert live.start_refresh == [True]
    assert app._live is live


def test_blocking_prompt_with_live_starts_live_even_if_fn_raises() -> None:
    settings = RuntimeSettings()
    session = RuntimeSession(task=UserTask(request="t", start_url=None), settings=settings)
    app = AgentConsoleApp(session, settings)
    live = _FakeLive()
    app._live = live

    def fn() -> None:
        raise ValueError("boom")

    try:
        blocking_prompt_with_live(live, app, fn)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")

    assert live.start_calls == 1
    assert app._live is live


def test_run_interactive_loop_prints_user_facing_final_answer() -> None:
    settings = RuntimeSettings()
    session = RuntimeSession(
        task=UserTask(request="Find sushi sets", start_url=None),
        settings=settings,
    )
    app = AgentConsoleApp(session, settings)
    app.console = Console(record=True, width=100, legacy_windows=False)

    report = FinalReport(
        session_id=session.session_id,
        status=RuntimeStatus.COMPLETED,
        summary="Collected the matching sushi sets.",
        completed=True,
        step_count=2,
        completion_reason="Found 3 sushi sets in Saint Petersburg under 1500 RUB.",
    )
    session.complete(report)

    class _Loop:
        def run(self, _session: RuntimeSession) -> FinalReport:
            app.emit(
                AgentRunCompleted(
                    timestamp=report.generated_at,
                    status=report.status.value,
                    summary=report.summary,
                    step_count=report.step_count,
                    trace_refs=(),
                    artifact_refs=(),
                    final_url=None,
                )
            )
            return report

    app.run_interactive_loop(_Loop())
    text = app.console.export_text()

    assert "Assistant" in text
    assert "Found 3 sushi sets in Saint Petersburg under 1500 RUB." in text
    assert "Run summary" in text
