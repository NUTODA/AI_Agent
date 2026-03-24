"""Confirmation request helpers for sensitive runtime actions."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from browser_agent.runtime.models import AgentAction, ConfirmationRequest, RiskLevel


class ConfirmationDecision(BaseModel):
    """Represents the operator response to a confirmation request."""

    request_id: str
    approved: bool
    reviewer_notes: str | None = None


@dataclass(slots=True)
class ConfirmationManager:
    """Builds human-readable confirmation requests.

    The current foundation does not persist decisions yet. Its job is to create
    explicit approval objects that can be surfaced by the runtime and CLI.
    """

    default_consequence_hints: dict[RiskLevel, list[str]] = field(
        default_factory=lambda: {
            RiskLevel.MEDIUM: ["This action may change the current page state."],
            RiskLevel.HIGH: ["This action may modify or submit user data."],
            RiskLevel.CRITICAL: [
                "This action may be destructive or financially significant.",
            ],
        },
    )

    def build_request(
        self,
        action: AgentAction,
        *,
        reason: str,
        consequences: list[str] | None = None,
    ) -> ConfirmationRequest:
        """Build a confirmation request for the given action."""

        default_consequences = self.default_consequence_hints.get(
            action.risk_level,
            [],
        )
        merged_consequences = consequences or default_consequences
        prompt = (
            f"Approve action `{action.tool_name}`? "
            f"Risk level: `{action.risk_level.value}`. "
            f"Reason: {reason}"
        )
        return ConfirmationRequest(
            action_id=action.action_id,
            action_name=action.tool_name,
            reason=reason,
            risk_level=action.risk_level,
            consequences=merged_consequences,
            prompt=prompt,
        )
