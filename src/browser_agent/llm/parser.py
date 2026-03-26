"""Structured parser boundary for planner responses."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError

from browser_agent.llm.planner import PlannerDecision
from browser_agent.runtime.models import PlannerDecisionType, PlannerProgressState, RiskLevel
from browser_agent.skills.registry import SkillRegistry

_VALID_DECISION_TYPES = frozenset(m.value for m in PlannerDecisionType)

_VALID_PROGRESS_STATES = frozenset(m.value for m in PlannerProgressState)

# Models often emit short labels or camelCase instead of the schema snake_case values.
_PROGRESS_ASSESSMENT_SYNONYMS: dict[str, str] = {
    "partial": "partial_progress",
    "partialprogress": "partial_progress",
    "partially": "partial_progress",
    "in_progress": "partial_progress",
    "inprogress": "partial_progress",
    "some": "partial_progress",
    "substantial": "substantial_progress",
    "substantialprogress": "substantial_progress",
    "major": "substantial_progress",
    "significant": "substantial_progress",
    "complete": "substantial_progress",
    "completed": "substantial_progress",
    "done": "substantial_progress",
    "none": "no_progress",
    "none_progress": "no_progress",
    "stalled": "no_progress",
    "blocked": "no_progress",
    "unclear": "unknown",
    "uncertain": "unknown",
    "n/a": "unknown",
    "na": "unknown",
    "unk": "unknown",
}

# Small models often emit synonyms or pasted prompt fragments; map before Pydantic.
_DECISION_TYPE_SYNONYMS: dict[str, str] = {
    "action": "act",
    "execute": "act",
    "tool": "act",
    "ask": "ask_user",
    "question": "ask_user",
    "user_question": "ask_user",
    "confirmation": "request_confirmation",
    "confirm": "request_confirmation",
    "complete": "finish",
    "completed": "finish",
    "done": "finish",
    "success": "finish",
    "error": "fail",
    "abort": "fail",
    "stop": "fail",
}


def _normalize_decision_type(raw: Any) -> Any:
    if raw is None or not isinstance(raw, str):
        return raw
    s = raw.strip().lower()
    if not s:
        return raw
    if s in _VALID_DECISION_TYPES:
        return s
    if "|" in s:
        for part in s.split("|"):
            token = part.strip().lower()
            if token in _VALID_DECISION_TYPES:
                return token
            if token in _DECISION_TYPE_SYNONYMS:
                return _DECISION_TYPE_SYNONYMS[token]
    if s in _DECISION_TYPE_SYNONYMS:
        return _DECISION_TYPE_SYNONYMS[s]
    return raw


def _normalize_enum_field(
    raw: Any,
    *,
    valid: frozenset[str],
    synonyms: dict[str, str] | None = None,
) -> Any:
    if raw is None or not isinstance(raw, str):
        return raw
    s = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if s in valid:
        return s
    if synonyms and s in synonyms:
        return synonyms[s]
    return raw


def _normalize_progress_assessment(raw: Any) -> str:
    """Map model output to a valid PlannerProgressState value; never leave invalid strings."""

    if raw is None:
        return PlannerProgressState.UNKNOWN.value
    if isinstance(raw, bool):
        return (
            PlannerProgressState.PARTIAL_PROGRESS.value
            if raw
            else PlannerProgressState.NO_PROGRESS.value
        )
    if isinstance(raw, (int, float)):
        return PlannerProgressState.UNKNOWN.value
    if not isinstance(raw, str):
        return PlannerProgressState.UNKNOWN.value

    s = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if s in _VALID_PROGRESS_STATES:
        return s
    if s in _PROGRESS_ASSESSMENT_SYNONYMS:
        return _PROGRESS_ASSESSMENT_SYNONYMS[s]
    # Try generic normalization (handles "PARTIAL PROGRESS" etc.)
    t = _normalize_enum_field(
        raw,
        valid=_VALID_PROGRESS_STATES,
        synonyms=_PROGRESS_ASSESSMENT_SYNONYMS,
    )
    if isinstance(t, str) and t in _VALID_PROGRESS_STATES:
        return t
    return PlannerProgressState.UNKNOWN.value


_ACTING_DECISION_TYPES = frozenset(
    {
        PlannerDecisionType.ACT.value,
        PlannerDecisionType.REQUEST_CONFIRMATION.value,
    }
)


def _coerce_finish_task_alias(payload: dict[str, Any]) -> None:
    """Rewrite legacy `act + finish_task` payloads into canonical `finish` decisions."""

    if payload.get("decision_type") not in _ACTING_DECISION_TYPES:
        return

    chosen_skill = payload.get("chosen_skill")
    if not isinstance(chosen_skill, str) or chosen_skill.strip() != "finish_task":
        return

    skill_input = payload.get("skill_input")
    finish_reason: str | None = None
    if isinstance(skill_input, dict):
        raw_summary = skill_input.get("summary")
        if isinstance(raw_summary, str) and raw_summary.strip():
            finish_reason = raw_summary.strip()

    if finish_reason is None:
        raw_finish_reason = payload.get("finish_reason")
        if isinstance(raw_finish_reason, str) and raw_finish_reason.strip():
            finish_reason = raw_finish_reason.strip()

    if finish_reason is None:
        raw_rationale = payload.get("rationale")
        if isinstance(raw_rationale, str) and raw_rationale.strip():
            finish_reason = raw_rationale.strip()

    payload["decision_type"] = PlannerDecisionType.FINISH.value
    payload["chosen_skill"] = None
    payload["skill_input"] = {}
    payload["expected_outcome"] = None
    payload["requires_confirmation"] = False
    payload["destructive"] = False
    payload["user_question"] = None
    payload["failure_reason"] = None
    payload["finish_reason"] = finish_reason or "The task has enough evidence to finish."


def _coerce_expected_outcome_for_acting(payload: dict[str, Any]) -> None:
    """Fill missing `expected_outcome` when the model omits it for acting decisions."""

    if payload.get("decision_type") not in _ACTING_DECISION_TYPES:
        return
    raw = payload.get("expected_outcome")
    if raw is not None and str(raw).strip():
        return
    rationale = payload.get("rationale")
    if isinstance(rationale, str) and rationale.strip():
        payload["expected_outcome"] = rationale.strip()[:500]
        return
    skill = payload.get("chosen_skill")
    if isinstance(skill, str) and skill.strip():
        payload["expected_outcome"] = (
            f"The `{skill.strip()}` step completes and the observable page state updates."
        )
        return
    payload["expected_outcome"] = (
        "The next action executes and the observable page state updates."
    )


def _coerce_planner_payload_dict(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if "decision_type" in out:
        out["decision_type"] = _normalize_decision_type(out["decision_type"])
    if "risk_level" in out:
        out["risk_level"] = _normalize_enum_field(
            out["risk_level"],
            valid=frozenset(m.value for m in RiskLevel),
        )
    if "progress_assessment" in out:
        out["progress_assessment"] = _normalize_progress_assessment(
            out["progress_assessment"]
        )
    _coerce_finish_task_alias(out)
    _coerce_expected_outcome_for_acting(out)
    return out


# Models often nest the contract under one key or use alternate field names.
_NESTED_WRAPPER_KEYS: tuple[str, ...] = (
    "decision",
    "planner_decision",
    "next_step",
    "output",
    "result",
    "response",
    "plan",
    "payload",
    "data",
)


def _unwrap_nested_planner_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Merge nested `{ decision: { ... } }`-style payloads into a flat planner dict."""

    merged = dict(d)
    for key in _NESTED_WRAPPER_KEYS:
        inner = merged.get(key)
        # Only unwrap if the key contains a dict (actual nested wrapper)
        # If it contains a string (e.g., alias for decision_type), keep it
        if isinstance(inner, dict):
            merged.pop(key, None)
            merged = {**inner, **merged}
    return merged


