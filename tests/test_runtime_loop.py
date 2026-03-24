"""Tests for runtime loop mapping from browser results to tool results."""

from __future__ import annotations

from browser_agent.browser.engine import BrowserOperationResult, StubBrowserEngine
from browser_agent.browser.page_state import PageState
from browser_agent.config import RuntimeSettings
from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import AgentAction, AgentThought, RiskLevel, RuntimeStatus, ToolExecutionStatus, UserTask
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry


class SingleActionPlanner:
    """Planner that emits one failing click action."""

    def decide(self, session_summary: dict[str, object]) -> PlannerDecision:
        return PlannerDecision(
            thought=AgentThought(
                summary="Attempt a click.",
                rationale="Exercise browser-result to ToolResult error mapping.",
            ),
            action=AgentAction(
                tool_name="click_element",
                rationale="Trigger a failing click for the mapping test.",
                parameters={"selector": 'text="Missing"'},
                expected_outcome="The runtime should surface a structured failure.",
                risk_level=RiskLevel.LOW,
            ),
        )


class FailingClickBrowser(StubBrowserEngine):
    """Stub browser that returns a structured click failure."""

    def click(self, target: str) -> BrowserOperationResult:
        page_state = self.observe_page()
        return BrowserOperationResult(
            ok=False,
            message=f"Failed to click target `{target}`.",
            page_state=page_state,
            metadata={"attempted_selectors": [target]},
            error_code="selector_not_found",
            error_message="No matching element was visible on the page.",
        )


def test_runtime_loop_maps_browser_failure_into_structured_tool_result(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Click the missing button"),
        settings=settings,
    )
    browser = FailingClickBrowser(
        initial_state=PageState(
            url="https://example.com/dashboard",
            title="Dashboard",
            summary="Dashboard without the requested button.",
            text_excerpt="No matching button is visible.",
        )
    )
    loop = RuntimeLoop(
        planner=SingleActionPlanner(),
        skill_registry=build_default_registry(),
        browser=browser,
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(trace_dir=settings.trace_dir),
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.FAILED
    assert session.tool_results[0].status == ToolExecutionStatus.ERROR
    assert session.tool_results[0].error_code == "selector_not_found"
    assert session.tool_results[0].data["browser_metadata"]["attempted_selectors"] == [
        'text="Missing"'
    ]
    assert session.latest_observation is not None
    assert session.latest_observation.page_title == "Dashboard"
    assert any(path.suffix == ".jsonl" for path in settings.trace_dir.iterdir())
