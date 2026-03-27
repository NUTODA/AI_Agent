"""Tests for extended generic skills.

These tests verify the input/output contracts and basic execution
of the new skills added in Stage 6.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from browser_agent.browser.engine import BrowserOperationResult, StubBrowserEngine
from browser_agent.runtime.models import AgentObservation, FormFieldSummary, UserTask
from browser_agent.config import RuntimeSettings
from browser_agent.runtime.session import RuntimeSession
from browser_agent.skills.base import SkillContext
from browser_agent.skills.dialog import (
    InspectDialogInput,
    InspectDialogOutput,
    InspectDialogSkill,
)
from browser_agent.skills.file_handling import (
    UploadFileInput,
    UploadFileOutput,
    UploadFileSkill,
)
from browser_agent.skills.interaction import (
    PressKeyInput,
    PressKeyOutput,
    PressKeySkill,
    SelectOptionInput,
    SelectOptionOutput,
    SelectOptionSkill,
    TypeTextInput,
    TypeTextSkill,
)
from browser_agent.skills.navigation import (
    ScrollViewportInput,
    ScrollViewportOutput,
    ScrollViewportSkill,
)
from browser_agent.skills.observation import (
    WaitForElementInput,
    WaitForElementOutput,
    WaitForElementSkill,
)


class FloatScrollStubBrowser(StubBrowserEngine):
    """Stub that emits browser-like float scroll coords (scrollY can be fractional)."""

    def scroll_viewport(
        self,
        direction: str,
        amount: int,
        target: str | None = None,
    ) -> BrowserOperationResult:
        result = super().scroll_viewport(direction, amount, target)
        md = dict(result.metadata or {})
        md["scroll_x"] = 10.7
        md["scroll_y"] = 419.5
        return result.model_copy(update={"metadata": md})


class TestSelectOptionSkillContract:
    """Test the select_option skill input/output contracts."""

    def test_skill_has_correct_name(self) -> None:
        """Skill name should be 'select_option'."""
        skill = SelectOptionSkill()
        assert skill.name == "select_option"

    def test_skill_has_description(self) -> None:
        """Skill should have a non-empty description."""
        skill = SelectOptionSkill()
        assert len(skill.description) > 0
        assert "select" in skill.description.lower()

    def test_input_schema_requires_target(self) -> None:
        """Input must have either selector or element_id."""
        with pytest.raises(ValueError, match="selector.*element_id"):
            SelectOptionInput(option_value="opt1")

    def test_input_schema_requires_option_criteria(self) -> None:
        """Input must have either option_value or option_text."""
        with pytest.raises(ValueError, match="option_value.*option_text"):
            SelectOptionInput(selector="#dropdown")

    def test_input_schema_accepts_selector_and_value(self) -> None:
        """Valid input with selector and value should work."""
        input_data = SelectOptionInput(
            selector="#country",
            option_value="us",
        )
        assert input_data.selector == "#country"
        assert input_data.option_value == "us"

    def test_input_schema_accepts_element_id_and_text(self) -> None:
        """Valid input with element_id and text should work."""
        input_data = SelectOptionInput(
            element_id="state-select",
            option_text="California",
        )
        assert input_data.element_id == "state-select"
        assert input_data.option_text == "California"

    def test_output_schema_structure(self) -> None:
        """Output should have expected fields."""
        output = SelectOptionOutput(
            target="#country",
            selected_value="us",
            selected_text="United States",
            message="Option selected",
        )
        assert output.target == "#country"
        assert output.selected_value == "us"
        assert output.selected_text == "United States"


class TestTypeTextSkillContract:
    """Test the type_text skill input/output contracts."""

    def test_input_schema_accepts_field_id(self) -> None:
        input_data = TypeTextInput(field_id="field_city_search", text="Санкт")
        assert input_data.field_id == "field_city_search"
        assert input_data.text == "Санкт"

    def test_type_text_resolves_field_id_from_latest_observation(self) -> None:
        browser = MagicMock()
        browser.type_text.return_value = BrowserOperationResult(
            message="Typed text.",
            metadata={"resolved_target": 'input[id="mat-input-0"]'},
        )
        session = RuntimeSession(
            task=UserTask(request="Select Saint Petersburg"),
            settings=RuntimeSettings(max_steps=3),
        )
        session.add_observation(
            AgentObservation(
                summary="City picker is visible.",
                form_fields=[
                    FormFieldSummary(
                        field_id="field_city_search",
                        label="Поиск",
                        selector='input[id="mat-input-0"]',
                        field_type="text",
                    )
                ],
            )
        )
        context = SkillContext(
            session=session,
            browser=browser,
            trace_recorder=MagicMock(),
            safety_guardrails=MagicMock(),
            confirmation_manager=MagicMock(),
        )

        output = TypeTextSkill().execute(
            context,
            TypeTextInput(field_id="field_city_search", text="Санкт"),
        )

        browser.type_text.assert_called_once_with(
            'input[id="mat-input-0"]',
            "Санкт",
            clear_first=True,
            submit=False,
        )
        assert output.target == 'input[id="mat-input-0"]'

    def test_type_text_treats_field_like_element_id_as_field_reference(self) -> None:
        browser = MagicMock()
        browser.type_text.return_value = BrowserOperationResult(message="Typed text.")
        session = RuntimeSession(
            task=UserTask(request="Select Saint Petersburg"),
            settings=RuntimeSettings(max_steps=3),
        )
        session.add_observation(
            AgentObservation(
                summary="City picker is visible.",
                form_fields=[
                    FormFieldSummary(
                        field_id="field_city_search",
                        label="Поиск",
                        selector='input[id="mat-input-0"]',
                        field_type="text",
                    )
                ],
            )
        )
        context = SkillContext(
            session=session,
            browser=browser,
            trace_recorder=MagicMock(),
            safety_guardrails=MagicMock(),
            confirmation_manager=MagicMock(),
        )

        output = TypeTextSkill().execute(
            context,
            TypeTextInput(element_id="field_city_search", text="Санкт"),
        )

        browser.type_text.assert_called_once()
        assert output.target == 'input[id="mat-input-0"]'


class TestScrollViewportSkillContract:
    """Test the scroll_viewport skill input/output contracts."""

    def test_skill_has_correct_name(self) -> None:
        """Skill name should be 'scroll_viewport'."""
        skill = ScrollViewportSkill()
        assert skill.name == "scroll_viewport"

    def test_skill_has_description(self) -> None:
        """Skill should have a non-empty description."""
        skill = ScrollViewportSkill()
        assert len(skill.description) > 0
        assert "scroll" in skill.description.lower()

    def test_input_schema_has_defaults(self) -> None:
        """Input should have sensible defaults."""
        input_data = ScrollViewportInput()
        assert input_data.direction == "down"
        assert input_data.amount == 500
        assert input_data.selector is None

    def test_input_schema_accepts_custom_values(self) -> None:
        """Input should accept custom direction and amount."""
        input_data = ScrollViewportInput(
            direction="up",
            amount=300,
            selector="#content-area",
        )
        assert input_data.direction == "up"
        assert input_data.amount == 300
        assert input_data.selector == "#content-area"

    def test_output_schema_structure(self) -> None:
        """Output should have expected fields."""
        output = ScrollViewportOutput(
            direction="down",
            amount=500,
            target="#main",
            scroll_x=0,
            scroll_y=500,
            message="Scrolled successfully",
        )
        assert output.direction == "down"
        assert output.scroll_y == 500


class TestPressKeySkillContract:
    """Test the press_key skill input/output contracts."""

    def test_skill_has_correct_name(self) -> None:
        """Skill name should be 'press_key'."""
        skill = PressKeySkill()
        assert skill.name == "press_key"

    def test_skill_has_description(self) -> None:
        """Skill should have a non-empty description."""
        skill = PressKeySkill()
        assert len(skill.description) > 0
        assert "key" in skill.description.lower()

    def test_input_schema_requires_key(self) -> None:
        """Input must have a key specified."""
        # Key is required field, pydantic will error if missing
        with pytest.raises(ValueError):
            PressKeyInput()  # type: ignore[call-arg]

    def test_input_schema_accepts_key_only(self) -> None:
        """Valid input with just key should work."""
        input_data = PressKeyInput(key="Enter")
        assert input_data.key == "Enter"
        assert input_data.selector is None
        assert input_data.element_id is None

    def test_input_schema_accepts_key_with_target(self) -> None:
        """Valid input with key and target should work."""
        input_data = PressKeyInput(
            key="Tab",
            selector="#input-field",
        )
        assert input_data.key == "Tab"
        assert input_data.selector == "#input-field"

    def test_output_schema_structure(self) -> None:
        """Output should have expected fields."""
        output = PressKeyOutput(
            key="Enter",
            target="#form",
            message="Key pressed",
        )
        assert output.key == "Enter"
        assert output.target == "#form"


class TestWaitForElementSkillContract:
    """Test the wait_for_element skill input/output contracts."""

    def test_skill_has_correct_name(self) -> None:
        """Skill name should be 'wait_for_element'."""
        skill = WaitForElementSkill()
        assert skill.name == "wait_for_element"

    def test_skill_has_description(self) -> None:
        """Skill should have a non-empty description."""
        skill = WaitForElementSkill()
        assert len(skill.description) > 0
        assert "wait" in skill.description.lower()

    def test_input_schema_has_defaults(self) -> None:
        """Input should have sensible defaults."""
        input_data = WaitForElementInput(selector="#button")
        assert input_data.timeout_ms == 5000
        assert input_data.state == "visible"

    def test_input_schema_accepts_custom_timeout(self) -> None:
        """Input should accept custom timeout."""
        input_data = WaitForElementInput(
            selector="#loader",
            timeout_ms=10000,
            state="hidden",
        )
        assert input_data.timeout_ms == 10000
        assert input_data.state == "hidden"

    def test_output_schema_structure(self) -> None:
        """Output should have expected fields."""
        output = WaitForElementOutput(
            found=True,
            selector="#button",
            waited_ms=1500,
            state="visible",
            message="Element found",
        )
        assert output.found is True
        assert output.waited_ms == 1500
        assert output.state == "visible"


class TestUploadFileSkillContract:
    """Test the upload_file skill input/output contracts."""

    def test_skill_has_correct_name(self) -> None:
        """Skill name should be 'upload_file'."""
        skill = UploadFileSkill()
        assert skill.name == "upload_file"

    def test_skill_has_description(self) -> None:
        """Skill should have a non-empty description."""
        skill = UploadFileSkill()
        assert len(skill.description) > 0
        assert "upload" in skill.description.lower()

    def test_input_schema_requires_target(self) -> None:
        """Input must have either selector or element_id."""
        with pytest.raises(ValueError, match="selector.*element_id"):
            UploadFileInput(file_path="/tmp/test.pdf")

    def test_input_schema_requires_file_path(self) -> None:
        """Input must have file_path."""
        with pytest.raises(ValueError, match="file_path"):
            UploadFileInput(selector="#upload")  # type: ignore[call-arg]

    def test_input_schema_structure(self) -> None:
        """Valid input should work."""
        input_data = UploadFileInput(
            selector="#resume-upload",
            file_path="/path/to/resume.pdf",
        )
        assert input_data.selector == "#resume-upload"
        assert input_data.file_path == "/path/to/resume.pdf"

    def test_output_schema_structure(self) -> None:
        """Output should have expected fields."""
        output = UploadFileOutput(
            target="#resume-upload",
            file_name="resume.pdf",
            file_path="/path/to/resume.pdf",
            message="File uploaded",
        )
        assert output.file_name == "resume.pdf"
        assert output.target == "#resume-upload"


class TestInspectDialogSkillContract:
    """Test the inspect_dialog skill input/output contracts."""

    def test_skill_has_correct_name(self) -> None:
        """Skill name should be 'inspect_dialog'."""
        skill = InspectDialogSkill()
        assert skill.name == "inspect_dialog"

    def test_skill_has_description(self) -> None:
        """Skill should have a non-empty description."""
        skill = InspectDialogSkill()
        assert len(skill.description) > 0
        assert "dialog" in skill.description.lower()

    def test_input_schema_has_default_timeout(self) -> None:
        """Input should have sensible default timeout."""
        input_data = InspectDialogInput()
        assert input_data.timeout_ms == 100

    def test_input_schema_accepts_custom_timeout(self) -> None:
        """Input should accept custom timeout."""
        input_data = InspectDialogInput(timeout_ms=500)
        assert input_data.timeout_ms == 500

    def test_output_schema_no_dialog(self) -> None:
        """Output when no dialog is visible."""
        output = InspectDialogOutput(
            visible=False,
            dialog_type=None,
            message=None,
        )
        assert output.visible is False
        assert output.dialog_type is None

    def test_output_schema_with_dialog(self) -> None:
        """Output when dialog is visible."""
        output = InspectDialogOutput(
            visible=True,
            dialog_type="confirm",
            message="Are you sure you want to delete?",
            default_value=None,
        )
        assert output.visible is True
        assert output.dialog_type == "confirm"
        assert "sure" in output.message


class TestSkillExecution:
    """Test skill execution with mock browser."""

    @pytest.fixture
    def mock_context(self) -> SkillContext:
        """Create a mock skill context with stub browser."""
        browser = StubBrowserEngine()
        return SkillContext(
            session=MagicMock(),
            browser=browser,
            trace_recorder=MagicMock(),
            safety_guardrails=MagicMock(),
            confirmation_manager=MagicMock(),
        )

    def test_select_option_execution(self, mock_context: SkillContext) -> None:
        """select_option should call browser method."""
        skill = SelectOptionSkill()
        payload = SelectOptionInput(
            selector="#country",
            option_value="us",
        )

        result = skill.execute(mock_context, payload)

        assert isinstance(result, SelectOptionOutput)
        assert result.target == "#country"
        assert result.selected_value == "us"
        assert "selected" in result.message.lower()

    def test_scroll_viewport_execution(self, mock_context: SkillContext) -> None:
        """scroll_viewport should call browser method."""
        skill = ScrollViewportSkill()
        payload = ScrollViewportInput(
            direction="down",
            amount=300,
        )

        result = skill.execute(mock_context, payload)

        assert isinstance(result, ScrollViewportOutput)
        assert result.direction == "down"
        assert result.amount == 300
        assert "scroll" in result.message.lower()

    def test_scroll_viewport_float_scroll_coords_coerced_to_int(self) -> None:
        """scroll_viewport should tolerate float scroll_x/scroll_y from browser metadata."""
        browser = FloatScrollStubBrowser()
        context = SkillContext(
            session=MagicMock(),
            browser=browser,
            trace_recorder=MagicMock(),
            safety_guardrails=MagicMock(),
            confirmation_manager=MagicMock(),
        )
        skill = ScrollViewportSkill()
        payload = ScrollViewportInput(direction="down", amount=300)

        result = skill.execute(context, payload)

        assert isinstance(result, ScrollViewportOutput)
        assert result.scroll_x == 11
        assert result.scroll_y == 420
        assert isinstance(result.scroll_x, int)
        assert isinstance(result.scroll_y, int)

    def test_press_key_execution(self, mock_context: SkillContext) -> None:
        """press_key should call browser method."""
        skill = PressKeySkill()
        payload = PressKeyInput(key="Enter")

        result = skill.execute(mock_context, payload)

        assert isinstance(result, PressKeyOutput)
        assert result.key == "Enter"
        assert result.target is None  # No target specified

    def test_press_key_with_target_execution(self, mock_context: SkillContext) -> None:
        """press_key with target should pass target to browser."""
        skill = PressKeySkill()
        payload = PressKeyInput(
            key="Tab",
            selector="#input",
        )

        result = skill.execute(mock_context, payload)

        assert isinstance(result, PressKeyOutput)
        assert result.key == "Tab"
        assert result.target == "#input"

    def test_wait_for_element_execution(self, mock_context: SkillContext) -> None:
        """wait_for_element should call browser method."""
        skill = WaitForElementSkill()
        payload = WaitForElementInput(
            selector="#button",
            timeout_ms=5000,
            state="visible",
        )

        result = skill.execute(mock_context, payload)

        assert isinstance(result, WaitForElementOutput)
        assert result.selector == "#button"
        assert result.state == "visible"

    def test_inspect_dialog_execution(self, mock_context: SkillContext) -> None:
        """inspect_dialog should call browser method."""
        skill = InspectDialogSkill()
        payload = InspectDialogInput(timeout_ms=100)

        result = skill.execute(mock_context, payload)

        assert isinstance(result, InspectDialogOutput)
        assert result.visible is False  # Stub returns no dialog
        assert result.dialog_type is None


class TestSkillRegistryIntegration:
    """Test that new skills are properly registered."""

    def test_all_new_skills_in_default_registry(self) -> None:
        """All new skills should be in the default registry."""
        from browser_agent.skills.registry import build_default_registry

        registry = build_default_registry()

        expected_skills = [
            "select_option",
            "scroll_viewport",
            "press_key",
            "wait_for_element",
            "upload_file",
            "inspect_dialog",
        ]

        for skill_name in expected_skills:
            skill = registry.get(skill_name)
            assert skill is not None, f"Skill '{skill_name}' not found in registry"
            assert skill.name == skill_name