def _apply_field_aliases(d: dict[str, Any]) -> dict[str, Any]:
    """Map common alternate keys before Pydantic validation."""

    out = dict(d)
    # Handle decision_type - check both missing key and None value
    if out.get("decision_type") is None:
        # Extended list of common alternate keys for decision_type
        for alt in ("type", "step_type", "kind", "action_type", "decision", "action"):
            if out.get(alt) is not None:
                out["decision_type"] = out[alt]
                break
    rationale_missing = (
        "rationale" not in out
        or out.get("rationale") is None
        or (isinstance(out.get("rationale"), str) and not str(out["rationale"]).strip())
    )
    if rationale_missing:
        for alt in ("reason", "reasoning", "explanation", "summary", "thought"):
            if out.get(alt) is not None and str(out[alt]).strip():
                out["rationale"] = str(out[alt])
                break
    return out


def _prepare_planner_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Unwrap, alias, then apply enum/decision_type coercion."""

    return _coerce_planner_payload_dict(
        _apply_field_aliases(_unwrap_nested_planner_dict(raw))
    )


class PlannerResponseParser:
    """Validate planner payloads against the runtime decision contract."""

    def __init__(self, *, skill_registry: SkillRegistry) -> None:
        self.skill_registry = skill_registry

    def parse(self, payload: str | Mapping[str, Any]) -> PlannerDecision:
        """Parse a raw payload into a validated `PlannerDecision`."""

        try:
            candidates = self._normalize_payload_candidates(payload)
        except ValueError as exc:
            return PlannerDecision.safe_fail(str(exc))

        last_validation: ValidationError | None = None
        last_candidate: dict[str, Any] | None = None
        for normalized_payload in candidates:
            last_candidate = normalized_payload
            try:
                decision = PlannerDecision.model_validate(normalized_payload)
                return self._validate_skill_contracts(decision)
            except ValidationError as exc:
                last_validation = exc
                continue

        if last_validation is not None:
            # Include the actual payload content for debugging
            preview = str(payload)[:500] if isinstance(payload, str) else str(last_candidate)[:500]
            return PlannerDecision.safe_fail(
                f"Planner response did not match the decision schema: "
                f"{self._format_validation_error(last_validation)}. "
                f"Response preview: {preview}"
            )
        return PlannerDecision.safe_fail(
            "Planner returned no JSON object that matched the decision schema."
        )

    def _normalize_payload_candidates(
        self, payload: str | Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Return one or more prepared dicts to try (nested unwrap + aliases + coercion)."""

        if isinstance(payload, Mapping):
            return [_prepare_planner_dict(dict(payload))]

        if not isinstance(payload, str) or not payload.strip():
            raise ValueError("Planner returned an empty response instead of JSON.")

        raw_dicts = self._extract_json_dict_candidates(payload)
        if not raw_dicts:
            raise ValueError("Planner response did not contain a JSON object.")

        return [_prepare_planner_dict(d) for d in raw_dicts]

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

    def _extract_json_dict_candidates(self, payload: str) -> list[dict[str, Any]]:
        """Parse all top-level JSON objects from the assistant text (handles preambles / multiple blobs)."""

        stripped = payload.strip()
        if stripped.startswith("```"):
            stripped = self._strip_code_fence(stripped)

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return [parsed]
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass

        out: list[dict[str, Any]] = []
        start = 0
        while True:
            pos = stripped.find("{", start)
            if pos < 0:
                break
            try:
                json_text = self._extract_balanced_json_object(stripped, pos)
                parsed = json.loads(json_text)
                if isinstance(parsed, dict):
                    out.append(parsed)
                elif isinstance(parsed, list):
                    out.extend([x for x in parsed if isinstance(x, dict)])
            except (json.JSONDecodeError, ValueError):
                pass
            start = pos + 1
        return out

    def _extract_balanced_json_object(self, stripped: str, start_index: int) -> str:
        """Return the balanced `{...}` substring starting at start_index."""

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
