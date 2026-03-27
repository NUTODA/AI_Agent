"""Safety policies for classifying and gating risky runtime actions."""

from __future__ import annotations

import re
from typing import Iterable

from pydantic import BaseModel, Field

from browser_agent.runtime.models import AgentAction, RiskLevel


DESTRUCTIVE_KEYWORDS = frozenset(
    {
        "delete",
        "remove",
        "archive",
        "send",
        "submit",
        "purchase",
        "buy",
        "pay",
        "confirm",
        "apply",
    }
)


class GuardrailDecision(BaseModel):
    """Safety classification output for a planned action."""

    allowed: bool = True
    requires_confirmation: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    reason: str = "Action is allowed."
    matched_signals: list[str] = Field(default_factory=list)


class SafetyGuardrails:
    """Classify actions before they reach the browser layer."""

    def __init__(
        self,
        *,
        destructive_keywords: Iterable[str] | None = None,
    ) -> None:
        self._destructive_keywords = frozenset(
            destructive_keywords or DESTRUCTIVE_KEYWORDS
        )

    def classify_action(self, action: AgentAction) -> GuardrailDecision:
        """Classify the action and decide whether confirmation is required."""

        matched_signals: list[str] = []
        requires_confirmation = action.requires_confirmation
        risk_level = action.risk_level

        action_text = self._action_text_for_keyword_scan(action)

        if action.destructive:
            matched_signals.append("action marked as destructive")
            requires_confirmation = True
            if risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM}:
                risk_level = RiskLevel.HIGH

        if self._contains_destructive_keyword(action_text):
            matched_signals.append("destructive keyword matched")
            requires_confirmation = True
            if risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM}:
                risk_level = RiskLevel.HIGH

        if action.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            matched_signals.append("high-risk level declared")
            requires_confirmation = True

        reason = (
            "Action requires explicit confirmation before execution."
            if requires_confirmation
            else "Action is allowed without confirmation."
        )
        return GuardrailDecision(
            requires_confirmation=requires_confirmation,
            risk_level=risk_level,
            reason=reason,
            matched_signals=matched_signals,
        )

    def _action_text_for_keyword_scan(self, action: AgentAction) -> str:
        """Return the subset of action text that should influence destructive matching."""

        parts = [action.tool_name, action.expected_outcome]

        # Free-form typing often contains words like "submit" or "apply" that are
        # harmless inside a search box. Do not gate those solely by keyword.
        if action.tool_name != "type_text":
            parts.append(action.rationale)
            parts.extend(
                f"{key}={value}"
                for key, value in action.parameters.items()
                if key != "text"
            )

        return " ".join(parts).lower()

    def _contains_destructive_keyword(self, text: str) -> bool:
        for keyword in self._destructive_keywords:
            pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, text):
                return True
        return False

    def requires_confirmation(self, action: AgentAction) -> bool:
        """Convenience helper used by the runtime loop."""

        return self.classify_action(action).requires_confirmation
