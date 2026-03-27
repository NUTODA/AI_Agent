"""Runtime-loop tests for the structured multi-step agent."""

from __future__ import annotations

from browser_agent.browser.engine import BrowserOperationResult, StubBrowserEngine
from browser_agent.browser.page_state import PageState
from browser_agent.config import RuntimeSettings
from browser_agent.llm.prompts import build_planner_context
from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import (
    AgentObservation,
    InteractiveElement,
    HumanInterventionKind,
    PlannerDecisionType,
    PlannerProgressState,
    RiskLevel,
    RuntimeStatus,
    ToolExecutionStatus,
    UserTask,
)
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationDecision, ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry


def act_decision(
    *,
    skill: str,
    skill_input: dict[str, object],
    rationale: str,
    expected_outcome: str,
    risk_level: RiskLevel = RiskLevel.LOW,
    destructive: bool = False,
    requires_confirmation: bool = False,
    progress_assessment: PlannerProgressState = PlannerProgressState.PARTIAL_PROGRESS,
) -> PlannerDecision:
    return PlannerDecision(
        decision_type=PlannerDecisionType.ACT,
        rationale=rationale,
        chosen_skill=skill,
        skill_input=skill_input,
        expected_outcome=expected_outcome,
        risk_level=risk_level,
        destructive=destructive,
        requires_confirmation=requires_confirmation,
        completion_confidence=0.6,
        progress_assessment=progress_assessment,
    )


def finish_decision(reason: str) -> PlannerDecision:
    return PlannerDecision(
        decision_type=PlannerDecisionType.FINISH,
        rationale="The task now has enough evidence to stop.",
        finish_reason=reason,
        completion_confidence=0.9,
        progress_assessment=PlannerProgressState.SUBSTANTIAL_PROGRESS,
    )


class QueuePlanner:
    """Return pre-seeded planner decisions in sequence."""

    def __init__(self, decisions: list[PlannerDecision]) -> None:
        self.decisions = list(decisions)

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        if not self.decisions:
            return PlannerDecision.safe_fail("Planner queue is empty.")
        return self.decisions.pop(0)


