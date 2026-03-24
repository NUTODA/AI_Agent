"""Completion and reporting skills."""

from __future__ import annotations

from pydantic import BaseModel, Field

from browser_agent.runtime.models import RuntimeStatus
from browser_agent.skills.base import BaseSkill, SkillContext


class FinishTaskInput(BaseModel):
    """Input contract for a clean runtime stop."""

    status: RuntimeStatus
    summary: str
    next_steps: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class FinishTaskOutput(BaseModel):
    """Output contract for task completion or early termination."""

    status: RuntimeStatus
    summary: str
    next_steps: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    final_url: str | None = None
    page_title: str | None = None
    action_count: int = 0
    observation_count: int = 0


class FinishTaskSkill(BaseSkill):
    """Produce the payload used by the runtime to assemble the final report."""

    name = "finish_task"
    description = "Finish the task and return a final summary payload."
    input_schema = FinishTaskInput
    output_schema = FinishTaskOutput

    def execute(
        self,
        context: SkillContext,
        payload: FinishTaskInput,
    ) -> FinishTaskOutput:
        latest_observation = context.session.latest_observation
        return FinishTaskOutput(
            status=payload.status,
            summary=payload.summary,
            next_steps=payload.next_steps,
            open_questions=payload.open_questions,
            final_url=latest_observation.page_url if latest_observation else None,
            page_title=latest_observation.page_title if latest_observation else None,
            action_count=len(context.session.actions),
            observation_count=len(context.session.observations),
        )
