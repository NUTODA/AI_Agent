"""Base contracts for runtime skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from browser_agent.browser.engine import BrowserEngine
    from browser_agent.runtime.session import RuntimeSession
    from browser_agent.runtime.trace import TraceRecorder
    from browser_agent.safety.confirmations import ConfirmationManager
    from browser_agent.safety.guardrails import SafetyGuardrails


@dataclass(slots=True)
class SkillContext:
    """Dependencies available to a skill at execution time."""

    session: "RuntimeSession"
    browser: "BrowserEngine"
    trace_recorder: "TraceRecorder"
    safety_guardrails: "SafetyGuardrails"
    confirmation_manager: "ConfirmationManager"


class BaseSkill(ABC):
    """Abstract base class for all runtime skills."""

    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    def validate_input(self, payload: dict) -> BaseModel:
        """Validate the incoming payload against the skill input schema."""

        return self.input_schema.model_validate(payload)

    @abstractmethod
    def execute(self, context: SkillContext, payload: BaseModel) -> BaseModel:
        """Execute the skill and return its typed output payload."""
