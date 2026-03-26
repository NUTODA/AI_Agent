"""Rich Live Agent Console — subscribes to runtime events via emit()."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.prompt import Confirm, Prompt

from browser_agent.config import RuntimeSettings
from browser_agent.runtime.models import FinalReport, RuntimeStatus
from browser_agent.runtime.session import RuntimeSession
from browser_agent.safety.confirmations import ConfirmationDecision
from browser_agent.ui.events import (
    AgentRunCompleted,
    AgentRunFailed,
    AgentRunStarted,
    ConfirmationRequested,
    GuardrailCheck,
    ObservationReady,
    PlannerDecisionReady,
    RuntimeEvent,
    SkillExecutionCompleted,
    SkillExecutionStarted,
    StepCompleted,
    StepStarted,
    TokenUsageUpdated,
    UserInputRequested,
)
from browser_agent.ui.models import AgentConsoleState, TimelineStepView
from browser_agent.ui.pricing import estimate_cost_usd
from browser_agent.ui.render import build_final_summary_panel, build_layout

if TYPE_CHECKING:
    from browser_agent.runtime.loop import RuntimeLoop


def _is_terminal_status(status: RuntimeStatus) -> bool:
    return status in {
        RuntimeStatus.COMPLETED,
        RuntimeStatus.STOPPED,
        RuntimeStatus.FAILED,
    }


class AgentConsoleApp:
    """Operator console: implements RuntimeEventEmitter protocol via emit()."""

    def __init__(self, session: RuntimeSession, settings: RuntimeSettings) -> None:
        self.session = session
        self.settings = settings
        self.state = AgentConsoleState()
        self.state.task = session.task.request
        self.state.model_name = settings.planner_model
        self.state.provider_kind = settings.planner_provider
        self.console = Console()
        self._live: Live | None = None
        self._last_skill_status: str | None = None
        self._pending_skill: str | None = None
        self._pending_target: str | None = None
        self._confirmation_pending = False
        self._user_input_pending = False

    def emit(self, event: RuntimeEvent) -> None:
        if isinstance(event, AgentRunStarted):
            self.state.status = "running"
            self.state.phase = "observe"
            self.state.max_steps_config = event.max_steps
            self.state.step_display = f"0 / {event.max_steps}"
            if event.model_name:
                self.state.model_name = event.model_name
            if event.provider_kind:
                self.state.provider_kind = event.provider_kind
            self.state.run_started_at = event.timestamp
        elif isinstance(event, StepStarted):
            self.state.phase = "observe"
            self.state.step_display = f"{event.step_number} / {self.state.max_steps_config or self.session.settings.max_steps}"
            self.state.status = "running"
        elif isinstance(event, ObservationReady):
            self.state.phase = "plan"
            self.state.current_url = event.page_url
            self.state.page_title = event.page_title
            self.state.observation_summary = event.summary
            self.state.interactive_element_count = event.interactive_element_count
            self.state.observation_warnings = list(event.warnings)
        elif isinstance(event, PlannerDecisionReady):
            self.state.phase = "act"
            self.state.last_decision_type = event.decision_type
            self.state.last_rationale = event.rationale_summary
            self.state.last_expected_outcome = event.expected_outcome
            self._pending_skill = event.chosen_skill
            self._pending_target = event.skill_input_summary
        elif isinstance(event, GuardrailCheck):
            self.state.phase = "confirm" if event.requires_confirmation else "guardrail"
        elif isinstance(event, SkillExecutionStarted):
            self.state.phase = "act"
            self._pending_skill = event.skill_name
            self._pending_target = event.target_summary
        elif isinstance(event, SkillExecutionCompleted):
            self._last_skill_status = event.status
        elif isinstance(event, ConfirmationRequested):
            self._confirmation_pending = True
            self.state.phase = "confirm"
            self.state.bottom_mode = "confirm"
            self.state.status = "waiting"
            self.state.confirm_action = event.action_name
            self.state.confirm_reason = event.reason
            self.state.confirm_prompt = event.prompt
            self.state.confirm_consequences = list(event.consequences)
        elif isinstance(event, UserInputRequested):
            self._user_input_pending = True
            self.state.phase = "wait_input"
            self.state.bottom_mode = "input"
            self.state.status = "waiting"
            self.state.input_question = event.question
        elif isinstance(event, StepCompleted):
            self.state.step_display = (
                f"{self.session.step_count} / {self.session.settings.max_steps}"
            )
            if event.session_status == RuntimeStatus.RUNNING.value:
                self.state.bottom_mode = "idle"
                self.state.status = "running"
            elif event.session_status == RuntimeStatus.WAITING_FOR_CONFIRMATION.value:
                self.state.bottom_mode = "confirm"
                self.state.status = "waiting"
            elif event.session_status == RuntimeStatus.WAITING_FOR_USER.value:
                self.state.bottom_mode = "input"
                self.state.status = "waiting"
            else:
                self.state.bottom_mode = "idle"
            if event.session_status not in {
                RuntimeStatus.WAITING_FOR_CONFIRMATION.value,
                RuntimeStatus.WAITING_FOR_USER.value,
            }:
                self.state.phase = "observe"

            if self._confirmation_pending:
                result = "waiting_for_confirmation"
                skill = self._pending_skill or "—"
                target = self._pending_target or "—"
                self._confirmation_pending = False
            elif self._user_input_pending:
                result = "need_user_input"
                skill = self._pending_skill or "—"
                target = self._pending_target or "—"
                self._user_input_pending = False
            else:
                result = self._last_skill_status or "—"
                skill = self._pending_skill or "—"
                target = self._pending_target or "—"

            phase_label = (self.state.last_decision_type or "step").upper()
            self.state.timeline.append(
                TimelineStepView(
                    step_number=event.step_number,
                    phase_label=phase_label,
                    rationale_summary=self.state.last_rationale or "—",
                    expected_outcome=self.state.last_expected_outcome,
                    skill_name=skill,
                    target_summary=target,
                    result_status=result,
                    progress_note=event.progress_summary,
                )
            )
            if len(self.state.timeline) > self.state.max_timeline_steps:
                self.state.timeline = self.state.timeline[-self.state.max_timeline_steps :]
        elif isinstance(event, TokenUsageUpdated):
            self.state.prompt_tokens_total = event.cumulative_prompt_tokens
            self.state.completion_tokens_total = event.cumulative_completion_tokens
            self.state.total_tokens_total = event.cumulative_total_tokens
            self.state.llm_request_count = event.request_count
            self.state.tokens_approximate = event.approximate
            model = event.model_name or self.state.model_name
            cost = estimate_cost_usd(
                model,
                event.cumulative_prompt_tokens,
                event.cumulative_completion_tokens,
            )
            self.state.estimated_cost_usd = cost
        elif isinstance(event, AgentRunCompleted):
            self.state.status = event.status
            self.state.phase = "done"
            self.state.bottom_mode = "idle"
            self._build_final_summary(event)
        elif isinstance(event, AgentRunFailed):
            self.state.status = "failed"
            self.state.phase = "done"

        self._refresh()

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(build_layout(self.state), refresh=True)

    def _build_final_summary(self, event: AgentRunCompleted) -> None:
        urls: list[str] = []
        seen: set[str] = set()
        for obs in self.session.observations:
            if obs.page_url and obs.page_url not in seen:
                seen.add(obs.page_url)
                urls.append(obs.page_url)
        dur = "—"
        if self.state.run_started_at is not None:
            delta = datetime.now(timezone.utc) - self.state.run_started_at
            sec = int(delta.total_seconds())
            dur = f"{sec // 60:02d}:{sec % 60:02d}"
        approx = " (estimated)" if self.state.tokens_approximate else ""
        cost_line = (
            f"${self.state.estimated_cost_usd:.4f}{approx}"
            if self.state.estimated_cost_usd is not None
            else f"N/A{approx}"
        )
        lines = [
            f"Task:\n  {self.state.task[:200]}",
            f"Steps:\n  {event.step_count}",
            f"LLM calls:\n  {self.state.llm_request_count}",
            f"Tokens used:\n  {self.state.total_tokens_total:,}{approx}",
            f"Duration:\n  {dur}",
            f"Est. cost:\n  {cost_line}",
            f"Outcome:\n  {event.status} — {event.summary[:300]}",
            "Visited URLs:",
            *[f"  - {u}" for u in urls[:12]] or ["  —"],
            "Artifacts:",
            *[f"  - {a}" for a in event.artifact_refs[:12]] or ["  —"],
            "Trace:",
            *[f"  - {t}" for t in event.trace_refs[:6]] or ["  —"],
        ]
        self.state.final_summary_lines = lines
        self.state.show_final_summary = True

    def run_interactive_loop(self, loop: RuntimeLoop) -> FinalReport:
        """Run runtime with Live UI and Rich prompts for pause states."""
        layout = build_layout(self.state)
        with Live(
            layout,
            console=self.console,
            refresh_per_second=8,
            transient=False,
        ) as live:
            self._live = live
            report = loop.run(self.session)
            self._refresh()

            while not _is_terminal_status(report.status):
                if report.status == RuntimeStatus.WAITING_FOR_CONFIRMATION:
                    if report.pending_confirmation is None:
                        break
                    req = report.pending_confirmation
                    self.state.bottom_mode = "confirm"
                    self._refresh()
                    with live.pause(refresh=True):
                        self.console.print()
                        approved = Confirm.ask(
                            f"Approve [bold]{req.action_name}[/]?",
                            default=False,
                        )
                        notes: str | None = None
                        if not approved:
                            notes = Prompt.ask(
                                "Reason for rejection (optional)",
                                default="",
                                show_default=False,
                            )
                            notes = notes.strip() or None
                        decision = ConfirmationDecision(
                            request_id=req.request_id,
                            approved=approved,
                            reviewer_notes=notes,
                        )
                    report = loop.continue_after_confirmation(self.session, decision)
                elif report.status == RuntimeStatus.WAITING_FOR_USER:
                    if report.pending_user_question is None:
                        break
                    q = report.pending_user_question.question
                    self.state.bottom_mode = "input"
                    self._refresh()
                    with live.pause(refresh=True):
                        self.console.print()
                        answer = Prompt.ask(f"[cyan]{q}[/]", default="")
                    report = loop.continue_after_user_answer(self.session, answer)
                else:
                    break
                self._refresh()

            self._live = None

        if self.state.show_final_summary and self.state.final_summary_lines:
            self.console.print()
            self.console.print(build_final_summary_panel(self.state))

        return report
