"""Safety and confirmation runtime skills."""

from __future__ import annotations

from pydantic import BaseModel, Field

from browser_agent.runtime.models import ConfirmationRequest, RiskLevel
from browser_agent.skills.base import BaseSkill, SkillContext


class RequestConfirmationInput(BaseModel):
    """Input contract for generating a confirmation request."""

    action_id: str | None = None
    action_name: str
    rationale: str
    risk_level: RiskLevel
    consequences: list[str] = Field(default_factory=list)


class RequestConfirmationOutput(BaseModel):
    """Output contract for the confirmation skill."""

    confirmation_request: ConfirmationRequest


class RequestConfirmationSkill(BaseSkill):
    """Build a confirmation request for human review."""

    name = "request_confirmation"
    description = "Create a human confirmation request for a risky action."
    input_schema = RequestConfirmationInput
    output_schema = RequestConfirmationOutput

    def execute(
        self,
        context: SkillContext,
        payload: RequestConfirmationInput,
    ) -> RequestConfirmationOutput:
        from browser_agent.runtime.models import AgentAction

        synthetic_action = AgentAction(
            action_id=payload.action_id or "",
            tool_name=payload.action_name,
            rationale=payload.rationale,
            expected_outcome="Await human confirmation before execution.",
            risk_level=payload.risk_level,
            destructive=payload.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL},
            requires_confirmation=True,
        )
        request = context.confirmation_manager.build_request(
            synthetic_action,
            reason=payload.rationale,
            consequences=payload.consequences,
        )
        return RequestConfirmationOutput(confirmation_request=request)
