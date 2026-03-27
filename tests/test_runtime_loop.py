"""Runtime-loop tests for the structured multi-step agent."""

from __future__ import annotations

from unittest.mock import MagicMock

from browser_agent.browser.engine import BrowserOperationResult, StubBrowserEngine
from browser_agent.browser.page_state import ElementRole, InteractiveElementState, PageState
from browser_agent.config import RuntimeSettings
from browser_agent.llm.prompts import build_planner_context
from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    FormFieldSummary,
    InteractiveElement,
    HumanInterventionKind,
    PlannerDecisionType,
    PlannerProgressState,
    ProgressOutcome,
    RiskLevel,
    RuntimeStatus,
    ToolResult,
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


class InvalidThenValidTargetingPlanner:
    """Emit one invalid targeting decision, then recover with a valid one."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        self.calls += 1
        if self.calls == 1:
            return act_decision(
                skill="click_element",
                skill_input={"selector": 'text="Buy now"'},
                rationale="Click the observed CTA.",
                expected_outcome="The CTA is activated.",
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        if self.calls == 2:
            return act_decision(
                skill="click_element",
                skill_input={"element_id": "element_buy_now"},
                rationale="Retry with the observed element_id.",
                expected_outcome="The CTA is activated.",
            )
        return finish_decision("Recovered from invalid targeting and completed the task.")


class RedundantExplorationThenFinishPlanner:
    """Emit one redundant exploration step, then finish after runtime replan."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        self.calls += 1
        if self.calls == 1:
            return act_decision(
                skill="scroll_viewport",
                skill_input={"direction": "down", "amount": 1200},
                rationale="Scroll further to load more prices from the same listing.",
                expected_outcome="More products become visible on the same page.",
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        return finish_decision(
            "The page already contained enough extracted evidence to stop."
        )


class RepeatedElementScanThenFinishPlanner:
    """Repeat get_interactive_elements once, then finish after runtime replan."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        self.calls += 1
        if self.calls == 1:
            return act_decision(
                skill="get_interactive_elements",
                skill_input={"max_elements": 120},
                rationale="Collect the interactive elements again.",
                expected_outcome="The runtime captures more controls from the same page.",
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        return finish_decision("The existing observation already had the needed controls.")


class RedundantSearchRefinementThenFinishPlanner:
    """Try an unnecessary search input after extraction, then finish on replan."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        self.calls += 1
        if self.calls == 1:
            return act_decision(
                skill="type_text",
                skill_input={"field_id": "field_search", "text": "мини"},
                rationale="Use the page search to narrow the visible sets under the budget.",
                expected_outcome="Only the cheapest relevant sets remain visible.",
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        return finish_decision("The extracted listing already contains enough budget options.")


class RedundantSortRefinementThenFinishPlanner:
    """Try an unnecessary sort click after extraction, then finish on replan."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, planner_context) -> PlannerDecision:
        del planner_context
        self.calls += 1
        if self.calls == 1:
            return act_decision(
                skill="click_element",
                skill_input={"element_id": "element_sort_price"},
                rationale="Sort the sets by best price to make the answer easier to read.",
                expected_outcome="The list is reordered by price.",
                progress_assessment=PlannerProgressState.NO_PROGRESS,
            )
        return finish_decision("The extracted listing already contains enough priced options.")


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


class BrokenObservationBrowser(StubBrowserEngine):
    """Stub browser that raises a descriptive observation failure."""

    def observe_page(self):
        raise RuntimeError("DOM snapshot evaluation crashed")


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


def test_runtime_loop_replans_after_recoverable_targeting_validation(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=4,
    )
    browser = StubBrowserEngine(
        initial_state=PageState(
            url="https://example.com/catalog",
            title="Catalog",
            summary="Catalog page.",
            text_excerpt="Buy now button is visible.",
            interactive_elements=[
                InteractiveElementState(
                    element_id="element_buy_now",
                    name="Buy now",
                    tag="button",
                    role=ElementRole.BUTTON,
                    selector='[data-testid="buy-now"]',
                    text="Buy now",
                    clickable=True,
                    attributes={"data-testid": "buy-now"},
                )
            ],
        )
    )
    session = RuntimeSession(
        task=UserTask(request="Open the buy flow"),
        settings=settings,
    )
    planner = InvalidThenValidTargetingPlanner()
    loop = build_loop(planner=planner, browser=browser, trace_dir=settings.trace_dir)

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    assert planner.calls == 3
    assert [action.tool_name for action in session.actions] == [
        "click_element",
        "finish_task",
    ]
    assert any(
        "rejected by runtime validation" in line
        for line in session.execution_history_summary
    )


def test_runtime_loop_auto_finishes_after_redundant_exploration_validation(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=4,
    )
    browser = StubBrowserEngine(
        initial_state=PageState(
            url="https://example.com/catalog",
            title="Catalog",
            summary="Catalog page.",
            text_excerpt="Affordable sets are listed on the page.",
        )
    )
    session = RuntimeSession(
        task=UserTask(request="Find sets under the budget"),
        settings=settings,
    )
    session.add_observation(
        AgentObservation(
            page_url="https://example.com/catalog",
            page_title="Catalog",
            summary="Catalog page.",
            visible_text_excerpt="Affordable sets are listed on the page.",
        )
    )
    session.add_action(
        AgentAction(
            tool_name="extract_page_text",
            rationale="Read the listing text.",
            parameters={"max_chars": 4000},
            expected_outcome="Capture the visible listing text.",
        )
    )
    session.add_tool_result(
        ToolResult(
            call_id="call_existing_extract",
            skill_name="extract_page_text",
            status=ToolExecutionStatus.SUCCESS,
            message="Skill `extract_page_text` completed successfully.",
            data={
                "text": (
                    "Starter set 1 239 ₽. Family set 1 159 ₽. Lunch combo 1 190 ₽. "
                    "Party set 1 129 ₽."
                ),
                "truncated": False,
                "page_url": "https://example.com/catalog",
            },
            duration_ms=8,
        )
    )
    planner = RedundantExplorationThenFinishPlanner()
    loop = build_loop(planner=planner, browser=browser, trace_dir=settings.trace_dir)

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    assert "Found:" in report.summary
    assert "Did:" in report.summary
    assert "Starter set 1 239 ₽" in report.summary
    assert planner.calls == 1
    assert [action.tool_name for action in session.actions] == [
        "extract_page_text",
        "finish_task",
    ]
    assert any(
        "converting the rejected planner action into finish" in line
        and "multiple price or value mentions" in line
        for line in session.execution_history_summary
    )


def test_runtime_loop_replans_after_repeated_get_interactive_elements(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=4,
    )
    browser = StubBrowserEngine(
        initial_state=PageState(
            url="https://example.com/catalog",
            title="Catalog",
            summary="Catalog page.",
            text_excerpt="Catalog content is visible.",
            interactive_elements=[
                InteractiveElementState(
                    element_id="element_sets",
                    name="Наборы",
                    tag="a",
                    role=ElementRole.LINK,
                    selector='a[href="/menu/nabory"]',
                    text="Наборы",
                    clickable=True,
                    attributes={"href": "/menu/nabory"},
                )
            ],
        )
    )
    session = RuntimeSession(
        task=UserTask(request="Inspect the visible controls"),
        settings=settings,
    )
    session.add_observation(
        AgentObservation(
            page_url="https://example.com/catalog",
            page_title="Catalog",
            summary="Catalog page.",
            visible_text_excerpt="Catalog content is visible.",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_sets",
                    label="Наборы",
                    tag="a",
                    role="link",
                    selector='a[href="/menu/nabory"]',
                    text="Наборы",
                    is_clickable=True,
                    attributes={"href": "/menu/nabory"},
                )
            ],
        )
    )
    session.add_action(
        AgentAction(
            tool_name="get_interactive_elements",
            rationale="Collect the controls.",
            parameters={"max_elements": 120},
            expected_outcome="The visible controls are captured.",
        )
    )
    session.add_tool_result(
        ToolResult(
            call_id="call_existing_elements",
            skill_name="get_interactive_elements",
            status=ToolExecutionStatus.SUCCESS,
            message="Skill `get_interactive_elements` completed successfully.",
            data={
                "elements": [
                    {
                        "element_id": "element_sets",
                        "label": "Наборы",
                        "tag": "a",
                        "role": "link",
                        "selector": 'a[href="/menu/nabory"]',
                    }
                ]
            },
            duration_ms=8,
        )
    )
    planner = RepeatedElementScanThenFinishPlanner()
    loop = build_loop(planner=planner, browser=browser, trace_dir=settings.trace_dir)

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    assert planner.calls == 2
    assert [action.tool_name for action in session.actions] == [
        "get_interactive_elements",
        "finish_task",
    ]
    assert any(
        "rejected by runtime validation" in line
        and "already includes the result of the most recent `get_interactive_elements` call"
        in line
        for line in session.execution_history_summary
    )


def test_runtime_loop_auto_finishes_after_redundant_search_refinement(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=4,
    )
    browser = StubBrowserEngine(
        initial_state=PageState(
            url="https://example.com/menu/nabory",
            title="Наборы",
            summary="Listing page with visible sets.",
            text_excerpt="Visible sets and prices.",
        )
    )
    session = RuntimeSession(
        task=UserTask(request="Глянь сеты роллов до 1500 ₽"),
        settings=settings,
    )
    session.add_observation(
        AgentObservation(
            page_url="https://example.com/menu/nabory",
            page_title="Наборы",
            summary="Listing page with visible sets.",
            visible_text_excerpt="Visible sets and prices.",
            form_fields=[
                FormFieldSummary(
                    field_id="field_search",
                    label="Искать блюда",
                    selector='input[name="search"]',
                    field_type="text",
                )
            ],
        )
    )
    session.add_action(
        AgentAction(
            tool_name="extract_page_text",
            rationale="Read the listing text.",
            parameters={"max_chars": 4000},
            expected_outcome="Capture the visible listing text.",
        )
    )
    session.add_tool_result(
        ToolResult(
            call_id="call_existing_extract",
            skill_name="extract_page_text",
            status=ToolExecutionStatus.SUCCESS,
            message="Skill `extract_page_text` completed successfully.",
            data={
                "text": (
                    "Филяй 1 499 ₽. Ёби Хит Комбо 1 349 ₽. Химицу 1 349 ₽. "
                    "Табэ Сусу 1 485 ₽."
                ),
                "truncated": False,
                "page_url": "https://example.com/menu/nabory",
            },
            duration_ms=8,
        )
    )
    planner = RedundantSearchRefinementThenFinishPlanner()
    loop = build_loop(planner=planner, browser=browser, trace_dir=settings.trace_dir)

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    assert "Что нашел:" in report.summary
    assert "Что сделал:" in report.summary
    assert "Филяй 1 499 ₽" in report.summary
    assert planner.calls == 1
    assert [action.tool_name for action in session.actions] == [
        "extract_page_text",
        "finish_task",
    ]
    assert any(
        "converting the rejected planner action into finish" in line
        and "search or filter input" in line
        for line in session.execution_history_summary
    )


def test_runtime_loop_auto_finishes_after_redundant_sort_refinement(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=4,
    )
    browser = StubBrowserEngine(
        initial_state=PageState(
            url="https://example.com/menu/nabory",
            title="Наборы",
            summary="Listing page with visible sets.",
            text_excerpt="Visible sets and prices.",
            interactive_elements=[
                InteractiveElementState(
                    element_id="element_sort_price",
                    name="Лучшая цена без скидок",
                    tag="button",
                    role=ElementRole.BUTTON,
                    selector='button[data-sort="price"]',
                    text="Лучшая цена без скидок",
                    clickable=True,
                )
            ],
        )
    )
    session = RuntimeSession(
        task=UserTask(request="Глянь сеты роллов до 1500 ₽"),
        settings=settings,
    )
    session.add_observation(
        AgentObservation(
            page_url="https://example.com/menu/nabory",
            page_title="Наборы",
            summary="Listing page with visible sets.",
            visible_text_excerpt="Visible sets and prices.",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_sort_price",
                    label="Лучшая цена без скидок",
                    tag="button",
                    role="button",
                    selector='button[data-sort="price"]',
                    text="Лучшая цена без скидок",
                    is_clickable=True,
                )
            ],
        )
    )
    session.add_action(
        AgentAction(
            tool_name="extract_page_text",
            rationale="Read the listing text.",
            parameters={"max_chars": 4000},
            expected_outcome="Capture the visible listing text.",
        )
    )
    session.add_tool_result(
        ToolResult(
            call_id="call_existing_extract",
            skill_name="extract_page_text",
            status=ToolExecutionStatus.SUCCESS,
            message="Skill `extract_page_text` completed successfully.",
            data={
                "text": (
                    "Филяй 1 499 ₽. Ёби Хит Комбо 1 349 ₽. Химицу 1 349 ₽. "
                    "Табэ Сусу 1 485 ₽."
                ),
                "truncated": False,
                "page_url": "https://example.com/menu/nabory",
            },
            duration_ms=8,
        )
    )
    planner = RedundantSortRefinementThenFinishPlanner()
    loop = build_loop(planner=planner, browser=browser, trace_dir=settings.trace_dir)

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    assert planner.calls == 1
    assert [action.tool_name for action in session.actions] == [
        "extract_page_text",
        "finish_task",
    ]
    assert any(
        "converting the rejected planner action into finish" in line
        and "sort, filter, or search" in line
        for line in session.execution_history_summary
    )


def test_runtime_loop_surfaces_observation_failure_details(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Observe the page"),
        settings=settings,
    )
    loop = build_loop(
        planner=QueuePlanner([]),
        browser=BrokenObservationBrowser(),
        trace_dir=settings.trace_dir,
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.FAILED
    assert "DOM snapshot evaluation crashed" in (report.failure_reason or "")


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


def test_get_interactive_elements_converts_browser_element_state_output(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
    )
    session = RuntimeSession(
        task=UserTask(request="Collect interactive elements"),
        settings=settings,
    )

    class BrowserStateElementsBrowser(StubBrowserEngine):
        def get_interactive_elements(self, max_elements: int = 25):
            return [
                InteractiveElementState(
                    element_id="element_menu_sets",
                    name="Наборы",
                    tag="a",
                    role=ElementRole.LINK,
                    selector='a[href="/menu/nabory"]',
                    text="Наборы",
                    clickable=True,
                    attributes={"href": "/menu/nabory"},
                )
            ][:max_elements]

        def observe_page(self):
            return PageState(
                url="https://spb.yobidoyobi.ru/menu",
                title="Menu",
                summary="Menu page.",
                text_excerpt="Menu categories are visible.",
            )

    planner = QueuePlanner(
        [
            act_decision(
                skill="get_interactive_elements",
                skill_input={"max_elements": 10},
                rationale="Collect interactive elements.",
                expected_outcome="The runtime captures visible controls.",
            ),
            finish_decision("Done."),
        ]
    )
    loop = build_loop(
        planner=planner,
        browser=BrowserStateElementsBrowser(),
        trace_dir=settings.trace_dir,
    )

    report = loop.run(session)

    assert report.status == RuntimeStatus.COMPLETED
    elements = session.tool_results[0].data["elements"]
    assert len(elements) == 1
    assert elements[0]["element_id"] == "element_menu_sets"
    assert elements[0]["role"] == "link"


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
    session.no_progress_streak = 2
    session.actions.extend(
        [
            AgentAction(
                tool_name="scroll_viewport",
                rationale="Scroll for the forecast block.",
                parameters={"direction": "down", "amount": 900},
                expected_outcome="A lower section becomes available.",
            ),
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read after scrolling.",
                parameters={"max_chars": 500},
                expected_outcome="Capture more readable text.",
            ),
            AgentAction(
                tool_name="scroll_viewport",
                rationale="Scroll again.",
                parameters={"direction": "down", "amount": 900},
                expected_outcome="A lower section becomes available.",
            ),
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read after scrolling again.",
                parameters={"max_chars": 500},
                expected_outcome="Capture more readable text.",
            ),
            AgentAction(
                tool_name="scroll_viewport",
                rationale="Scroll again.",
                parameters={"direction": "down", "amount": 900},
                expected_outcome="A lower section becomes available.",
            ),
        ]
    )
    session.trace_items.extend(
        [MagicMock(current_url="https://example.com/weather") for _ in range(5)]
    )
    loop = build_loop(
        planner=QueuePlanner([]),
        browser=ScrollingTextBrowser(),
        trace_dir=settings.trace_dir,
    )

    should_stop = loop._is_repetitive_exploration_loop(
        action=AgentAction(
            tool_name="extract_page_text",
            rationale="Read after another scroll.",
            parameters={"max_chars": 500},
            expected_outcome="Capture more readable text.",
        ),
        session=session,
        current_observation=AgentObservation(
            page_url="https://example.com/weather",
            page_title="Weather",
            summary="Weather page with repetitive exploration.",
            visible_text_excerpt="Chunk 6",
        ),
    )

    assert should_stop is True


def test_repetitive_exploration_loop_requires_stagnation(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=12,
    )
    session = RuntimeSession(
        task=UserTask(request="Find affordable sets"),
        settings=settings,
    )
    session.no_progress_streak = 0
    session.actions.extend(
        [
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read visible text.",
                parameters={"max_chars": 12000},
                expected_outcome="Capture visible text.",
            ),
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read more text.",
                parameters={"max_chars": 12000},
                expected_outcome="Capture more text.",
            ),
            AgentAction(
                tool_name="get_interactive_elements",
                rationale="Inspect visible controls.",
                parameters={"max_elements": 120},
                expected_outcome="Capture controls.",
            ),
            AgentAction(
                tool_name="scroll_viewport",
                rationale="Reveal more content.",
                parameters={"direction": "down", "amount": 1400},
                expected_outcome="Reveal more content.",
            ),
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read newly revealed content.",
                parameters={"max_chars": 12000},
                expected_outcome="Capture newly revealed text.",
            ),
        ]
    )
    session.trace_items.extend(
        [
            MagicMock(current_url="https://spb.yobidoyobi.ru/menu/nabory"),
            MagicMock(current_url="https://spb.yobidoyobi.ru/menu/nabory"),
            MagicMock(current_url="https://spb.yobidoyobi.ru/menu/nabory"),
            MagicMock(current_url="https://spb.yobidoyobi.ru/menu/nabory"),
            MagicMock(current_url="https://spb.yobidoyobi.ru/menu/nabory"),
        ]
    )
    loop = build_loop(
        planner=QueuePlanner([]),
        browser=StubBrowserEngine(),
        trace_dir=settings.trace_dir,
    )

    should_stop = loop._is_repetitive_exploration_loop(
        action=AgentAction(
            tool_name="get_interactive_elements",
            rationale="Inspect controls after scroll revealed more products.",
            parameters={"max_elements": 120},
            expected_outcome="Capture controls on the newly visible portion.",
        ),
        session=session,
        current_observation=AgentObservation(
            page_url="https://spb.yobidoyobi.ru/menu/nabory",
            page_title="Наборы",
            summary="Sets page with new content after scroll.",
            visible_text_excerpt="New products became visible after scroll.",
        ),
    )

    assert should_stop is False


def test_repetitive_exploration_loop_stops_on_weak_text_only_progress(tmp_path) -> None:
    settings = RuntimeSettings(
        trace_dir=tmp_path / "traces",
        artifact_dir=tmp_path / "artifacts",
        max_steps=12,
    )
    session = RuntimeSession(
        task=UserTask(request="Find roll sets under 1500 RUB"),
        settings=settings,
    )
    session.no_progress_streak = 0
    session.actions.extend(
        [
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read visible text.",
                parameters={"max_chars": 12000},
                expected_outcome="Capture visible text.",
            ),
            AgentAction(
                tool_name="scroll_viewport",
                rationale="Reveal more products.",
                parameters={"direction": "down", "amount": 1400},
                expected_outcome="Reveal more content.",
            ),
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read after scrolling.",
                parameters={"max_chars": 12000},
                expected_outcome="Capture more text.",
            ),
            AgentAction(
                tool_name="scroll_viewport",
                rationale="Reveal more products again.",
                parameters={"direction": "down", "amount": 1400},
                expected_outcome="Reveal more content.",
            ),
            AgentAction(
                tool_name="extract_page_text",
                rationale="Read after scrolling again.",
                parameters={"max_chars": 12000},
                expected_outcome="Capture more text.",
            ),
        ]
    )
    session.trace_items.extend(
        [
            MagicMock(
                current_url="https://spb.yobidoyobi.ru/menu/nabory",
                action_name="extract_page_text",
                progress_outcome=ProgressOutcome(
                    made_progress=True,
                    summary="Observable progress detected after the last planner step.",
                    signals=["visible text excerpt changed"],
                    no_progress_streak=0,
                ),
            ),
            MagicMock(
                current_url="https://spb.yobidoyobi.ru/menu/nabory",
                action_name="scroll_viewport",
                progress_outcome=ProgressOutcome(
                    made_progress=True,
                    summary="Observable progress detected after the last planner step.",
                    signals=["visible text excerpt changed"],
                    no_progress_streak=0,
                ),
            ),
            MagicMock(
                current_url="https://spb.yobidoyobi.ru/menu/nabory",
                action_name="extract_page_text",
                progress_outcome=ProgressOutcome(
                    made_progress=True,
                    summary="Observable progress detected after the last planner step.",
                    signals=["visible text excerpt changed"],
                    no_progress_streak=0,
                ),
            ),
            MagicMock(
                current_url="https://spb.yobidoyobi.ru/menu/nabory",
                action_name="scroll_viewport",
                progress_outcome=ProgressOutcome(
                    made_progress=True,
                    summary="Observable progress detected after the last planner step.",
                    signals=["visible text excerpt changed"],
                    no_progress_streak=0,
                ),
            ),
            MagicMock(
                current_url="https://spb.yobidoyobi.ru/menu/nabory",
                action_name="extract_page_text",
                progress_outcome=ProgressOutcome(
                    made_progress=True,
                    summary="Observable progress detected after the last planner step.",
                    signals=["visible text excerpt changed"],
                    no_progress_streak=0,
                ),
            ),
        ]
    )
    loop = build_loop(
        planner=QueuePlanner([]),
        browser=StubBrowserEngine(),
        trace_dir=settings.trace_dir,
    )

    should_stop = loop._is_repetitive_exploration_loop(
        action=AgentAction(
            tool_name="scroll_viewport",
            rationale="Keep looking for cheaper sets.",
            parameters={"direction": "down", "amount": 1400},
            expected_outcome="Reveal more content.",
        ),
        session=session,
        current_observation=AgentObservation(
            page_url="https://spb.yobidoyobi.ru/menu/nabory",
            page_title="Наборы",
            summary="Sets page with repeated text-only progress.",
            visible_text_excerpt="Another chunk of the same long listing.",
        ),
    )

    assert should_stop is True


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
