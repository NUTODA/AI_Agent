"""Planner contracts and implementations for the browser agent runtime."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from pydantic import BaseModel, Field, ValidationError, model_validator

from browser_agent.llm.provider import LLMProvider, LLMProviderError, LLMRequest
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    AgentThought,
    ConfirmationRequest,
    HumanInterventionRequest,
    PendingUserQuestion,
    PlannerDecisionType,
    PlannerProgressState,
    RiskLevel,
    RuntimeStatus,
    ToolExecutionStatus,
    UserResponse,
    UserTask,
)
from browser_agent.skills.registry import SkillRegistry


class AvailableSkill(BaseModel):
    """Compact skill contract exposed to the planner."""

    name: str
    description: str
    input_contract: list[str] = Field(default_factory=list)


class PlannerSessionState(BaseModel):
    """Planner-facing snapshot of runtime state."""

    session_id: str
    status: RuntimeStatus
    step_count: int
    max_steps: int
    no_progress_streak: int = 0
    latest_url: str | None = None
    latest_page_title: str | None = None
    latest_action_name: str | None = None
    latest_tool_status: ToolExecutionStatus | None = None
    latest_tool_message: str | None = None
    latest_extracted_text: str | None = None
    latest_extracted_text_truncated: bool | None = None
    latest_extracted_text_url: str | None = None
    pending_confirmation: ConfirmationRequest | None = None
    pending_user_question: PendingUserQuestion | None = None
    pending_human_intervention: HumanInterventionRequest | None = None
    user_responses: list[UserResponse] = Field(default_factory=list)


class PlannerContext(BaseModel):
    """Typed input provided to the planner for the next decision."""

    task: UserTask
    current_observation: AgentObservation | None = None
    trace_summary: list[str] = Field(default_factory=list)
    available_skills: list[AvailableSkill] = Field(default_factory=list)
    session_state: PlannerSessionState


class PlannerDecision(BaseModel):
    """Strict structured decision emitted by the planner."""

    decision_type: PlannerDecisionType
    rationale: str
    chosen_skill: str | None = None
    skill_input: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    destructive: bool = False
    completion_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    progress_assessment: PlannerProgressState = PlannerProgressState.UNKNOWN
    requires_confirmation: bool = False
    user_question: str | None = None
    finish_reason: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "PlannerDecision":
        if self.decision_type in {
            PlannerDecisionType.ACT,
            PlannerDecisionType.REQUEST_CONFIRMATION,
        }:
            if not self.chosen_skill:
                raise ValueError("Acting decisions must include `chosen_skill`.")
            if self.chosen_skill == "finish_task":
                raise ValueError(
                    "`finish_task` must be represented with `decision_type=finish`."
                )
            if not self.expected_outcome:
                raise ValueError(
                    "Acting decisions must include `expected_outcome`."
                )

        if self.decision_type == PlannerDecisionType.ASK_USER and not self.user_question:
            raise ValueError("`ask_user` decisions must include `user_question`.")

        if self.decision_type == PlannerDecisionType.FINISH and not self.finish_reason:
            raise ValueError("`finish` decisions must include `finish_reason`.")

        if self.decision_type == PlannerDecisionType.FAIL and not self.failure_reason:
            raise ValueError("`fail` decisions must include `failure_reason`.")

        return self

    @classmethod
    def safe_fail(
        cls,
        reason: str,
        *,
        rationale: str | None = None,
    ) -> "PlannerDecision":
        """Return a controlled failure decision instead of crashing the loop."""

        return cls(
            decision_type=PlannerDecisionType.FAIL,
            rationale=(
                rationale
                or "The planner could not produce a valid structured next step."
            ),
            failure_reason=reason,
            progress_assessment=PlannerProgressState.NO_PROGRESS,
        )

    def to_agent_thought(self) -> AgentThought:
        """Convert the decision into the runtime thought model."""

        summary_by_type = {
            PlannerDecisionType.ACT: (
                f"Execute `{self.chosen_skill}` as the next atomic step."
            ),
            PlannerDecisionType.ASK_USER: "Ask the user for missing information.",
            PlannerDecisionType.REQUEST_CONFIRMATION: (
                f"Pause for confirmation before `{self.chosen_skill}`."
            ),
            PlannerDecisionType.FINISH: "Finish the task with observed evidence.",
            PlannerDecisionType.FAIL: "Stop because the task cannot continue safely.",
        }
        missing_information = [self.user_question] if self.user_question else []
        return AgentThought(
            summary=summary_by_type[self.decision_type],
            rationale=self.rationale,
            missing_information=missing_information,
            confidence=self.completion_confidence,
            needs_user_input=self.decision_type
            in {
                PlannerDecisionType.ASK_USER,
                PlannerDecisionType.REQUEST_CONFIRMATION,
            },
            can_finish=self.decision_type
            in {
                PlannerDecisionType.FINISH,
                PlannerDecisionType.FAIL,
            },
        )

    def to_agent_action(self) -> AgentAction:
        """Convert an acting planner decision into a runtime action."""

        if self.decision_type not in {
            PlannerDecisionType.ACT,
            PlannerDecisionType.REQUEST_CONFIRMATION,
        }:
            raise ValueError("Only acting decisions can be converted to AgentAction.")
        if self.chosen_skill is None or self.expected_outcome is None:
            raise ValueError("Acting decisions require a skill and expected outcome.")
        return AgentAction(
            tool_name=self.chosen_skill,
            rationale=self.rationale,
            parameters=self.skill_input,
            expected_outcome=self.expected_outcome,
            risk_level=self.risk_level,
            destructive=self.destructive,
            requires_confirmation=(
                self.requires_confirmation
                or self.decision_type == PlannerDecisionType.REQUEST_CONFIRMATION
            ),
        )

    def to_finish_action(self) -> AgentAction:
        """Convert an explicit finish decision into the finish skill action."""

        if self.decision_type != PlannerDecisionType.FINISH:
            raise ValueError("Only finish decisions can be converted to finish actions.")
        return AgentAction(
            tool_name="finish_task",
            rationale=self.rationale,
            parameters={
                "status": RuntimeStatus.COMPLETED.value,
                "summary": self.finish_reason,
            },
            expected_outcome="Produce the final task report from observed evidence.",
            risk_level=RiskLevel.LOW,
        )


class PlannerResponseParserProtocol(Protocol):
    """Structured parser contract used by the LLM planner."""

    def parse(self, payload: str | Mapping[str, Any]) -> PlannerDecision:
        """Validate the raw provider payload into a planner decision."""


class Planner(Protocol):
    """Planner interface consumed by the runtime loop."""

    def decide(self, planner_context: PlannerContext) -> PlannerDecision:
        """Choose the next action based on the current runtime context."""


class LLMPlanner:
    """Structured LLM-backed planner that returns typed decisions only."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        parser: PlannerResponseParserProtocol,
        response_format: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.parser = parser
        self.response_format = response_format or {"type": "json_object"}

    def decide(self, planner_context: PlannerContext) -> PlannerDecision:
        from browser_agent.llm.prompts import build_planner_messages

        try:
            llm_response = self.provider.complete(
                LLMRequest(
                    messages=build_planner_messages(planner_context),
                    response_format=self.response_format,
                )
            )
        except LLMProviderError as exc:
            return PlannerDecision.safe_fail(
                f"Planner provider error: {exc}",
                rationale=(
                    "The runtime could not obtain a structured planner response from "
                    "the configured LLM provider."
                ),
            )
        except Exception as exc:
            return PlannerDecision.safe_fail(
                f"Planner request failed unexpectedly: {exc}",
            )

        return self.parser.parse(llm_response.content)


