"""Dialog and alert handling runtime skills."""

from __future__ import annotations

from pydantic import BaseModel

from browser_agent.runtime.models import AgentObservation
from browser_agent.skills.base import (
    BaseSkill,
    SkillContext,
    SkillExecutionError,
    raise_for_browser_result,
)


class InspectDialogInput(BaseModel):
    """Input contract for inspecting dialogs."""

    timeout_ms: int = 100  # Short timeout since dialogs are immediate


class InspectDialogOutput(BaseModel):
    """Output contract for dialog inspection."""

    visible: bool
    dialog_type: str | None = None  # alert, confirm, prompt
    message: str | None = None
    default_value: str | None = None  # for prompt dialogs
    page_title: str | None = None
    observation: AgentObservation | None = None


class InspectDialogSkill(BaseSkill):
    """Inspect any active dialog or alert on the page."""

    name = "inspect_dialog"
    description = "Check for and read the content of any active dialog, alert, confirm, or prompt on the page."
    input_schema = InspectDialogInput
    output_schema = InspectDialogOutput

    def execute(
        self,
        context: SkillContext,
        payload: InspectDialogInput,
    ) -> InspectDialogOutput:
        try:
            result = raise_for_browser_result(
                context.browser.inspect_dialog(timeout_ms=payload.timeout_ms),
                default_error_code="inspect_dialog_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to inspect dialogs on the page.",
                error_code="inspect_dialog_failed",
                data={"details": str(exc)},
            ) from exc

        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )
        metadata = result.metadata or {}

        return InspectDialogOutput(
            visible=metadata.get("dialog_visible", False),
            dialog_type=metadata.get("dialog_type"),
            message=metadata.get("dialog_message"),
            default_value=metadata.get("dialog_default_value"),
            page_title=result.page_state.title if result.page_state else None,
            observation=observation,
        )