class AskThenFinishPlanner:
    """Ask for a user answer once, then finish."""

    def decide(self, planner_context) -> PlannerDecision:
        if not planner_context.session_state.user_responses:
            return PlannerDecision(
                decision_type=PlannerDecisionType.ASK_USER,
                rationale="The target account is ambiguous.",
                user_question="Which account should the agent use?",
                completion_confidence=0.2,
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        return finish_decision("The agent received the blocking user clarification.")


class SingleActionPlanner:
    """Planner that emits one failing click action."""

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        return act_decision(
            skill="click_element",
            skill_input={"selector": 'text="Missing"'},
            rationale="Trigger a failing click for the mapping test.",
            expected_outcome="The runtime should surface a structured failure.",
            progress_assessment=PlannerProgressState.NO_PROGRESS,
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


class NoProgressBrowser(StubBrowserEngine):
    """Stub browser that returns success without changing the page state."""

    def click(self, target: str) -> BrowserOperationResult:
        page_state = self.observe_page()
        return BrowserOperationResult(
            message=f"Clicked {target}.",
            page_state=page_state,
            metadata={"resolved_target": target},
        )


class ScrollingTextBrowser(StubBrowserEngine):
    """Stub browser that keeps one URL while scroll changes the observed text."""

    def __init__(self) -> None:
        super().__init__(
            initial_state=PageState(
                url="https://example.com/weather",
                title="Weather",
                summary="Weather page with a long report.",
                text_excerpt="Top of weather page.",
            )
        )
        self._scroll_index = 0

    def scroll_viewport(self, direction: str, amount: int, target: str | None = None):
        del target
        self._scroll_index += 1
        self._state = self._state.model_copy(
            update={
                "text_excerpt": f"Weather block chunk {self._scroll_index}",
                "summary": f"Weather page chunk {self._scroll_index}.",
            }
        )
        return BrowserOperationResult(
            message=f"Scrolled {direction} by {amount}px.",
            page_state=self._state,
            metadata={"scroll_y": self._scroll_index * amount},
        )


def build_loop(*, planner, browser, trace_dir) -> RuntimeLoop:
    return RuntimeLoop(
        planner=planner,
        skill_registry=build_default_registry(),
        browser=browser,
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(trace_dir=trace_dir),
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
    loop = build_loop(
        planner=SingleActionPlanner(),
        browser=browser,
        trace_dir=settings.trace_dir,
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
    assert session.trace_items[0].planner_decision_type == PlannerDecisionType.ACT
    assert any(path.suffix == ".jsonl" for path in settings.trace_dir.iterdir())


def test_runtime_loop_executes_multiple_steps_and_finishes(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=6,
    )
    session = RuntimeSession(
        task=UserTask(
            request="Navigate and inspect the dashboard",
            start_url="https://example.com/dashboard",
        ),
        settings=settings,
    )
    planner = QueuePlanner(
        [
            act_decision(
                skill="navigate",
                skill_input={"url": "https://example.com/dashboard", "wait_for": "load"},
                rationale="The requested start URL is the next safe atomic step.",
                expected_outcome="The dashboard page loads in the browser.",
            ),
            act_decision(
                skill="extract_page_text",
                skill_input={"max_chars": 250},
                rationale="Read the current page text before finishing.",
                expected_outcome="The runtime captures bounded visible text from the page.",
            ),
            finish_decision("The dashboard page was loaded and its visible text was read."),
        ]
    )
    loop = build_loop(
        planner=planner,
        browser=StubBrowserEngine(),
        trace_dir=settings.trace_dir,
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    assert report.completed is True
    assert report.step_count == 3
    assert [action.tool_name for action in session.actions] == [
        "navigate",
        "extract_page_text",
        "finish_task",
    ]
    assert session.latest_observation is not None
    assert session.latest_observation.page_url == "https://example.com/dashboard"
    assert len(session.trace_items) == 3
    assert session.trace_items[-1].report_summary == report.summary
    assert all(item.planner_decision_type is not None for item in session.trace_items)


def test_runtime_loop_maps_captcha_question_to_human_checkpoint(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Open the site and continue after captcha"),
        settings=settings,
    )
    planner = QueuePlanner(
        [
            PlannerDecision(
                decision_type=PlannerDecisionType.ASK_USER,
                rationale="The site is blocked by a captcha.",
                user_question="Пожалуйста, пройдите капчу на странице и продолжите.",
                completion_confidence=0.1,
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        ]
    )
    browser = StubBrowserEngine(
        PageState(
            url="https://example.com/challenge",
            title="Вы не робот?",
            summary="Captcha page is visible.",
            text_excerpt="Подтвердите, что вы не робот.",
        )
    )
    loop = build_loop(planner=planner, browser=browser, trace_dir=settings.trace_dir)

    report = loop.run(session)

    assert report.status == RuntimeStatus.WAITING_FOR_INTERVENTION
    assert report.pending_human_intervention is not None
    assert report.pending_human_intervention.kind == HumanInterventionKind.CAPTCHA
    assert session.pending_human_intervention is not None


def test_get_interactive_elements_respects_requested_max_elements(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Collect more interactive elements"),
        settings=settings,
    )

    class MaxElementsBrowser(StubBrowserEngine):
        def get_interactive_elements(self, max_elements: int = 25):
            return [
                InteractiveElement(
                    element_id=f"element_{idx}",
                    label=f"Link {idx}",
                    tag="a",
                    role="link",
                    selector=f'text="Link {idx}"',
                    is_clickable=True,
                )
                for idx in range(max_elements)
            ]

        def observe_page(self):
            return PageState(
                url="https://example.com/search",
                title="Search",
                summary="Results page.",
                text_excerpt="Results are visible.",
            )

    planner = QueuePlanner(
        [
            act_decision(
                skill="get_interactive_elements",
                skill_input={"max_elements": 40},
                rationale="Collect a larger element set.",
                expected_outcome="The runtime captures 40 interactive elements.",
            ),
            finish_decision("Done."),
        ]
    )
    loop = build_loop(
        planner=planner,
        browser=MaxElementsBrowser(),
        trace_dir=settings.trace_dir,
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    assert session.tool_results[0].data["elements"]
    assert len(session.tool_results[0].data["elements"]) == 40


def test_runtime_loop_transitions_to_waiting_for_confirmation_and_can_resume(
    tmp_path,
) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=5,
    )
    session = RuntimeSession(
        task=UserTask(request="Delete the selected record"),
        settings=settings,
    )
    planner = QueuePlanner(
        [
            act_decision(
                skill="click_element",
                skill_input={"selector": 'text="Delete"'},
                rationale="This click appears to delete the selected record.",
                expected_outcome="Delete the selected record from the current page.",
                risk_level=RiskLevel.HIGH,
                destructive=True,
                requires_confirmation=True,
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            ),
            finish_decision("The confirmed click was executed and the step can stop."),
        ]
    )
    loop = build_loop(
        planner=planner,
        browser=StubBrowserEngine(),
        trace_dir=settings.trace_dir,
    )

    paused_report = loop.run(session)

    assert paused_report.status == RuntimeStatus.WAITING_FOR_CONFIRMATION
    assert "request_id=" in paused_report.summary
    assert session.pending_confirmation is not None
    assert session.pending_action is not None
    assert session.pending_planner_decision is not None
    assert session.pending_planner_decision.chosen_skill == "click_element"
    assert session.tool_results[0].status == ToolExecutionStatus.WAITING_FOR_CONFIRMATION

    resumed_report = loop.continue_after_confirmation(
        session,
        ConfirmationDecision(
            request_id=session.pending_confirmation.request_id,
            approved=True,
        ),
    )

    assert resumed_report.status == RuntimeStatus.COMPLETED
    assert session.pending_confirmation is None
    assert [action.tool_name for action in session.actions] == [
        "click_element",
        "finish_task",
    ]


def test_runtime_loop_transitions_to_waiting_for_user_and_can_resume(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=4,
    )
    session = RuntimeSession(
        task=UserTask(request="Choose the account and stop"),
        settings=settings,
    )
    loop = build_loop(
        planner=AskThenFinishPlanner(),
        browser=StubBrowserEngine(),
        trace_dir=settings.trace_dir,
    )

    paused_report = loop.run(session)

    assert paused_report.status == RuntimeStatus.WAITING_FOR_USER
    assert session.pending_user_question is not None
    assert session.trace_items[0].planner_decision_type == PlannerDecisionType.ASK_USER

    resumed_report = loop.continue_after_user_answer(session, "Use account A.")

    assert resumed_report.status == RuntimeStatus.COMPLETED
    assert session.pending_user_question is None
    assert session.latest_user_response is not None
    assert session.latest_user_response.answer == "Use account A."


def test_runtime_loop_stops_after_multiple_no_progress_steps(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=5,
        max_no_progress_steps=2,
    )
    session = RuntimeSession(
        task=UserTask(request="Keep clicking a stuck button"),
        settings=settings,
    )
    planner = QueuePlanner(
        [
            act_decision(
                skill="click_element",
                skill_input={"selector": 'text="Retry"'},
                rationale="Try the button again.",
                expected_outcome="The page should change after the click.",
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            ),
            act_decision(
                skill="click_element",
                skill_input={"selector": 'text="Retry"'},
                rationale="Try the same button again after no visible change.",
                expected_outcome="The page should change after the click.",
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            ),
        ]
    )
    loop = build_loop(
        planner=planner,
        browser=NoProgressBrowser(
            initial_state=PageState(
                url="https://example.com/retry",
                title="Retry Page",
                summary="Retry page with no visible state changes.",
                text_excerpt="Retry again.",
            )
        ),
        trace_dir=settings.trace_dir,
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.FAILED
    assert "without observable progress" in report.summary.lower()
    assert session.no_progress_streak >= 2
    assert session.trace_items[-1].progress_outcome is not None
    assert session.trace_items[-1].progress_outcome.made_progress is False


def test_runtime_loop_honors_explicit_fail_decision(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Complete an impossible task"),
        settings=settings,
    )
    planner = QueuePlanner(
        [
            PlannerDecision(
                decision_type=PlannerDecisionType.FAIL,
                rationale="The task cannot continue honestly.",
                failure_reason="The required data is unavailable on the page.",
                completion_confidence=0.1,
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        ]
    )
    loop = build_loop(
        planner=planner,
        browser=StubBrowserEngine(),
        trace_dir=settings.trace_dir,
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.FAILED
    assert report.failure_reason == "The required data is unavailable on the page."
    assert not session.actions
    assert session.trace_items[0].planner_decision_type == PlannerDecisionType.FAIL


def test_runtime_loop_stops_repetitive_exploration_loop_even_with_text_changes(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=12,
    )
    session = RuntimeSession(
        task=UserTask(request="Find the weekly weather forecast"),
        settings=settings,
    )
    planner = QueuePlanner(
        [
            act_decision(
                skill="scroll_viewport",
                skill_input={"direction": "down", "amount": 900},
                rationale="Scroll for the forecast block.",
                expected_outcome="A lower section of the page becomes available.",
            ),
            act_decision(
                skill="extract_page_text",
                skill_input={"max_chars": 500},
                rationale="Read the page again after scrolling.",
                expected_outcome="The runtime captures more readable text.",
            ),
            act_decision(
                skill="scroll_viewport",
                skill_input={"direction": "down", "amount": 900},
                rationale="Scroll again for the forecast block.",
                expected_outcome="A lower section of the page becomes available.",
            ),
            act_decision(
                skill="extract_page_text",
                skill_input={"max_chars": 500},
                rationale="Read the page again after scrolling.",
                expected_outcome="The runtime captures more readable text.",
            ),
            act_decision(
                skill="scroll_viewport",
                skill_input={"direction": "down", "amount": 900},
                rationale="Scroll again for the forecast block.",
                expected_outcome="A lower section of the page becomes available.",
            ),
            act_decision(
                skill="extract_page_text",
                skill_input={"max_chars": 500},
                rationale="Read the page again after scrolling.",
                expected_outcome="The runtime captures more readable text.",
            ),
        ]
    )
    loop = build_loop(
        planner=planner,
        browser=ScrollingTextBrowser(),
        trace_dir=settings.trace_dir,
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.FAILED
    assert "repeatedly" in report.summary.lower()
    assert session.step_count == 6


def test_planner_context_includes_latest_extracted_text(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Read the current page"),
        settings=settings,
    )
    browser = StubBrowserEngine(
        initial_state=PageState(
            url="https://example.com/report",
            title="Report",
            summary="Report page.",
            text_excerpt="Short report excerpt.",
        )
    )
    loop = build_loop(
        planner=QueuePlanner(
            [
                act_decision(
                    skill="extract_page_text",
                    skill_input={"max_chars": 200},
                    rationale="Read the page.",
                    expected_outcome="The runtime captures readable page text.",
                )
            ]
        ),
        browser=browser,
        trace_dir=settings.trace_dir,
    )

    # Run one step manually through the runtime, then inspect planner-facing context.
    loop.run(session)
    context_text = build_planner_context(session.build_planner_context(available_skills=[]))

    assert "Latest extracted page text:" in context_text
    assert "Short report excerpt." in context_text


def test_planner_context_shows_text_end_for_long_extraction(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Read the full document"),
        settings=settings,
    )
    long_text = "START " + ("A" * 1900) + " FINISH_SECTION"
    browser = StubBrowserEngine(
        initial_state=PageState(
            url="https://example.com/spec",
            title="Spec",
            summary="Specification page.",
            text_excerpt=long_text,
        )
    )
    loop = build_loop(
        planner=QueuePlanner(
            [
                act_decision(
                    skill="extract_page_text",
                    skill_input={"max_chars": 4000},
                    rationale="Read the page.",
                    expected_outcome="The runtime captures readable page text.",
                )
            ]
        ),
        browser=browser,
        trace_dir=settings.trace_dir,
    )

    loop.run(session)
    context_text = build_planner_context(session.build_planner_context(available_skills=[]))

    assert "prompt_excerpt_note" in context_text
    assert "text_start:" in context_text
    assert "text_end:" in context_text
    assert "FINISH_SECTION" in context_text
