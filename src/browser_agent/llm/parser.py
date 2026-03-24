"""Structured parser boundary for planner responses."""

from __future__ import annotations

from typing import Any, Mapping

from browser_agent.llm.planner import PlannerDecision


class PlannerResponseParser:
    """Validate planner payloads against the runtime decision contract."""

    def parse(self, payload: Mapping[str, Any]) -> PlannerDecision:
        """Parse a raw mapping into a validated `PlannerDecision`."""

        return PlannerDecision.model_validate(payload)
