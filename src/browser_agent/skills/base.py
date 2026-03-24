"""Base contracts and execution helpers for runtime skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from browser_agent.browser.engine import BrowserEngine, BrowserOperationResult
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


@dataclass(slots=True)
class SkillExecutionError(RuntimeError):
    """Structured skill failure used by the runtime loop."""

    message: str
    error_code: str = "skill_execution_error"
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)


def raise_for_browser_result(
    result: "BrowserOperationResult",
    *,
    default_error_code: str,
) -> "BrowserOperationResult":
    """Raise a structured skill error when a browser action fails."""

    if result.ok:
        return result

    error_data: dict[str, Any] = {
        "browser_metadata": result.metadata,
    }
    if result.page_state is not None:
        error_data["observation"] = result.page_state.to_agent_observation().model_dump(
            mode="json"
        )

    raise SkillExecutionError(
        message=result.message,
        error_code=result.error_code or default_error_code,
        data=error_data,
        artifacts=result.artifacts,
    )


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
