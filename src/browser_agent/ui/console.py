"""Rich Live Agent Console — subscribes to runtime events via emit()."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, TypeVar

from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.prompt import Confirm, Prompt
from rich.rule import Rule

from browser_agent.config import RuntimeSettings
from browser_agent.runtime.models import ConfirmationRequest, FinalReport, RuntimeStatus
from browser_agent.runtime.session import RuntimeSession
from browser_agent.safety.confirmations import ConfirmationDecision
from browser_agent.ui.events import (
    AgentRunCompleted,
    AgentRunFailed,
    AgentRunStarted,
    ConfirmationRequested,
    GuardrailCheck,
    HumanInterventionRequested,
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
from browser_agent.ui.formatting import (
    FinalSummaryInput,
    build_final_summary_lines,
    compute_timeline_phase_label,
    generate_human_summary,
    humanize_result_status,
    humanize_skill_name,
    infer_error_block,
    truncate_text,
)
from browser_agent.ui.models import AgentConsoleState, TimelineStepView
from browser_agent.ui.pricing import estimate_cost_usd
from browser_agent.ui.render import build_final_summary_panel, build_layout

if TYPE_CHECKING:
    from browser_agent.runtime.loop import RuntimeLoop

T = TypeVar("T")


def blocking_prompt_with_live(
    live: Live,
    app: "AgentConsoleApp",
    fn: Callable[[], T],
) -> T:
    """Exit Rich Live (and alternate screen), run blocking stdin prompts, then resume Live.

    Rich's ``Live.pause()`` is not available in supported Rich versions; ``stop``/``start`` is.
    """
    live.stop()
    app._live = None
    try:
        return fn()
    finally:
        live.start(refresh=True)
        app._live = live
        app._refresh()


def _live_prefers_alt_screen(console: Console) -> bool:
    """Alternate screen is opt-in.

    Default is off: Live updates in the main scroll buffer. That avoids layout “jumping” and
    keystroke echo flickering under the dashboard (alternate screen + frequent refresh redraws
    over echoed characters).

    Set ``BROWSER_AGENT_ALT_SCREEN=1`` for a full-screen buffer that clears when the run ends.
    ``BROWSER_AGENT_NO_ALT_SCREEN=1`` still forces alternate screen off.
    """
    no = os.environ.get("BROWSER_AGENT_NO_ALT_SCREEN", "").strip().lower()
    if no in ("1", "true", "yes", "on"):
        return False
    yes = os.environ.get("BROWSER_AGENT_ALT_SCREEN", "").strip().lower()
    if yes in ("1", "true", "yes", "on"):
        return bool(console.is_terminal and not console.is_dumb_terminal)
    return False


def _reset_terminal_after_live(console: Console) -> None:
    """Best-effort restore after Live / interrupt (cursor + alternate screen)."""
    try:
        console.show_cursor(True)
        console.set_alt_screen(False)
    except Exception:
        pass


def _is_terminal_status(status: RuntimeStatus) -> bool:
    return status in {
        RuntimeStatus.COMPLETED,
        RuntimeStatus.STOPPED,
        RuntimeStatus.FAILED,
    }


def _set_summary(state: AgentConsoleState, text: str) -> None:
    t = text.strip()
    if t and t != state.human_summary:
        state.human_summary = t


def _clear_error(state: AgentConsoleState) -> None:
    state.error_title = None
    state.error_explanation = None
    state.error_hint = None


def _print_pending_confirmation(console: Console, req: ConfirmationRequest) -> None:
    """Show confirmation details on the main terminal after Live stops."""
    console.print()
    console.print(Rule("[bold red]Confirmation required[/]", style="red"))
    console.print(f"[bold]Request ID:[/] {escape(req.request_id)}")
    console.print(f"[bold]Action:[/] {escape(req.action_name)}")
    if req.reason:
        console.print(f"[bold]Reason:[/] {escape(req.reason)}")
    console.print(f"[bold]Risk:[/] {escape(str(req.risk_level.value))}")
    if req.consequences:
        console.print("[bold]Consequences:[/]")
        for c in req.consequences:
            console.print(f"  • {escape(c)}")
    console.print(f"\n{escape(req.prompt)}\n")


def _print_pending_user_question(console: Console, question: str) -> None:
    """Show the blocking question on the main terminal after Live stops."""
    console.print()
    console.print(Rule("[bold cyan]Planner needs input[/]", style="cyan"))
    console.print(escape(question))
    console.print()


def _print_pending_human_intervention(
    console: Console,
    kind: str,
    instruction: str,
    prompt: str,
    allowed_actions: list[str],
    resume_hint: str | None,
) -> None:
    """Show the manual browser checkpoint details after Live stops."""
    console.print()
    console.print(Rule("[bold yellow]Manual browser step required[/]", style="yellow"))
    console.print(f"[bold]Checkpoint:[/] {escape(kind)}")
    console.print(f"[bold]Do this:[/] {escape(instruction)}")
    console.print(f"[bold]Why paused:[/] {escape(prompt)}")
    if allowed_actions:
        console.print("[bold]Allowed actions:[/]")
        for item in allowed_actions:
            console.print(f"  • {escape(item)}")
    if resume_hint:
        console.print(f"\n[bold]Resume:[/] {escape(resume_hint)}")
    console.print()


class AgentConsoleApp:
    """Operator console: implements RuntimeEventEmitter protocol via emit()."""

    def __init__(
        self,
        session: RuntimeSession,
        settings: RuntimeSettings,
        *,
        ui_mode: str = "demo",
    ) -> None:
        self.session = session
        self.settings = settings
        self.state = AgentConsoleState()
        self.state.ui_mode = "debug" if ui_mode == "debug" else "demo"
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
        self._human_checkpoint_pending = False
        self._step_had_non_observe_skill = False

    def emit(self, event: RuntimeEvent) -> None:
        if isinstance(event, AgentRunStarted):
            _clear_error(self.state)
            self._step_had_non_observe_skill = False
            self.state.status = "running"
            self.state.display_phase = "OBSERVE"
            self.state.max_steps_config = event.max_steps
            self.state.step_display = f"0 / {event.max_steps}"
            if event.model_name:
                self.state.model_name = event.model_name
            if event.provider_kind:
                self.state.provider_kind = event.provider_kind
            self.state.run_started_at = event.timestamp
            _set_summary(
                self.state,
                generate_human_summary(event_kind="run_started"),
            )
        elif isinstance(event, StepStarted):
            _clear_error(self.state)
            self._step_had_non_observe_skill = False
            self.state.display_phase = "OBSERVE"
            self.state.step_display = f"{event.step_number} / {self.state.max_steps_config or self.session.settings.max_steps}"
            self.state.status = "running"
        elif isinstance(event, ObservationReady):
            self.state.display_phase = "OBSERVE"
            self.state.current_url = event.page_url
            self.state.page_title = event.page_title
            self.state.observation_summary = event.summary
            self.state.interactive_element_count = event.interactive_element_count
            self.state.observation_warnings = list(event.warnings)
            _set_summary(
                self.state,
                generate_human_summary(
                    event_kind="observation_ready",
                    observation_snippet=truncate_text(event.summary, 80),
                ),
            )
        elif isinstance(event, PlannerDecisionReady):
            self.state.display_phase = "PLAN"
            self.state.last_decision_type = event.decision_type
            self.state.last_rationale = event.rationale_summary
            self.state.last_expected_outcome = event.expected_outcome
            self._pending_skill = event.chosen_skill
            self._pending_target = event.skill_input_summary
            dt = (event.decision_type or "").lower()
            if dt == "fail":
                _clear_error(self.state)
                self.state.error_title = "Planner failure"
                self.state.error_explanation = truncate_text(event.rationale_summary, 240)
                self.state.error_hint = "Check planner output and task constraints; see trace for details."
            _set_summary(
                self.state,
                generate_human_summary(
                    event_kind="planner_decision",
                    decision_type=event.decision_type,
                    rationale=event.rationale_summary,
                    expected_outcome=event.expected_outcome,
                    skill_name=event.chosen_skill,
                ),
            )
        elif isinstance(event, GuardrailCheck):
            self.state.display_phase = (
                "GUARDRAIL" if not event.requires_confirmation else "GUARDRAIL"
            )
            if event.requires_confirmation:
                _set_summary(
                    self.state,
                    generate_human_summary(
                        event_kind="guardrail",
                        requires_confirmation=True,
                        guardrail_reason=event.reason,
                    ),
                )
            else:
                _set_summary(
                    self.state,
                    generate_human_summary(
                        event_kind="guardrail",
                        requires_confirmation=False,
                        guardrail_reason=event.reason,
                    ),
                )
        elif isinstance(event, SkillExecutionStarted):
            self.state.display_phase = "ACT"
            if event.skill_name and event.skill_name != "observe_page":
                self._step_had_non_observe_skill = True
            self._pending_skill = event.skill_name
            self._pending_target = event.target_summary
            _set_summary(
                self.state,
                generate_human_summary(
                    event_kind="skill_started",
                    skill_name=event.skill_name,
                    target_summary=event.target_summary,
                ),
            )
        elif isinstance(event, SkillExecutionCompleted):
            self._last_skill_status = event.status
            err = infer_error_block(status=event.status, message=event.message)
            if err:
                title, explanation, hint = err
                self.state.error_title = title
                self.state.error_explanation = explanation
                self.state.error_hint = hint
            elif event.status.lower() == "success":
                _clear_error(self.state)
            _set_summary(
                self.state,
                generate_human_summary(
                    event_kind="skill_completed",
                    skill_name=event.skill_name,
                    skill_status=event.status,
                    skill_message=event.message,
                ),
            )
        elif isinstance(event, ConfirmationRequested):
            self._confirmation_pending = True
            self.state.display_phase = "WAITING_CONFIRMATION"
            self.state.bottom_mode = "confirm"
            self.state.status = "waiting"
            self.state.confirm_action = event.action_name
            self.state.confirm_reason = event.reason
            self.state.confirm_prompt = event.prompt
            self.state.confirm_consequences = list(event.consequences)
            self.state.error_title = "Confirmation required"
            self.state.error_explanation = truncate_text(event.reason or event.prompt, 220)
            self.state.error_hint = "Approve (Y) only if you accept the listed consequences."
            _set_summary(
                self.state,
                generate_human_summary(
                    event_kind="confirmation",
                    confirm_action=event.action_name,
                ),
            )
        elif isinstance(event, UserInputRequested):
            self._user_input_pending = True
            self.state.display_phase = "WAITING_USER"
            self.state.bottom_mode = "input"
            self.state.status = "waiting"
            self.state.input_question = event.question
            _clear_error(self.state)
            _set_summary(
                self.state,
                generate_human_summary(event_kind="user_input", question=event.question),
            )
        elif isinstance(event, HumanInterventionRequested):
            self._human_checkpoint_pending = True
            self.state.display_phase = "WAITING_INTERVENTION"
            self.state.bottom_mode = "checkpoint"
            self.state.status = "waiting"
            self.state.checkpoint_kind = event.kind
            self.state.checkpoint_instruction = event.instruction
            self.state.checkpoint_prompt = event.prompt
            self.state.checkpoint_resume_hint = event.resume_hint or ""
            self.state.checkpoint_allowed_actions = list(event.allowed_actions)
            self.state.error_title = "Manual browser step required"
            self.state.error_explanation = truncate_text(event.instruction, 220)
            self.state.error_hint = "Complete the requested step in the browser, then resume the run."
            _set_summary(
                self.state,
                generate_human_summary(
                    event_kind="human_intervention",
                    question=event.instruction,
                ),
            )
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
                self.state.display_phase = "OBSERVE"

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

            phase_label = compute_timeline_phase_label(
                session_status=event.session_status,
                step_had_non_observe_skill=self._step_had_non_observe_skill,
            )
            skill_display = humanize_skill_name(skill if skill != "—" else None)
            result_display = humanize_result_status(result)
            self.state.timeline.append(
                TimelineStepView(
                    step_number=event.step_number,
                    phase_label=phase_label,
                    rationale_summary=truncate_text(self.state.last_rationale or "—", 200),
                    expected_outcome=self.state.last_expected_outcome,
                    skill_name=skill if skill != "—" else None,
                    target_summary=target if target != "—" else None,
                    result_status=result,
                    progress_note=event.progress_summary,
                    skill_display=skill_display,
                    result_display=result_display,
                )
            )
            if len(self.state.timeline) > self.state.max_timeline_steps:
                self.state.timeline = self.state.timeline[-self.state.max_timeline_steps :]
            _set_summary(
                self.state,
                generate_human_summary(
                    event_kind="step_completed",
                    progress_summary=event.progress_summary,
                ),
            )
        elif isinstance(event, TokenUsageUpdated):
            self.state.prompt_tokens_total = event.cumulative_prompt_tokens
            self.state.completion_tokens_total = event.cumulative_completion_tokens
            self.state.total_tokens_total = event.cumulative_total_tokens
            self.state.llm_request_count = event.request_count
            self.state.tokens_approximate = event.approximate
            if event.latency_ms is not None:
                self.state.llm_latency_sum_ms += float(event.latency_ms)
                self.state.llm_latency_count += 1
            model = event.model_name or self.state.model_name
            cost = estimate_cost_usd(
                model,
                event.cumulative_prompt_tokens,
                event.cumulative_completion_tokens,
            )
            self.state.estimated_cost_usd = cost
        elif isinstance(event, AgentRunCompleted):
            self.state.status = event.status
            st = event.status.lower()
            if st == "failed":
                self.state.display_phase = "FAILED"
            else:
                self.state.display_phase = "FINISHED"
            self.state.bottom_mode = "idle"
            self._build_final_summary(event)
            _set_summary(self.state, truncate_text(event.summary, 160))
        elif isinstance(event, AgentRunFailed):
            self.state.status = "failed"
            self.state.display_phase = "FAILED"
            self.state.error_title = "Run error"
            self.state.error_explanation = truncate_text(event.message, 220)
            self.state.error_hint = truncate_text(event.failure_reason or "", 160) or None
            if self.state.error_hint == self.state.error_explanation:
                self.state.error_hint = "See trace artifacts for full detail."

        self._refresh()

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(build_layout(self.state, width=self.console.width), refresh=True)

    def _latency_avg_display(self) -> str:
        if self.state.llm_latency_count <= 0:
            return "—"
        avg = self.state.llm_latency_sum_ms / self.state.llm_latency_count
        approx = " (estimated)" if self.state.tokens_approximate else ""
        return f"{avg:.0f} ms{approx}"

    def _key_actions_from_session(self, max_items: int = 5) -> list[str]:
        fr = self.session.final_report
        if fr and fr.actions_taken:
            out: list[str] = []
            seen: set[str] = set()
            for action in fr.actions_taken:
                label = str(action).strip()
                if not label or label in seen:
                    continue
                seen.add(label)
                out.append(label)
                if len(out) >= max_items:
                    break
            return out
        lines: list[str] = []
        for item in self.session.trace_items[-12:]:
            name = item.action_name or (
                item.planner_decision_type.value if item.planner_decision_type else None
            )
            if not name:
                continue
            rat = (item.rationale_summary or "").strip()
            piece = humanize_skill_name(name)
            if rat:
                piece = f"{piece} — {truncate_text(rat, 72)}"
            lines.append(piece)
        out: list[str] = []
        seen: set[str] = set()
        for L in reversed(lines):
            if L not in seen:
                seen.add(L)
                out.append(L)
            if len(out) >= max_items:
                break
        return list(reversed(out))

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

        fr = self.session.final_report
        failure_reason = getattr(fr, "failure_reason", None) if fr else None
        completed = bool(getattr(fr, "completed", False)) if fr else False
        status_enum = getattr(fr, "status", None) if fr else None
        if status_enum == RuntimeStatus.COMPLETED and completed:
            outcome = "Completed"
        elif status_enum == RuntimeStatus.FAILED:
            outcome = "Failed"
        else:
            outcome = "Partial"

        self.state.outcome_label = outcome
        st = event.status.lower()
        if st == "failed":
            self.state.final_run_headline = "RUN FAILED"
        elif st == "completed":
            self.state.final_run_headline = "RUN COMPLETED"
        else:
            self.state.final_run_headline = "RUN STOPPED"

        key_actions = self._key_actions_from_session(5)
        self.state.key_actions = key_actions

        data = FinalSummaryInput(
            task=self.state.task,
            status=event.status,
            outcome_label=outcome,
            step_count=event.step_count,
            llm_request_count=self.state.llm_request_count,
            prompt_tokens=self.state.prompt_tokens_total,
            completion_tokens=self.state.completion_tokens_total,
            total_tokens=self.state.total_tokens_total,
            tokens_approximate=self.state.tokens_approximate,
            estimated_cost_usd=self.state.estimated_cost_usd,
            latency_avg_ms=self._latency_avg_display(),
            duration_mmss=dur,
            summary=event.summary,
            visited_urls=urls,
            trace_refs=event.trace_refs,
            artifact_refs=event.artifact_refs,
            key_actions=key_actions,
            failure_reason=failure_reason,
        )
        self.state.final_summary_lines = build_final_summary_lines(data)
        self.state.show_final_summary = True

    def run_interactive_loop(self, loop: RuntimeLoop) -> FinalReport:
        """Run runtime with Live UI and Rich prompts for pause states."""
        self.console.print("[bold cyan]Starting Agent Console…[/]")
        use_alt = _live_prefers_alt_screen(self.console)
        self.console.print(
            "[yellow]Tip:[/] The [bold]Operator[/] panel is not a text field — do not type while the agent runs. "
            "Wait for a confirmation or answer prompt (the live view pauses first). "
            "Accidental keys may flicker at the bottom; they are not sent to the agent.\n"
        )
        if use_alt:
            self.console.print(
                "[dim]Live UI uses the terminal alternate screen; it clears when the run ends. "
                "When confirmation or your answer is needed, the live view pauses and prompts appear "
                "on the main terminal. Traces and artifact paths appear in the final summary.[/]\n"
            )
        else:
            self.console.print(
                "[dim]Live layout updates in the scroll buffer (default). "
                "Traces and artifact paths appear in the final summary. "
                "Set [bold]BROWSER_AGENT_ALT_SCREEN=1[/] for a full-screen alternate buffer.[/]\n"
            )
        layout = build_layout(self.state, width=self.console.width)
        report: FinalReport
        try:
            with Live(
                layout,
                console=self.console,
                refresh_per_second=4,
                screen=use_alt,
                transient=not use_alt,
                vertical_overflow="crop",
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

                        def _confirm() -> ConfirmationDecision:
                            _print_pending_confirmation(self.console, req)
                            approved = Confirm.ask(
                                f"Approve [bold]{escape(req.action_name)}[/]?",
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
                            return ConfirmationDecision(
                                request_id=req.request_id,
                                approved=approved,
                                reviewer_notes=notes,
                            )

                        decision = blocking_prompt_with_live(live, self, _confirm)
                        report = loop.continue_after_confirmation(self.session, decision)
                    elif report.status == RuntimeStatus.WAITING_FOR_USER:
                        if report.pending_user_question is None:
                            break
                        q = report.pending_user_question.question
                        self.state.input_question = q
                        self.state.bottom_mode = "input"
                        self._refresh()

                        def _answer() -> str:
                            _print_pending_user_question(self.console, q)
                            return Prompt.ask("[bold]Your answer[/]", default="")

                        answer = blocking_prompt_with_live(live, self, _answer)
                        report = loop.continue_after_user_answer(self.session, answer)
                    elif report.status == RuntimeStatus.WAITING_FOR_INTERVENTION:
                        if report.pending_human_intervention is None:
                            break
                        request = report.pending_human_intervention
                        self.state.bottom_mode = "checkpoint"
                        self.state.checkpoint_kind = request.kind.value
                        self.state.checkpoint_instruction = request.instruction
                        self.state.checkpoint_prompt = request.prompt
                        self.state.checkpoint_resume_hint = request.resume_hint or ""
                        self.state.checkpoint_allowed_actions = list(
                            request.allowed_actions
                        )
                        self._refresh()

                        def _resume_note() -> str:
                            _print_pending_human_intervention(
                                self.console,
                                request.kind.value,
                                request.instruction,
                                request.prompt,
                                list(request.allowed_actions),
                                request.resume_hint,
                            )
                            return Prompt.ask(
                                "[bold]Press Enter when done[/] or leave a short note",
                                default="",
                                show_default=False,
                            )

                        note = blocking_prompt_with_live(live, self, _resume_note)
                        report = loop.continue_after_human_intervention(
                            self.session,
                            note,
                        )
                    else:
                        break
                    self._refresh()

                self._live = None
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Agent Console interrupted by user (Ctrl+C).[/]")
            raise
        finally:
            self._live = None
            _reset_terminal_after_live(self.console)

        if self.state.show_final_summary and self.state.final_summary_lines:
            if not use_alt and self.console.is_terminal:
                self.console.clear(home=True)
            self.console.print()
            self.console.print(build_final_summary_panel(self.state))
        if report.status == RuntimeStatus.COMPLETED:
            self.console.print("\n[bold green]Run completed successfully.[/]")
        elif report.status == RuntimeStatus.FAILED:
            self.console.print("\n[bold red]Run ended with failures — see summary and trace artifacts.[/]")
        else:
            self.console.print("\n[bold yellow]Run stopped — see summary for outcome and artifact paths.[/]")
        self.console.print(
            "[dim]Artifacts (e.g. traces/*.md, traces/*.jsonl) are under your configured trace directory.[/]\n"
        )

        return report
