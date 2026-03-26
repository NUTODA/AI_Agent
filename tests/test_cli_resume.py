"""Tests for CLI resume flow functionality.

These tests verify that the CLI correctly handles pending states
(waiting_for_confirmation and waiting_for_user) and can resume
execution after user interaction.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from browser_agent.cli.runner import (
    is_terminal_status,
    prompt_for_confirmation,
    prompt_for_user_answer,
    run_cli_interactive,
)
from browser_agent.runtime.models import (
    ConfirmationRequest,
    FinalReport,
    PendingUserQuestion,
    RiskLevel,
    RuntimeStatus,
)

_SID = "test_session_cli_resume"
from browser_agent.safety.confirmations import ConfirmationDecision


class TestIsTerminalStatus:
    """Test the is_terminal_status helper function."""

    def test_completed_is_terminal(self) -> None:
        """COMPLETED should be recognized as terminal."""
        assert is_terminal_status(RuntimeStatus.COMPLETED) is True

    def test_stopped_is_terminal(self) -> None:
        """STOPPED should be recognized as terminal."""
        assert is_terminal_status(RuntimeStatus.STOPPED) is True

    def test_failed_is_terminal(self) -> None:
        """FAILED should be recognized as terminal."""
        assert is_terminal_status(RuntimeStatus.FAILED) is True

    def test_waiting_for_confirmation_is_not_terminal(self) -> None:
        """WAITING_FOR_CONFIRMATION should not be terminal."""
        assert is_terminal_status(RuntimeStatus.WAITING_FOR_CONFIRMATION) is False

    def test_waiting_for_user_is_not_terminal(self) -> None:
        """WAITING_FOR_USER should not be terminal."""
        assert is_terminal_status(RuntimeStatus.WAITING_FOR_USER) is False

    def test_running_is_not_terminal(self) -> None:
        """RUNNING should not be terminal."""
        assert is_terminal_status(RuntimeStatus.RUNNING) is False


class TestPromptForConfirmation:
    """Test the confirmation prompt function."""

    def test_returns_none_when_no_pending_confirmation(self) -> None:
        """Should return None if report has no pending confirmation."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.COMPLETED,
            summary="Test",
        )
        assert prompt_for_confirmation(report) is None

    def test_returns_decision_with_approved_true_for_yes(self, monkeypatch) -> None:
        """Should return approved decision when user inputs yes."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Test",
            pending_confirmation=ConfirmationRequest(
                request_id="req-123",
                action_name="submit_form",
                reason="This will submit data",
                risk_level=RiskLevel.MEDIUM,
                prompt="Approve this action?",
            ),
        )

        # Simulate user typing "yes"
        monkeypatch.setattr("builtins.input", lambda _: "yes")

        decision = prompt_for_confirmation(report)

        assert decision is not None
        assert decision.approved is True
        assert decision.request_id == "req-123"

    def test_returns_decision_with_approved_false_for_no(self, monkeypatch) -> None:
        """Should return rejected decision when user inputs no."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Test",
            pending_confirmation=ConfirmationRequest(
                request_id="req-456",
                action_name="delete_data",
                reason="This will delete data",
                risk_level=RiskLevel.HIGH,
                prompt="Approve this action?",
            ),
        )

        # Simulate user typing "no" and providing notes
        inputs = iter(["no", "too risky"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        decision = prompt_for_confirmation(report)

        assert decision is not None
        assert decision.approved is False
        assert decision.request_id == "req-456"
        assert decision.reviewer_notes == "too risky"

    def test_accepts_y_as_shorthand_for_yes(self, monkeypatch) -> None:
        """Should accept 'y' as shorthand for 'yes'."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Test",
            pending_confirmation=ConfirmationRequest(
                request_id="req-789",
                action_name="click_button",
                reason="Safe action",
                risk_level=RiskLevel.LOW,
                prompt="Approve?",
            ),
        )

        monkeypatch.setattr("builtins.input", lambda _: "y")

        decision = prompt_for_confirmation(report)

        assert decision is not None
        assert decision.approved is True

    def test_accepts_n_as_shorthand_for_no(self, monkeypatch) -> None:
        """Should accept 'n' as shorthand for 'no'."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Test",
            pending_confirmation=ConfirmationRequest(
                request_id="req-abc",
                action_name="submit",
                reason="Form submission",
                risk_level=RiskLevel.LOW,
                prompt="Approve?",
            ),
        )

        inputs = iter(["n", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        decision = prompt_for_confirmation(report)

        assert decision is not None
        assert decision.approved is False

    def test_rejects_invalid_input_and_reprompts(self, monkeypatch) -> None:
        """Should reject invalid input and prompt again."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Test",
            pending_confirmation=ConfirmationRequest(
                request_id="req-def",
                action_name="action",
                reason="Test",
                risk_level=RiskLevel.LOW,
                prompt="Approve?",
            ),
        )

        # First invalid, then valid
        inputs = iter(["invalid", "maybe", "yes"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        decision = prompt_for_confirmation(report)

        assert decision is not None
        assert decision.approved is True


class TestPromptForUserAnswer:
    """Test the user question prompt function."""

    def test_returns_none_when_no_pending_question(self) -> None:
        """Should return None if report has no pending question."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.COMPLETED,
            summary="Test",
        )
        assert prompt_for_user_answer(report) is None

    def test_returns_user_input(self, monkeypatch) -> None:
        """Should return the user's answer."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_USER,
            summary="Test",
            pending_user_question=PendingUserQuestion(
                question="What is your email?",
            ),
        )

        monkeypatch.setattr("builtins.input", lambda _: "user@example.com")

        answer = prompt_for_user_answer(report)

        assert answer == "user@example.com"

    def test_handles_empty_answer(self, monkeypatch) -> None:
        """Should handle empty user input."""
        report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_USER,
            summary="Test",
            pending_user_question=PendingUserQuestion(
                question="Optional comment?",
            ),
        )

        monkeypatch.setattr("builtins.input", lambda _: "")

        answer = prompt_for_user_answer(report)

        assert answer == ""


class TestRunCliInteractive:
    """Test the main CLI interactive loop."""

    def test_returns_immediately_for_terminal_status(self) -> None:
        """Should return immediately when initial report is terminal."""
        mock_loop = MagicMock()
        mock_session = MagicMock()

        # Initial report is already complete
        mock_loop.run.return_value = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.COMPLETED,
            summary="Task done",
        )

        report = run_cli_interactive(mock_loop, mock_session, args_json=False)

        assert report.status == RuntimeStatus.COMPLETED
        mock_loop.run.assert_called_once()

    def test_resumes_after_confirmation_yes(self, monkeypatch) -> None:
        """Should continue after user approves confirmation."""
        mock_loop = MagicMock()
        mock_session = MagicMock()

        # First report requires confirmation
        pending_report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Waiting",
            pending_confirmation=ConfirmationRequest(
                request_id="req-1",
                action_name="action",
                reason="Test",
                risk_level=RiskLevel.MEDIUM,
                prompt="Approve?",
            ),
        )

        # After approval, loop completes
        completed_report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.COMPLETED,
            summary="Done",
        )

        mock_loop.run.return_value = pending_report
        mock_loop.continue_after_confirmation.return_value = completed_report

        # User approves
        monkeypatch.setattr("builtins.input", lambda _: "yes")

        report = run_cli_interactive(mock_loop, mock_session, args_json=False)

        assert report.status == RuntimeStatus.COMPLETED
        mock_loop.continue_after_confirmation.assert_called_once()
        # Verify decision was passed
        call_args = mock_loop.continue_after_confirmation.call_args
        decision = call_args[0][1]  # Second positional argument
        assert isinstance(decision, ConfirmationDecision)
        assert decision.approved is True

    def test_resumes_after_confirmation_no(self, monkeypatch) -> None:
        """Should handle rejection of confirmation."""
        mock_loop = MagicMock()
        mock_session = MagicMock()

        pending_report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Waiting",
            pending_confirmation=ConfirmationRequest(
                request_id="req-1",
                action_name="action",
                reason="Test",
                risk_level=RiskLevel.HIGH,
                prompt="Approve?",
            ),
        )

        stopped_report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.STOPPED,
            summary="User rejected action",
        )

        mock_loop.run.return_value = pending_report
        mock_loop.continue_after_confirmation.return_value = stopped_report

        inputs = iter(["no", "too risky"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        report = run_cli_interactive(mock_loop, mock_session, args_json=False)

        assert report.status == RuntimeStatus.STOPPED

    def test_resumes_after_user_answer(self, monkeypatch) -> None:
        """Should continue after user provides answer."""
        mock_loop = MagicMock()
        mock_session = MagicMock()

        pending_report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_USER,
            summary="Waiting for input",
            pending_user_question=PendingUserQuestion(
                question="What is your name?",
            ),
        )

        completed_report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.COMPLETED,
            summary="Done",
        )

        mock_loop.run.return_value = pending_report
        mock_loop.continue_after_user_answer.return_value = completed_report

        monkeypatch.setattr("builtins.input", lambda _: "John Doe")

        report = run_cli_interactive(mock_loop, mock_session, args_json=False)

        assert report.status == RuntimeStatus.COMPLETED
        mock_loop.continue_after_user_answer.assert_called_once()
        # Verify answer was passed
        call_args = mock_loop.continue_after_user_answer.call_args
        answer = call_args[0][1]  # Second positional argument
        assert answer == "John Doe"

    def test_handles_multiple_resume_cycles(self, monkeypatch) -> None:
        """Should handle multiple pending states in sequence."""
        mock_loop = MagicMock()
        mock_session = MagicMock()

        # First: waiting for user question
        user_pending = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_USER,
            summary="Need user input",
            pending_user_question=PendingUserQuestion(question="Email?"),
        )

        # Second: waiting for confirmation
        confirm_pending = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Need confirmation",
            pending_confirmation=ConfirmationRequest(
                request_id="req-1",
                action_name="submit",
                reason="Submit form",
                risk_level=RiskLevel.MEDIUM,
                prompt="Approve?",
            ),
        )

        # Final: completed
        completed = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.COMPLETED,
            summary="Done",
        )

        mock_loop.run.return_value = user_pending
        mock_loop.continue_after_user_answer.return_value = confirm_pending
        mock_loop.continue_after_confirmation.return_value = completed

        # User provides email, then approves
        inputs = iter(["user@example.com", "yes"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        report = run_cli_interactive(mock_loop, mock_session, args_json=False)

        assert report.status == RuntimeStatus.COMPLETED
        mock_loop.continue_after_user_answer.assert_called_once()
        mock_loop.continue_after_confirmation.assert_called_once()

    def test_json_mode_returns_pending_report(self, capsys) -> None:
        """In JSON mode, should return pending report without prompting."""
        mock_loop = MagicMock()
        mock_session = MagicMock()

        pending_report = FinalReport(
            session_id=_SID,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary="Waiting",
            pending_confirmation=ConfirmationRequest(
                request_id="req-1",
                action_name="action",
                reason="Test",
                risk_level=RiskLevel.MEDIUM,
                prompt="Approve?",
            ),
        )

        mock_loop.run.return_value = pending_report

        report = run_cli_interactive(mock_loop, mock_session, args_json=True)

        # Should return the pending report without interaction
        assert report.status == RuntimeStatus.WAITING_FOR_CONFIRMATION
        mock_loop.continue_after_confirmation.assert_not_called()
        err = capsys.readouterr().err
        assert "--json" in err
        assert "browser-agent" in err
