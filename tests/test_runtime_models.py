"""Contract tests for core runtime models."""

from __future__ import annotations

from browser_agent.runtime.models import (
    AgentAction,
    ConfirmationRequest,
    FinalReport,
    RiskLevel,
    RuntimeStatus,
    ToolExecutionStatus,
    ToolResult,
    UserTask,
)


def test_user_task_and_action_contracts() -> None:
    task = UserTask(
        request="Search for backend jobs",
        start_url="https://example.com/jobs",
        constraints=["Ask before submitting an application."],
    )
    action = AgentAction(
        tool_name="click_element",
        rationale="Open the selected job card.",
        parameters={"selector": "[data-job-id='1']"},
        expected_outcome="The job details page becomes visible.",
        risk_level=RiskLevel.MEDIUM,
    )

    assert task.request == "Search for backend jobs"
    assert action.tool_name == "click_element"
    assert action.risk_level == RiskLevel.MEDIUM


def test_confirmation_request_and_report_contracts() -> None:
    confirmation = ConfirmationRequest(
        action_name="click_element",
        reason="The button appears to submit an application.",
        risk_level=RiskLevel.HIGH,
        prompt="Approve the submission click?",
    )
    report = FinalReport(
        session_id="session_test",
        status=RuntimeStatus.WAITING_FOR_USER,
        summary="Waiting for confirmation before a sensitive action.",
        open_questions=[confirmation.prompt],
    )

    assert confirmation.risk_level == RiskLevel.HIGH
    assert report.status == RuntimeStatus.WAITING_FOR_USER
    assert report.open_questions == ["Approve the submission click?"]


def test_tool_result_contract_supports_structured_payloads() -> None:
    result = ToolResult(
        call_id="call_test",
        skill_name="observe_page",
        status=ToolExecutionStatus.SUCCESS,
        message="Observation completed.",
        data={"page_url": "https://example.com"},
        artifacts=["traces/session_test.jsonl"],
        duration_ms=42,
    )

    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.data["page_url"] == "https://example.com"
    assert result.artifacts == ["traces/session_test.jsonl"]
    assert result.duration_ms == 42