class FoundationPlanner:
    """Legacy planner kept only for compatibility with early-stage tests."""

    def decide(self, planner_context: PlannerContext) -> PlannerDecision:
        task_start_url = planner_context.task.start_url
        observation = planner_context.current_observation

        if observation is None:
            return PlannerDecision(
                decision_type=PlannerDecisionType.ACT,
                rationale=(
                    "The foundation fallback still starts from a real browser "
                    "observation instead of hidden assumptions."
                ),
                chosen_skill="observe_page",
                skill_input={},
                expected_outcome="Capture the current page as a structured observation.",
                progress_assessment=PlannerProgressState.UNKNOWN,
            )

        if task_start_url and observation.page_url == "about:blank":
            return PlannerDecision(
                decision_type=PlannerDecisionType.ACT,
                rationale=(
                    "A provided start URL is an explicit operator input, so the "
                    "foundation fallback can begin with one typed navigation step."
                ),
                chosen_skill="navigate",
                skill_input={"url": task_start_url, "wait_for": "load"},
                expected_outcome="Load the requested page before the next observation.",
                progress_assessment=PlannerProgressState.PARTIAL_PROGRESS,
            )

        return PlannerDecision(
            decision_type=PlannerDecisionType.FINISH,
            rationale=(
                "The fallback planner should stop honestly once the initial browser "
                "state is available, instead of pretending autonomous depth."
            ),
            finish_reason=(
                "The legacy fallback planner captured a real browser state but does "
                "not implement true multi-step autonomy."
            ),
            completion_confidence=0.2,
            progress_assessment=PlannerProgressState.PARTIAL_PROGRESS,
        )


def describe_skill_registry(skill_registry: SkillRegistry) -> list[AvailableSkill]:
    """Build a compact prompt-facing description of the registered skills."""

    descriptors: list[AvailableSkill] = []
    for skill_name in skill_registry.list_names():
        skill = skill_registry.get(skill_name)
        schema = skill.input_schema.model_json_schema()
        required = set(schema.get("required", []))
        input_contract: list[str] = []
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field_name, raw_definition in properties.items():
                if not isinstance(raw_definition, dict):
                    continue
                input_contract.append(
                    _format_input_contract_line(
                        field_name=field_name,
                        definition=raw_definition,
                        required=field_name in required,
                    )
                )
        if not input_contract:
            input_contract.append("No input arguments.")
        descriptors.append(
            AvailableSkill(
                name=skill.name,
                description=skill.description,
                input_contract=input_contract,
            )
        )
    return descriptors


def _format_input_contract_line(
    *,
    field_name: str,
    definition: dict[str, Any],
    required: bool,
) -> str:
    type_label = _schema_type(definition)
    required_label = "required" if required else "optional"
    description = definition.get("description")
    if isinstance(description, str) and description:
        return f"{field_name}: {type_label} ({required_label}) - {description}"
    return f"{field_name}: {type_label} ({required_label})"


def _schema_type(definition: dict[str, Any]) -> str:
    if "enum" in definition and isinstance(definition["enum"], list):
        values = ", ".join(str(value) for value in definition["enum"])
        return f"enum[{values}]"

    any_of = definition.get("anyOf")
    if isinstance(any_of, list) and any_of:
        parts = []
        for option in any_of:
            if isinstance(option, dict):
                parts.append(_schema_type(option))
        if parts:
            return " | ".join(dict.fromkeys(parts))

    field_type = definition.get("type")
    if isinstance(field_type, list):
        return " | ".join(str(item) for item in field_type)
    if field_type == "array":
        item_type = "any"
        items = definition.get("items")
        if isinstance(items, dict):
            item_type = _schema_type(items)
        return f"array[{item_type}]"
    if isinstance(field_type, str):
        return field_type
    if "$ref" in definition:
        return str(definition["$ref"]).split("/")[-1]
    return "object"
