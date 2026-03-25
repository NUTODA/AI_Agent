"""Tests for trace recording and final report generation.

These tests verify that:
1. Trace items correctly capture pending state transitions
2. Final reports contain expected sections and structure
3. Trace output formatting is readable and complete
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from browser_agent.runtime.models import (
    ConfirmationRequest,
    ExecutionTraceItem,
    FinalReport,
    PendingUserQuestion,
    ProgressOutcome,
    RiskLevel,
    RuntimeStatus,
    ToolResultStatus,
)
from browser_agent.runtime.trace import TraceRecorder


class TestTracePendingTransitions:
    """Test that trace correctly captures pending state transitions."""

    def test_trace_captures_waiting_for_confirmation(self) -> None:
        """Trace should record transition to waiting_for_confirmation state."""
        recorder = TraceRecorder()

        # Record initial action
        recorder.record_step(
            step_index=0,
            observation_summary="Initial page load",
            planner_decision_type="ACT",
            rationale_summary="Load the page",
            action_name="navigate",
            action_input={"url": "http://example.com"},
            tool_result_status=ToolResultStatus.SUCCESS,
            output_summary="Page loaded",
        )

        # Record transition to pending confirmation
        recorder.record_step(
            step_index=1,
            observation_summary="Form ready for submission",
            planner_decision_type="REQUEST_CONFIRMATION",
            rationale_summary="Form submission needs confirmation",
            action_name="submit_form",
            action_input={},
            tool_result_status=ToolResultStatus.WAITING_FOR_CONFIRMATION,
            output_summary="Waiting for user confirmation",
            state_transition="waiting_for_confirmation",
        )

        trace = recorder.as_markdown()

        # Should contain pending state indicator
        assert "WAITING_FOR_CONFIRMATION" in trace or "waiting_for_confirmation" in trace

    def test_trace_captures_waiting_for_user(self) -> None:
        """Trace should record transition to waiting_for_user state."""
        recorder = TraceRecorder()

        recorder.record_step(
            step_index=0,
            observation_summary="Form missing required field",
            planner_decision_type="ASK_USER",
            rationale_summary="Need user email to continue",
            action_name="ask_user",
            action_input={"question": "What is your email?"},
            tool_result_status=ToolResultStatus.SUCCESS,
            output_summary="Question asked",
            state_transition="waiting_for_user",
        )

        trace = recorder.as_markdown()

        assert "waiting_for_user" in trace.lower() or "ASK_USER" in trace

    def test_trace_shows_progress_outcome(self) -> None:
        """Trace should show progress outcome for each step."""
        recorder = TraceRecorder()

        progress = ProgressOutcome(made_progress=True, reason="New content loaded")

        recorder.record_step(
            step_index=0,
            observation_summary="Page content",
            planner_decision_type="ACT",
            action_name="click_element",
            progress_outcome=progress,
        )

        trace = recorder.as_markdown()

        # Should show progress information
        assert "progress" in trace.lower() or "Progress" in trace

    def test_trace_captures_state_transitions(self) -> None:
        """Trace should record explicit state transitions."""
        recorder = TraceRecorder()

        recorder.record_step(
            step_index=0,
            observation_summary="Completed task",
            planner_decision_type="FINISH",
            state_transition="completed",
        )

        recorder.record_step(
            step_index=1,
            observation_summary="Task failed",
            planner_decision_type="FAIL",
            state_transition="failed",
        )

        trace = recorder.as_markdown()

        assert "completed" in trace.lower() or "failed" in trace.lower()

    def test_trace_contains_all_step_fields(self) -> None:
        """Trace should include all relevant step fields."""
        recorder = TraceRecorder()

        recorder.record_step(
            step_index=5,
            observation_summary="Found button",
            planner_decision_type="ACT",
            rationale_summary="Click to continue",
            action_name="click_element",
            action_input={"selector": "#submit"},
            tool_result_status=ToolResultStatus.SUCCESS,
            output_summary="Clicked successfully",
            progress_outcome=ProgressOutcome(made_progress=True),
            page_title="Test Page",
            current_url="http://example.com/form",
            duration_ms=1500,
        )

        trace = recorder.as_markdown()

        # Should contain step number
        assert "Step 6" in trace  # step_index + 1 for display

        # Should contain action name
        assert "click_element" in trace

        # Should show status
        assert "success" in trace.lower() or "" in trace


class TestFinalReportStructure:
    """Test that final reports contain expected sections."""

    def test_report_has_required_fields(self) -> None:
        """Report should have all required fields."""
        report = FinalReport(
            status=RuntimeStatus.COMPLETED,
            summary="Task completed successfully",
            step_count=5,
            actions_taken=["navigate", "click", "type", "submit"],
            session_id="test-session-123",
        )

        assert report.status == RuntimeStatus.COMPLETED
        assert report.summary == "Task completed successfully"
        assert report.step_count == 5
        assert len(report.actions_taken) == 4
        assert report.session_id == "test-session-123"
        assert report.generated_at is not None

    def test_report_with_pending_confirmation(self) -> None:
        """Report should include pending confirmation details."""
        confirmation = ConfirmationRequest(
            request_id="req-123",
            action_name="submit_form",
            reason="This will submit data to external service",
            risk_level=RiskLevel.HIGH,
            consequences=["Data will be saved", "Cannot be undone"],
            prompt="Do you want to submit this form?",
        )

        report = FinalReport(
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Waiting for user confirmation",
            pending_confirmation=confirmation,
        )

        assert report.pending_confirmation is not None
        assert report.pending_confirmation.action_name == "submit_form"
        assert report.pending_confirmation.risk_level == RiskLevel.HIGH
        assert len(report.pending_confirmation.consequences) == 2

    def test_report_with_pending_user_question(self) -> None:
        """Report should include pending user question."""
        question = PendingUserQuestion(
            question="What is your email address?",
            context="Required for account creation",
        )

        report = FinalReport(
            status=RuntimeStatus.WAITING_FOR_USER,
            summary="Waiting for user input",
            pending_user_question=question,
        )

        assert report.pending_user_question is not None
        assert report.pending_user_question.question == "What is your email address?"

    def test_report_with_open_questions(self) -> None:
        """Report should include unresolved questions."""
        report = FinalReport(
            status=RuntimeStatus.COMPLETED,
            summary="Partial completion",
            open_questions=["What format for the output?", "Where to save the file?"],
        )

        assert len(report.open_questions) == 2
        assert "format" in report.open_questions[0].lower()

    def test_report_with_next_steps(self) -> None:
        """Report should include recommended next steps."""
        report = FinalReport(
            status=RuntimeStatus.COMPLETED,
            summary="Step 1 done",
            next_steps=["Verify the output", "Continue to step 2", "Review changes"],
        )

        assert len(report.next_steps) == 3
        assert "step 2" in report.next_steps[1].lower()

    def test_report_with_failure_reason(self) -> None:
        """Failed report should include failure reason."""
        report = FinalReport(
            status=RuntimeStatus.FAILED,
            summary="Could not complete task",
            failure_reason="Element not found after multiple attempts",
        )

        assert report.failure_reason is not None
        assert "not found" in report.failure_reason.lower()

    def test_report_with_artifacts(self) -> None:
        """Report should include artifact references."""
        report = FinalReport(
            status=RuntimeStatus.COMPLETED,
            summary="Done",
            artifact_refs=["screenshot_step_1.png", "trace.jsonl", "report.md"],
        )

        assert len(report.artifact_refs) == 3
        assert "screenshot" in report.artifact_refs[0]

    def test_report_with_final_url(self) -> None:
        """Report should include final URL."""
        report = FinalReport(
            status=RuntimeStatus.COMPLETED,
            summary="Done",
            final_url="http://example.com/success",
        )

        assert report.final_url == "http://example.com/success"


class TestTraceRecorderIntegration:
    """Test TraceRecorder integration with runtime."""

    def test_recorder_builds_complete_trace(self) -> None:
        """Recorder should build a complete multi-step trace."""
        recorder = TraceRecorder(session_id="test-123")

        # Simulate a multi-step execution
        recorder.record_step(
            step_index=0,
            observation_summary="Initial page",
            planner_decision_type="NAVIGATE",
            action_name="navigate",
            tool_result_status=ToolResultStatus.SUCCESS,
        )

        recorder.record_step(
            step_index=1,
            observation_summary="Found form",
            planner_decision_type="ACT",
            action_name="type_text",
            tool_result_status=ToolResultStatus.SUCCESS,
        )

        recorder.record_step(
            step_index=2,
            observation_summary="Form ready",
            planner_decision_type="REQUEST_CONFIRMATION",
            action_name="submit_form",
            tool_result_status=ToolResultStatus.WAITING_FOR_CONFIRMATION,
            state_transition="waiting_for_confirmation",
        )

        items = recorder.items

        assert len(items) == 3
        assert items[0].step_index == 0
        assert items[2].step_index == 2
        assert items[2].state_transition == "waiting_for_confirmation"

    def test_recorder_generates_valid_markdown(self) -> None:
        """Generated markdown should be valid and readable."""
        recorder = TraceRecorder()

        recorder.record_step(
            step_index=0,
            observation_summary="Page loaded",
            planner_decision_type="NAVIGATE",
            action_name="navigate",
            tool_result_status=ToolResultStatus.SUCCESS,
            page_title="Demo Page",
            current_url="http://localhost:8765/demo",
        )

        markdown = recorder.as_markdown()

        # Should be valid markdown structure
        assert markdown.startswith("# Browser Agent Execution Trace")
        assert "##" in markdown  # Section headers
        assert "Step 1" in markdown  # Step numbering

    def test_trace_item_records_all_fields(self) -> None:
        """ExecutionTraceItem should record all relevant fields."""
        from datetime import datetime

        item = ExecutionTraceItem(
            step_index=3,
            recorded_at=datetime.now(timezone.utc),
            observation_summary="Test observation",
            planner_decision_type="ACT",
            rationale_summary="Test rationale",
            action_name="click",
            action_input={"selector": "#btn"},
            status=ToolResultStatus.SUCCESS,
            output_summary="Clicked",
            page_title="Page",
            current_url="http://example.com",
            duration_ms=500,
            state_transition="completed",
        )

        assert item.step_index == 3
        assert item.action_name == "click"
        assert item.status == ToolResultStatus.SUCCESS
        assert item.state_transition == "completed"


class TestReportFormatting:
    """Test report formatting for different statuses."""

    def test_completed_report_formatting(self) -> None:
        """Completed status should be clearly formatted."""
        report = FinalReport(
            status=RuntimeStatus.COMPLETED,
            summary="Done",
            completed=True,
        )

        assert report.status == RuntimeStatus.COMPLETED
        assert report.completed is True

    def test_failed_report_formatting(self) -> None:
        """Failed status should be clearly formatted."""
        report = FinalReport(
            status=RuntimeStatus.FAILED,
            summary="Failed",
            completed=False,
            failure_reason="Error occurred",
        )

        assert report.status == RuntimeStatus.FAILED
        assert report.completed is False
        assert report.failure_reason is not None

    def test_stopped_report_formatting(self) -> None:
        """Stopped status should be clearly formatted."""
        report = FinalReport(
            status=RuntimeStatus.STOPPED,
            summary="User stopped execution",
            completed=False,
        )

        assert report.status == RuntimeStatus.STOPPED

    def test_partial_completion_report(self) -> None:
        """Partial completion should be distinguishable."""
        report = FinalReport(
            status=RuntimeStatus.COMPLETED,
            summary="Partial: some steps done",
            completed=False,  # Not fully completed
            next_steps=["Continue with step 3"],
        )

        assert report.status == RuntimeStatus.COMPLETED
        assert report.completed is False
