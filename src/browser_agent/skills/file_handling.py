"""File handling runtime skills."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, model_validator

from browser_agent.runtime.models import AgentObservation
from browser_agent.skills.base import (
    BaseSkill,
    SkillContext,
    SkillExecutionError,
    raise_for_browser_result,
)


def _resolve_target(selector: str | None, element_id: str | None) -> str:
    target = element_id or selector
    if target is None:
        raise ValueError("One of `selector` or `element_id` must be provided.")
    return target


class UploadFileInput(BaseModel):
    """Input contract for uploading a file."""

    selector: str | None = None
    element_id: str | None = None
    file_path: str

    @model_validator(mode="after")
    def validate_target(self) -> "UploadFileInput":
        _resolve_target(self.selector, self.element_id)
        return self


class UploadFileOutput(BaseModel):
    """Output contract for file upload execution."""

    target: str
    file_name: str
    file_path: str
    message: str
    page_title: str | None = None
    observation: AgentObservation | None = None


class UploadFileSkill(BaseSkill):
    """Upload a file to a file input element."""

    name = "upload_file"
    description = "Upload a file to a file input field on the page."
    input_schema = UploadFileInput
    output_schema = UploadFileOutput

    def execute(
        self,
        context: SkillContext,
        payload: UploadFileInput,
    ) -> UploadFileOutput:
        target = _resolve_target(payload.selector, payload.element_id)
        file_path = Path(payload.file_path)

        if not file_path.exists():
            raise SkillExecutionError(
                message=f"File not found: {payload.file_path}",
                error_code="file_not_found",
                data={"file_path": payload.file_path},
            )

        try:
            result = raise_for_browser_result(
                context.browser.upload_file(
                    target=target,
                    file_path=str(file_path.resolve()),
                ),
                default_error_code="upload_failed",
            )
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                message="Failed to upload the file.",
                error_code="upload_failed",
                data={
                    "target": target,
                    "file_path": payload.file_path,
                    "details": str(exc),
                },
            ) from exc

        observation = (
            result.page_state.to_agent_observation()
            if result.page_state is not None
            else None
        )

        return UploadFileOutput(
            target=target,
            file_name=file_path.name,
            file_path=payload.file_path,
            message=result.message,
            page_title=result.page_state.title if result.page_state else None,
            observation=observation,
        )
