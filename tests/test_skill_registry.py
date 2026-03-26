"""Tests for the runtime skill registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from browser_agent.skills.base import BaseSkill, SkillContext
from browser_agent.skills.registry import SkillRegistry, build_default_registry


class DummyInput(BaseModel):
    value: str = "ok"


class DummyOutput(BaseModel):
    value: str


class DummySkill(BaseSkill):
    name = "dummy"
    description = "Dummy skill used in tests."
    input_schema = DummyInput
    output_schema = DummyOutput

    def execute(self, context: SkillContext, payload: DummyInput) -> DummyOutput:
        return DummyOutput(value=payload.value)


def test_default_registry_contains_mvp_skills() -> None:
    registry = build_default_registry()

    assert registry.list_names() == [
        "click_element",
        "extract_page_text",
        "finish_task",
        "get_interactive_elements",
        "inspect_dialog",
        "navigate",
        "observe_page",
        "press_key",
        "request_confirmation",
        "scroll_viewport",
        "select_option",
        "type_text",
        "upload_file",
        "wait_for_element",
    ]


def test_registry_rejects_duplicate_skill_names() -> None:
    registry = SkillRegistry()
    registry.register(DummySkill())

    with pytest.raises(ValueError):
        registry.register(DummySkill())
