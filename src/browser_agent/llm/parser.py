"""Structured parser boundary for planner responses."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError

from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.models import PlannerDecisionType
from browser_agent.skills.registry import SkillRegistry


class PlannerResponseParser:
    """Validate planner payloads against the runtime decision contract."""

    def __init__(self, *, skill_registry: SkillRegistry) -> None:
        self.skill_registry = skill_registry

    def parse(self, payload: str | Mapping[str, Any]) -> PlannerDecision:
        """Parse a raw payload into a validated `PlannerDecision`."""

        try:
            normalized_payload = self._normalize_payload(payload)
        except ValueError as exc:
            return PlannerDecision.safe_fail(str(exc))

        try:
            decision = PlannerDecision.model_validate(normalized_payload)
        except ValidationError as exc:
            return PlannerDecision.safe_fail(
                f"Planner response did not match the decision schema: "
                f"{self._format_validation_error(exc)}"
            )

        return self._validate_skill_contracts(decision)

    def _normalize_payload(self, payload: str | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(payload, Mapping):
            return dict(payload)
        if not isinstance(payload, str) or not payload.strip():
            raise ValueError("Planner returned an empty response instead of JSON.")

        json_text = self._extract_json_object(payload)
        try:
            raw_payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError("Planner returned malformed JSON.") from exc

        if not isinstance(raw_payload, dict):
            raise ValueError("Planner JSON payload must be an object.")
        return raw_payload

    def _validate_skill_contracts(self, decision: PlannerDecision) -> PlannerDecision:
        if decision.decision_type in {
            PlannerDecisionType.ASK_USER,
            PlannerDecisionType.FINISH,
            PlannerDecisionType.FAIL,
        }:
            if decision.chosen_skill is not None:
                return PlannerDecision.safe_fail(
                    "Non-acting planner decisions must not include `chosen_skill`."
                )
            if decision.skill_input:
                return PlannerDecision.safe_fail(
                    "Non-acting planner decisions must not include `skill_input`."
                )
            return decision

        if decision.chosen_skill is None:
            return PlannerDecision.safe_fail(
                "Acting planner decisions must include a registered skill name."
            )

        if decision.chosen_skill not in self.skill_registry:
            return PlannerDecision.safe_fail(
                f"Planner selected unregistered skill `{decision.chosen_skill}`."
            )

        if (
            decision.decision_type == PlannerDecisionType.REQUEST_CONFIRMATION
            and decision.chosen_skill == "request_confirmation"
        ):
            return PlannerDecision.safe_fail(
                "`request_confirmation` decisions must reference the risky target "
                "skill, not the confirmation helper skill itself."
            )

        skill = self.skill_registry.get(decision.chosen_skill)
        try:
            skill.validate_input(decision.skill_input)
        except ValidationError as exc:
            return PlannerDecision.safe_fail(
                f"Planner arguments for `{decision.chosen_skill}` did not satisfy "
                f"the skill schema: {self._format_validation_error(exc)}"
            )
        except ValueError as exc:
            return PlannerDecision.safe_fail(
                f"Planner arguments for `{decision.chosen_skill}` are invalid: {exc}"
            )
        return decision

    def _extract_json_object(self, payload: str) -> str:
        stripped = payload.strip()
        if stripped.startswith("```"):
            stripped = self._strip_code_fence(stripped)

        start_index = stripped.find("{")
        if start_index < 0:
            raise ValueError("Planner response did not contain a JSON object.")

        depth = 0
        in_string = False
        escaped = False
        for index in range(start_index, len(stripped)):
            char = stripped[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return stripped[start_index : index + 1]

        raise ValueError("Planner response contained an incomplete JSON object.")

    def _strip_code_fence(self, payload: str) -> str:
        lines = payload.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            return "\n".join(lines[1:-1]).strip()
        return payload

    def _format_validation_error(self, error: ValidationError) -> str:
        details: list[str] = []
        for item in error.errors():
            location = ".".join(str(part) for part in item.get("loc", []))
            message = item.get("msg", "validation error")
            details.append(f"{location}: {message}".strip(": "))
        return "; ".join(details)
