"""Smoke tests for runtime → UI event emission."""

from __future__ import annotations

from browser_agent.browser.engine import StubBrowserEngine
from browser_agent.browser.page_state import PageState
from browser_agent.config import RuntimeSettings
from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import (
    PlannerDecisionType,
    PlannerProgressState,
    RiskLevel,
    RuntimeStatus,
    UserTask,
)
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry
from browser_agent.ui.events import (
    AgentRunCompleted,
    AgentRunStarted,
    CallbackEventEmitter,
    ObservationReady,
    PlannerDecisionReady,
    StepStarted,
)


class QueuePlanner:
    def __init__(self, decisions: list[PlannerDecision]) -> None:
        self.decisions = list(decisions)

    def decide(self, planner_context):
        del planner_context
        return self.decisions.pop(0)


def test_runtime_loop_emits_core_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BROWSER_AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("BROWSER_AGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    settings = RuntimeSettings.from_env()
    session = RuntimeSession(
        task=UserTask(request="Observe once", start_url="https://example.com"),
        settings=settings,
    )
    planner = QueuePlanner(
        [
            PlannerDecision(
                decision_type=PlannerDecisionType.FINISH,
                rationale="Done.",
                finish_reason="Smoke finish.",
                completion_confidence=0.9,
                progress_assessment=PlannerProgressState.SUBSTANTIAL_PROGRESS,
            ),
        ]
    )
    events: list = []
    emitter = CallbackEventEmitter(events.append)
    loop = RuntimeLoop(
        planner=planner,
        skill_registry=build_default_registry(),
        browser=StubBrowserEngine(
            PageState(
                url="https://example.com",
                title="T",
                summary="S",
                text_excerpt="x",
            )
        ),
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(trace_dir=settings.trace_dir),
        event_emitter=emitter,
        planner_display_name="test-model",
        planner_provider_kind="openai_compatible",
    )
    report = loop.run(session)
    assert report.status == RuntimeStatus.COMPLETED
    types = {type(e).__name__ for e in events}
    assert "AgentRunStarted" in types
    assert "StepStarted" in types
    assert "ObservationReady" in types
    assert "PlannerDecisionReady" in types
    assert "AgentRunCompleted" in types
    assert any(isinstance(e, AgentRunStarted) for e in events)
    assert any(isinstance(e, AgentRunCompleted) for e in events)
