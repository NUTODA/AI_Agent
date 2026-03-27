"""Tests for element_id preference and ambiguous selector rejection."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from browser_agent.llm.planner import (
    PlannerContext,
    PlannerDecision,
    PlannerDecisionType,
    PlannerProgressState,
    PlannerSessionState,
)
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    InteractiveElement,
    RiskLevel,
    ToolExecutionStatus,
    ToolResult,
    RuntimeStatus,
    UserTask,
)
from browser_agent.config import RuntimeSettings
from browser_agent.runtime.session import RuntimeSession
from browser_agent.browser.page_state import ElementRole, InteractiveElementState
from browser_agent.browser.selectors import resolve_target_candidates


def create_mock_loop():
    """Create a RuntimeLoop with mocked dependencies for testing."""
    from browser_agent.runtime.loop import RuntimeLoop

    mock_skill_registry = MagicMock()
    mock_skill_registry.list_names.return_value = []

    return RuntimeLoop(
        planner=MagicMock(),
        skill_registry=mock_skill_registry,
        browser=MagicMock(),
        safety_guardrails=MagicMock(),
        confirmation_manager=MagicMock(),
        trace_recorder=MagicMock(),
    )


class TestElementTargetingValidation:
    """Tests for the runtime loop element targeting validation."""

    def test_looks_like_generic_text_selector_detects_text_pattern(self) -> None:
        """_looks_like_generic_text_selector should detect text= selectors."""
        loop = create_mock_loop()

        # Should detect text="..." patterns
        assert loop._looks_like_generic_text_selector('text="Submit"') is True
        assert loop._looks_like_generic_text_selector("text='Submit'") is True
        assert loop._looks_like_generic_text_selector('text="Mark Spam"') is True
        assert loop._looks_like_generic_text_selector('a:has-text("Submit")') is True
        assert loop._looks_like_generic_text_selector('button:text-is("Submit")') is True

        # Should not detect other patterns
        assert loop._looks_like_generic_text_selector('[data-testid="submit"]') is False
        assert loop._looks_like_generic_text_selector('button#submit') is False
        assert loop._looks_like_generic_text_selector('role=button[name="Submit"]') is False

    def test_looks_like_generic_text_selector_detects_role_without_name(self) -> None:
        """_looks_like_generic_text_selector should detect role= without name=."""
        loop = create_mock_loop()

        # Should detect role= without name=
        assert loop._looks_like_generic_text_selector("role=button") is True
        assert loop._looks_like_generic_text_selector("role=link") is True

        # Should not detect role= with name=
        assert loop._looks_like_generic_text_selector('role=button[name="Submit"]') is False

    def test_selector_matches_element_with_text_pattern(self) -> None:
        """_selector_matches_element should match text= selectors to elements."""
        loop = create_mock_loop()

        element = InteractiveElement(
            element_id="element_test",
            label="Mark Spam",
            tag="button",
            role="button",
            text="Mark Spam",
            selector='[data-testid="spam-btn"]',
        )

        # Should match
        assert loop._selector_matches_element('text="Mark Spam"', element) is True
        assert loop._selector_matches_element("text='Mark Spam'", element) is True
        assert loop._selector_matches_element('a:has-text("Mark Spam")', element) is True

        # Should not match
        assert loop._selector_matches_element('text="Add to Cart"', element) is False
        assert loop._selector_matches_element('a:has-text("Add to Cart")', element) is False

    def test_count_matching_observed_elements_counts_matches(self) -> None:
        """_count_matching_observed_elements should count matching elements."""
        loop = create_mock_loop()

        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_1",
                    label="Add to Cart",
                    tag="button",
                    role="button",
                    text="Add to Cart",
                    selector='[data-testid="cart-1"]',
                ),
                InteractiveElement(
                    element_id="element_2",
                    label="Add to Cart",
                    tag="button",
                    role="button",
                    text="Add to Cart",
                    selector='[data-testid="cart-2"]',
                ),
                InteractiveElement(
                    element_id="element_3",
                    label="Submit",
                    tag="button",
                    role="button",
                    text="Submit",
                    selector='[data-testid="submit"]',
                ),
            ],
        )

        # Should count both "Add to Cart" buttons
        assert loop._count_matching_observed_elements('text="Add to Cart"', observation) == 2
        assert loop._count_matching_observed_elements('a:has-text("Add to Cart")', observation) == 2

        # Should count one "Submit" button
        assert loop._count_matching_observed_elements('text="Submit"', observation) == 1

        # Should count zero for non-matching
        assert loop._count_matching_observed_elements('text="Delete"', observation) == 0

    def test_validate_element_targeting_rejects_selector_when_element_id_available(self) -> None:
        """Validation should reject text selector when element_id is available."""
        loop = create_mock_loop()

        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_abc123",
                    label="Mark Spam",
                    tag="button",
                    role="button",
                    text="Mark Spam",
                    selector='[data-testid="spam-btn"]',
                ),
            ],
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Click the spam button",
            chosen_skill="click_element",
            skill_input={"selector": 'text="Mark Spam"'},  # Using selector, not element_id
            expected_outcome="The email is marked as spam",
        )

        result = loop._validate_element_targeting(decision, observation)

        # Should be converted to a fail decision
        assert result.decision.decision_type == PlannerDecisionType.FAIL
        assert "element_abc123" in (result.decision.failure_reason or "")
        assert "element_id" in (result.decision.failure_reason or "").lower()
        assert result.failure_kind is not None

    def test_validate_element_targeting_rejects_has_text_selector_when_element_id_available(self) -> None:
        """Validation should reject :has-text selectors when observed elements already have element_id."""
        loop = create_mock_loop()

        observation = AgentObservation(
            summary="Search results",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_spb_1",
                    label="Санкт-Петербург (север)",
                    tag="a",
                    role="link",
                    text="Санкт-Петербург (север)",
                    selector='tbody > tr:nth-of-type(1) > td:nth-of-type(1) > a',
                ),
                InteractiveElement(
                    element_id="element_spb_2",
                    label="Санкт-Петербург (юг)",
                    tag="a",
                    role="link",
                    text="Санкт-Петербург (юг)",
                    selector='tbody > tr:nth-of-type(2) > td:nth-of-type(1) > a',
                ),
            ],
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Click the matching city result.",
            chosen_skill="click_element",
            skill_input={"selector": 'a:has-text("Санкт-Петербург")'},
            expected_outcome="The city weather page opens.",
        )

        result = loop._validate_element_targeting(decision, observation)

        assert result.decision.decision_type == PlannerDecisionType.FAIL
        assert "element_id" in (result.decision.failure_reason or "").lower()
        assert result.failure_kind is not None

    def test_validate_element_targeting_allows_element_id_usage(self) -> None:
        """Validation should allow decision with element_id."""
        loop = create_mock_loop()

        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_abc123",
                    label="Mark Spam",
                    tag="button",
                    role="button",
                    text="Mark Spam",
                    selector='[data-testid="spam-btn"]',
                ),
            ],
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Click the spam button",
            chosen_skill="click_element",
            skill_input={"element_id": "element_abc123"},  # Using element_id
            expected_outcome="The email is marked as spam",
        )

        result = loop._validate_element_targeting(decision, observation)

        # Should remain an act decision
        assert result.decision.decision_type == PlannerDecisionType.ACT
        assert result.decision.chosen_skill == "click_element"

    def test_validate_element_targeting_rejects_redundant_navigation_click_after_full_text_extraction(self) -> None:
        """Navigation-like clicks should be blocked once the same page text is already extracted."""
        loop = create_mock_loop()

        observation = AgentObservation(
            page_url="https://example.com/spec",
            page_title="Spec Title",
            summary="Spec page",
            visible_text_excerpt="Spec Title Requirements Architecture",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_title_btn",
                    label="Spec Title",
                    tag="button",
                    role="button",
                    text="Spec Title",
                    selector='role=button[name="Spec Title"]',
                ),
            ],
        )
        session = RuntimeSession(
            task=UserTask(request="Summarize the spec"),
            settings=RuntimeSettings(max_steps=8),
        )
        session.add_tool_result(
            ToolResult(
                call_id="call_extract",
                skill_name="extract_page_text",
                status=ToolExecutionStatus.SUCCESS,
                message="Extracted page text.",
                data={
                    "text": (
                        "Spec Title\nRequirements\nArchitecture\n" * 120
                    ),
                    "truncated": False,
                    "page_url": "https://example.com/spec",
                },
            )
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Click the page title button to keep reading the document.",
            chosen_skill="click_element",
            skill_input={"element_id": "element_title_btn"},
            expected_outcome="More of the same document becomes available.",
        )

        result = loop._validate_element_targeting(
            decision,
            observation,
            session=session,
        )

        assert result.decision.decision_type == PlannerDecisionType.FAIL
        assert "redundant click" in (result.decision.failure_reason or "").lower()

    def test_validate_element_targeting_allows_click_after_scroll_following_read(self) -> None:
        """A follow-up click after scrolling should not be blocked as a redundant reread."""
        loop = create_mock_loop()
        observation = AgentObservation(
            page_url="https://example.com/spec",
            page_title="Spec",
            summary="Spec page",
            visible_text_excerpt="Spec Title Requirements Architecture",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_title_btn",
                    label="Spec Title",
                    tag="button",
                    role="button",
                    text="Spec Title",
                    selector='role=button[name="Spec Title"]',
                ),
            ],
        )
        session = RuntimeSession(
            task=UserTask(request="Summarize the spec"),
            settings=RuntimeSettings(max_steps=8),
        )
        session.add_tool_result(
            ToolResult(
                call_id="call_extract",
                skill_name="extract_page_text",
                status=ToolExecutionStatus.SUCCESS,
                message="Extracted page text.",
                data={
                    "text": (
                        "Spec Title\nRequirements\nArchitecture\n" * 120
                    ),
                    "truncated": False,
                    "page_url": "https://example.com/spec",
                },
            )
        )
        session.add_action(
            AgentAction(
                tool_name="scroll_viewport",
                rationale="Scroll to the next section.",
                parameters={"direction": "down", "amount": 900},
                expected_outcome="More content becomes visible.",
            )
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Click the page title button after scrolling to inspect the new section.",
            chosen_skill="click_element",
            skill_input={"element_id": "element_title_btn"},
            expected_outcome="A new section becomes available.",
        )

        result = loop._validate_element_targeting(
            decision,
            observation,
            session=session,
        )

        assert result.decision.decision_type == PlannerDecisionType.ACT

    def test_validate_element_targeting_allows_domain_like_result_controls_after_read(self) -> None:
        """Search-result domain controls should not be treated as redundant rereads."""
        loop = create_mock_loop()
        observation = AgentObservation(
            page_url="https://www.google.com/search?q=sushi",
            page_title="Ёбидоёби СПб - Поиск в Google",
            summary="Search results page",
            visible_text_excerpt="Search results are visible.",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_result_group",
                    label="spb.yobidoyobi.ru (+3), посмотреть ссылки по теме",
                    tag="button",
                    role="button",
                    text="spb.yobidoyobi.ru +3",
                    aria_label="spb.yobidoyobi.ru (+3), посмотреть ссылки по теме",
                    selector='role=button[name="spb.yobidoyobi.ru (+3), посмотреть ссылки по теме"]',
                ),
            ],
        )
        session = RuntimeSession(
            task=UserTask(request="Find sushi sets"),
            settings=RuntimeSettings(max_steps=8),
        )
        session.add_tool_result(
            ToolResult(
                call_id="call_extract",
                skill_name="extract_page_text",
                status=ToolExecutionStatus.SUCCESS,
                message="Extracted page text.",
                data={
                    "text": ("Search results with domains and descriptions. " * 80),
                    "truncated": False,
                    "page_url": "https://www.google.com/search?q=sushi",
                },
            )
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Open the official site result to inspect current prices.",
            chosen_skill="click_element",
            skill_input={"element_id": "element_result_group"},
            expected_outcome="The official Yobidoyobi site opens.",
        )

        result = loop._validate_element_targeting(
            decision,
            observation,
            session=session,
        )

        assert result.decision.decision_type == PlannerDecisionType.ACT

    def test_validate_element_targeting_allows_drilldown_click_after_extract(self) -> None:
        """Catalog drill-down clicks should not be blocked just because item text appears in extracted text."""
        loop = create_mock_loop()
        observation = AgentObservation(
            page_url="https://example.com/catalog",
            page_title="Catalog",
            summary="Catalog page",
            visible_text_excerpt="Budget Set 1499",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_set_card",
                    label="Budget Set",
                    tag="a",
                    role="link",
                    text="Budget Set",
                    selector='role=link[name="Budget Set"]',
                ),
            ],
        )
        session = RuntimeSession(
            task=UserTask(request="Find sets up to 1500"),
            settings=RuntimeSettings(max_steps=8),
        )
        session.add_tool_result(
            ToolResult(
                call_id="call_extract",
                skill_name="extract_page_text",
                status=ToolExecutionStatus.SUCCESS,
                message="Extracted page text.",
                data={
                    "text": ("Budget Set 1499\nAnother Set 1699\n" * 80),
                    "truncated": False,
                    "page_url": "https://example.com/catalog",
                },
            )
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Open the set details to verify the exact composition and price.",
            chosen_skill="click_element",
            skill_input={"element_id": "element_set_card"},
            expected_outcome="The set detail page opens for verification.",
        )

        result = loop._validate_element_targeting(
            decision,
            observation,
            session=session,
        )

        assert result.decision.decision_type == PlannerDecisionType.ACT

    def test_validate_element_targeting_rejects_ambiguous_selector(self) -> None:
        """Validation should reject selector matching multiple elements.

        Note: The policy violation (element_id available) is caught first before ambiguity check.
        This is still correct behavior - the planner should use element_id when available.
        """
        loop = create_mock_loop()

        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_1",
                    label="Add to Cart",
                    tag="button",
                    role="button",
                    text="Add to Cart",
                    selector='[data-testid="cart-1"]',
                ),
                InteractiveElement(
                    element_id="element_2",
                    label="Add to Cart",
                    tag="button",
                    role="button",
                    text="Add to Cart",
                    selector='[data-testid="cart-2"]',
                ),
            ],
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Click add to cart",
            chosen_skill="click_element",
            skill_input={"selector": 'text="Add to Cart"'},  # Ambiguous
            expected_outcome="Item added to cart",
        )

        result = loop._validate_element_targeting(decision, observation)

        # Should be converted to a fail decision
        # Note: The policy violation (element_id available) is caught before ambiguity check
        assert result.decision.decision_type == PlannerDecisionType.FAIL
        assert "element_id" in (result.decision.failure_reason or "").lower()
        # The selector matches multiple elements, but the policy violation is caught first
        assert "element_1" in (result.decision.failure_reason or "") or "element_2" in (result.decision.failure_reason or "")

    def test_validate_element_targeting_skips_non_targeting_skills(self) -> None:
        """Validation should skip non-element-targeting skills."""
        loop = create_mock_loop()

        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_abc123",
                    label="Mark Spam",
                    tag="button",
                    role="button",
                    text="Mark Spam",
                    selector='[data-testid="spam-btn"]',
                ),
            ],
        )

        # navigate doesn't target elements, so validation should skip it
        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Go to inbox",
            chosen_skill="navigate",
            skill_input={"url": "https://example.com/inbox"},
            expected_outcome="Inbox page loads",
        )

        result = loop._validate_element_targeting(decision, observation)

        # Should remain unchanged
        assert result.decision.decision_type == PlannerDecisionType.ACT
        assert result.decision.chosen_skill == "navigate"

    def test_validate_element_targeting_allows_fallback_selector_for_unobserved_elements(self) -> None:
        """Validation should allow selector when element is NOT in observation."""
        loop = create_mock_loop()

        # Empty observation - element not present
        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[],
        )

        decision = PlannerDecision(
            decision_type=PlannerDecisionType.ACT,
            rationale="Click the button",
            chosen_skill="click_element",
            skill_input={"selector": 'text="Submit"'},
            expected_outcome="Form submits",
        )

        result = loop._validate_element_targeting(decision, observation)

        # Should remain an act decision since element is not in observation
        assert result.decision.decision_type == PlannerDecisionType.ACT


class TestElementIdResolution:
    """Tests for element_id to selector candidate resolution."""

    def test_resolve_target_candidates_returns_stable_selectors(self) -> None:
        """When element_id resolves to cached element, return its selector candidates."""
        element = InteractiveElementState(
            element_id="element_test_123",
            name="Submit Order",
            tag="button",
            role=ElementRole.BUTTON,
            selector="form > button",
            text="Submit Order",
            attributes={"data-testid": "submit-btn"},
            clickable=True,
        )

        resolution = resolve_target_candidates(
            "element_test_123",
            {"element_test_123": element}
        )

        assert resolution.used_element_reference is True
        assert resolution.matched_element_id == "element_test_123"
        # Should have candidates from the element, not just raw selector
        assert len(resolution.candidates) > 0
        # First candidate should be the highest priority (testid)
        assert resolution.candidates[0].value == '[data-testid="submit-btn"]'

    def test_resolve_target_candidates_falls_back_for_stale_reference(self) -> None:
        """When element_id is not in cache, mark as stale reference."""
        resolution = resolve_target_candidates(
            "element_missing_abc",
            {}  # Empty cache
        )

        assert resolution.used_element_reference is True
        assert resolution.matched_element_id == "element_missing_abc"
        assert resolution.candidates == []

    def test_resolve_target_candidates_handles_raw_selector(self) -> None:
        """When raw selector provided, return it as-is."""
        resolution = resolve_target_candidates(
            '[data-testid="custom-btn"]',
            {}
        )

        assert resolution.used_element_reference is False
        assert resolution.matched_element_id is None
        assert len(resolution.candidates) == 1
        assert resolution.candidates[0].value == '[data-testid="custom-btn"]'


class TestObservationRendering:
    """Tests for improved observation formatting."""

    def test_render_observation_shows_element_id_first(self) -> None:
        """Observation rendering should emphasize element_id for planner."""
        from browser_agent.llm.prompts import _render_observation
        from browser_agent.llm.planner import PlannerContext, PlannerSessionState
        from browser_agent.runtime.models import UserTask, RuntimeStatus

        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_abc123",
                    label="Add to Cart",
                    tag="button",
                    role="button",
                    text="Add to Cart",
                    selector='[data-testid="add-cart-1"]',
                    selector_candidates=['[data-testid="add-cart-1"]', 'text="Add to Cart"'],
                    attributes={"data-testid": "add-cart-1"},
                )
            ],
        )

        context = PlannerContext(
            task=UserTask(request="Test"),
            current_observation=observation,
            session_state=PlannerSessionState(
                session_id="test",
                status=RuntimeStatus.RUNNING,
                step_count=0,
                max_steps=10,
            ),
        )

        rendered = _render_observation(context)

        # Should contain element_id prominently
        assert "element_abc123" in rendered
        # Should show the element in the list format
        assert "[element_abc123]" in rendered
        # Should show testid attribute
        assert "testid=add-cart-1" in rendered

    def test_render_observation_shows_form_field_ids(self) -> None:
        """Observation rendering should show field_id for form fields."""
        from browser_agent.llm.prompts import _render_observation
        from browser_agent.llm.planner import PlannerContext, PlannerSessionState
        from browser_agent.runtime.models import UserTask, RuntimeStatus, FormFieldSummary

        observation = AgentObservation(
            summary="Test page",
            interactive_elements=[],
            form_fields=[
                FormFieldSummary(
                    field_id="field_xyz789",
                    label="Email Address",
                    field_type="email",
                    required=True,
                    selector='input[type="email"]',
                )
            ],
        )

        context = PlannerContext(
            task=UserTask(request="Test"),
            current_observation=observation,
            session_state=PlannerSessionState(
                session_id="test",
                status=RuntimeStatus.RUNNING,
                step_count=0,
                max_steps=10,
            ),
        )

        rendered = _render_observation(context)

        # Should contain field_id prominently
        assert "field_xyz789" in rendered
        assert "[field_xyz789]" in rendered

    def test_render_observation_prioritizes_result_links(self) -> None:
        """Search-result links should appear before generic controls in planner context."""
        from browser_agent.llm.prompts import _render_observation
        from browser_agent.llm.planner import PlannerContext, PlannerSessionState
        from browser_agent.runtime.models import UserTask, RuntimeStatus

        observation = AgentObservation(
            summary="Search results page",
            interactive_elements=[
                InteractiveElement(
                    element_id="element_settings",
                    label="Settings",
                    tag="button",
                    role="button",
                    selector='role=button[name="Settings"]',
                    is_clickable=True,
                ),
                InteractiveElement(
                    element_id="element_result",
                    label="Ёбидоёби - Доставка суши",
                    tag="a",
                    role="link",
                    text="Ёбидоёби - Доставка суши",
                    selector='[data-testid="result-title-a"]',
                    is_clickable=True,
                    attributes={"data-testid": "result-title-a"},
                ),
            ],
        )

        context = PlannerContext(
            task=UserTask(request="Find a result"),
            current_observation=observation,
            session_state=PlannerSessionState(
                session_id="test",
                status=RuntimeStatus.RUNNING,
                step_count=0,
                max_steps=10,
            ),
        )

        rendered = _render_observation(context)

        assert rendered.find("element_result") < rendered.find("element_settings")


class TestSkillFieldDescriptions:
    """Tests for updated skill input field descriptions."""

    def test_click_element_prefers_element_id_in_description(self) -> None:
        """ClickElementInput should emphasize element_id preference."""
        from browser_agent.skills.interaction import ClickElementInput

        schema = ClickElementInput.model_json_schema()
        element_id_desc = schema["properties"]["element_id"].get("description", "")
        selector_desc = schema["properties"]["selector"].get("description", "")

        assert "primary" in element_id_desc.lower()
        assert "fallback" in selector_desc.lower()

    def test_type_text_prefers_element_id_in_description(self) -> None:
        """TypeTextInput should emphasize element_id preference."""
        from browser_agent.skills.interaction import TypeTextInput

        schema = TypeTextInput.model_json_schema()
        element_id_desc = schema["properties"]["element_id"].get("description", "")
        selector_desc = schema["properties"]["selector"].get("description", "")

        assert "primary" in element_id_desc.lower()
        assert "fallback" in selector_desc.lower()

    def test_select_option_prefers_element_id_in_description(self) -> None:
        """SelectOptionInput should emphasize element_id preference."""
        from browser_agent.skills.interaction import SelectOptionInput

        schema = SelectOptionInput.model_json_schema()
        element_id_desc = schema["properties"]["element_id"].get("description", "")
        selector_desc = schema["properties"]["selector"].get("description", "")

        assert "primary" in element_id_desc.lower()
        assert "fallback" in selector_desc.lower()

    def test_press_key_prefers_element_id_in_description(self) -> None:
        """PressKeyInput should emphasize element_id preference."""
        from browser_agent.skills.interaction import PressKeyInput

        schema = PressKeyInput.model_json_schema()
        element_id_desc = schema["properties"]["element_id"].get("description", "")
        selector_desc = schema["properties"]["selector"].get("description", "")

        assert "primary" in element_id_desc.lower()
        assert "fallback" in selector_desc.lower()
