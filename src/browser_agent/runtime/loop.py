"""Runtime orchestration loop for the browser agent."""

from __future__ import annotations

from time import perf_counter

from browser_agent.browser.engine import BrowserEngine
from browser_agent.llm.planner import (
    Planner,
    PlannerDecision,
    describe_skill_registry,
)
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    FinalReport,
    HumanInterventionKind,
    HumanInterventionRequest,
    InteractiveElement,
    PendingUserQuestion,
    PlannerDecisionType,
    PlannerProgressState,
    ProgressOutcome,
    RuntimeStatus,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
)
from browser_agent.runtime.element_remap import remap_stale_element_references
from browser_agent.runtime.progress import ProgressDetector
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationDecision, ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.base import SkillContext, SkillExecutionError
from browser_agent.skills.registry import SkillRegistry
from browser_agent.ui.events import (
    AgentRunCompleted,
    AgentRunFailed,
    AgentRunStarted,
    ConfirmationRequested,
    GuardrailCheck,
    HumanInterventionRequested,
    NoOpEventEmitter,
    ObservationReady,
    PlannerDecisionReady,
    RuntimeEventEmitter,
    SkillExecutionCompleted,
    SkillExecutionStarted,
    StepCompleted,
    StepStarted,
    TokenUsageUpdated,
    UserInputRequested,
    utc_now,
)
from browser_agent.ui.formatting import format_tool_target, summarize_skill_input, truncate_text


class RuntimeLoop:
    """Coordinate planning, safety checks, skill execution, and reporting."""

    _RECOVERABLE_VALIDATION_RATIONALE = (
        "The proposed action is recoverable but violates runtime targeting rules. "
        "Replan using the current observation."
    )
    _MAX_PLANNER_REPLAN_ATTEMPTS = 2
    _EXPLORATION_SKILLS = frozenset(
        {
            "observe_page",
            "extract_page_text",
            "get_interactive_elements",
            "scroll_viewport",
        }
    )
    _WEAK_EXPLORATION_PROGRESS_SIGNALS = frozenset(
        {
            "visible text excerpt changed",
            "planner marked progress after successful execution",
        }
    )

    def __init__(
        self,
        *,
        planner: Planner,
        skill_registry: SkillRegistry,
        browser: BrowserEngine,
        safety_guardrails: SafetyGuardrails,
        confirmation_manager: ConfirmationManager,
        trace_recorder: TraceRecorder,
        progress_detector: ProgressDetector | None = None,
        event_emitter: RuntimeEventEmitter | None = None,
        planner_display_name: str | None = None,
        planner_provider_kind: str | None = None,
        keep_browser_open: bool = False,
    ) -> None:
        self.planner = planner
        self.skill_registry = skill_registry
        self.browser = browser
        self.safety_guardrails = safety_guardrails
        self.confirmation_manager = confirmation_manager
        self.trace_recorder = trace_recorder
        self.progress_detector = progress_detector or ProgressDetector()
        self.available_skills = describe_skill_registry(skill_registry)
        self._events: RuntimeEventEmitter = event_emitter or NoOpEventEmitter()
        self._planner_display_name = planner_display_name
        self._planner_provider_kind = planner_provider_kind
        self.keep_browser_open = keep_browser_open

    def _finish(self, session: RuntimeSession, report: FinalReport) -> FinalReport:
        result = session.complete(report)
        if result.status not in {
            RuntimeStatus.WAITING_FOR_CONFIRMATION,
            RuntimeStatus.WAITING_FOR_USER,
            RuntimeStatus.WAITING_FOR_INTERVENTION,
        }:
            self._events.emit(
                AgentRunCompleted(
                    timestamp=utc_now(),
                    status=result.status.value,
                    summary=result.summary,
                    step_count=result.step_count,
                    trace_refs=tuple(result.trace_refs),
                    artifact_refs=tuple(result.artifact_refs),
                    final_url=result.final_url,
                )
            )
        return result

    def _emit_token_usage(self, session: RuntimeSession, step_index: int | None) -> None:
        u = session.llm_usage
        self._events.emit(
            TokenUsageUpdated(
                timestamp=utc_now(),
                step_number=step_index,
                prompt_tokens=u.last_prompt_tokens,
                completion_tokens=u.last_completion_tokens,
                total_tokens=u.last_total_tokens,
                cumulative_prompt_tokens=u.cumulative_prompt_tokens,
                cumulative_completion_tokens=u.cumulative_completion_tokens,
                cumulative_total_tokens=u.cumulative_total_tokens,
                request_count=u.request_count,
                latency_ms=u.last_latency_ms,
                approximate=u.last_approximate,
                model_name=u.last_model_name or self._planner_display_name,
            )
        )

    def _emit_observation_ready(self, step_index: int, observation: AgentObservation) -> None:
        self._events.emit(
            ObservationReady(
                timestamp=utc_now(),
                step_number=step_index,
                page_url=observation.page_url,
                page_title=observation.page_title,
                summary=truncate_text(observation.summary, 400),
                interactive_element_count=len(observation.interactive_elements),
                warnings=tuple(observation.observation_errors[:8]),
            )
        )

    def _emit_planner_decision(self, step_index: int, decision: PlannerDecision) -> None:
        self._events.emit(
            PlannerDecisionReady(
                timestamp=utc_now(),
                step_number=step_index,
                decision_type=decision.decision_type.value,
                rationale_summary=truncate_text(decision.rationale, 320),
                expected_outcome=(
                    truncate_text(decision.expected_outcome, 240)
                    if decision.expected_outcome
                    else None
                ),
                chosen_skill=decision.chosen_skill,
                skill_input_summary=summarize_skill_input(decision.skill_input or {}),
            )
        )

    def _emit_step_completed(
        self,
        step_index: int,
        progress_summary: str | None,
        report: FinalReport | None,
    ) -> None:
        status = (
            report.status.value
            if report is not None
            else RuntimeStatus.RUNNING.value
        )
        self._events.emit(
            StepCompleted(
                timestamp=utc_now(),
                step_number=step_index,
                progress_summary=(
                    truncate_text(progress_summary, 200) if progress_summary else None
                ),
                session_status=status,
            )
        )

    def run(self, session: RuntimeSession) -> FinalReport:
        """Execute the runtime loop until completion or a controlled stop."""

        if session.pending_confirmation is not None and session.final_report is not None:
            return session.final_report
        if session.pending_user_question is not None and session.final_report is not None:
            return session.final_report
        if (
            session.pending_human_intervention is not None
            and session.final_report is not None
        ):
            return session.final_report
        return self._run_loop(session)

    def continue_after_confirmation(
        self,
        session: RuntimeSession,
        decision: ConfirmationDecision,
    ) -> FinalReport:
        """Resume execution after the operator answered a confirmation request."""

        approved = session.continue_after_confirmation(decision)
        if approved is None:
            report = FinalReport(
                session_id=session.session_id,
                status=RuntimeStatus.STOPPED,
                summary="Execution stopped because the operator rejected the action.",
                completed=False,
                actions_taken=self._actions_taken(session),
                next_steps=[
                    "Provide a different instruction or restart the task with a safer goal."
                ],
                trace_refs=self._trace_refs(session),
                artifact_refs=self._artifact_refs(session),
                final_url=self._final_url(session),
                step_count=session.step_count,
                failure_reason=session.failure_reason,
            )
            return self._finish(session, report)

        approved_action, approved_planner_decision = approved
        session.record_history(
            f"Continuing after confirmation for action {approved_action.action_id}"
        )
        return self._run_loop(
            session,
            resumed_action=approved_action,
            resumed_decision=approved_planner_decision,
            resumed_notes=[
                "Continued after explicit operator confirmation; executing approved step once."
            ],
        )

    def continue_after_user_answer(
        self,
        session: RuntimeSession,
        answer: str,
    ) -> FinalReport:
        """Resume execution after the operator answered a blocking question."""

        session.continue_after_user_answer(answer)
        return self._run_loop(session)

    def continue_after_human_intervention(
        self,
        session: RuntimeSession,
        note: str = "",
    ) -> FinalReport:
        """Resume execution after the operator completed a manual browser step."""

        session.continue_after_human_intervention(note)
        return self._run_loop(session)

    def _run_loop(
        self,
        session: RuntimeSession,
        *,
        resumed_action: AgentAction | None = None,
        resumed_decision: PlannerDecision | None = None,
        resumed_notes: list[str] | None = None,
    ) -> FinalReport:
        session.start()
        self.trace_recorder.bind_session(session.session_id)

        try:
            self.browser.start()
        except Exception as exc:
            self._events.emit(
                AgentRunFailed(
                    timestamp=utc_now(),
                    message="Browser failed to start.",
                    failure_reason=str(exc),
                )
            )
            return self._finish(session, self._startup_failure_report(session, exc))

        self._events.emit(
            AgentRunStarted(
                timestamp=utc_now(),
                session_id=session.session_id,
                task_summary=truncate_text(session.task.request, 200),
                max_steps=session.settings.max_steps,
                model_name=self._planner_display_name,
                provider_kind=self._planner_provider_kind,
            )
        )

        try:
            if resumed_action is not None and resumed_decision is not None:
                self._events.emit(StepStarted(timestamp=utc_now(), step_number=session.step_count))
                pre_observation = self._observe_current_page(session, step_index=session.step_count)
                self._emit_observation_ready(session.step_count, pre_observation)
                prior_observations = list(session.observations[:-1])
                params_before = dict(resumed_action.parameters)
                resumed_action = remap_stale_element_references(
                    resumed_action,
                    pre_observation,
                    prior_observations,
                )
                if resumed_action.parameters != params_before:
                    session.record_history(
                        "Adjusted targeting after confirmation: element_id or selector "
                        "was remapped to the fresh observation."
                    )
                resumed_decision = resumed_decision.model_copy(
                    update={"skill_input": dict(resumed_action.parameters)}
                )
                resumed_report = self._execute_action_step(
                    session=session,
                    step_index=session.step_count,
                    observation_before=pre_observation,
                    decision=resumed_decision,
                    action=resumed_action,
                    record_action=False,
                    notes=resumed_notes or [],
                )
                if resumed_report is not None:
                    return resumed_report

            while session.step_count < session.settings.max_steps:
                step_index = session.step_count
                self._events.emit(StepStarted(timestamp=utc_now(), step_number=step_index))
                try:
                    observation_before = self._observe_current_page(session, step_index=step_index)
                except Exception as exc:
                    self._events.emit(
                        AgentRunFailed(
                            timestamp=utc_now(),
                            message="Observation failed.",
                            failure_reason=str(exc),
                        )
                    )
                    report = FinalReport(
                        session_id=session.session_id,
                        status=RuntimeStatus.FAILED,
                        summary="Runtime failed while observing the current page.",
                        completed=False,
                        actions_taken=self._actions_taken(session),
                        next_steps=["Inspect the browser observation failure and trace."],
                        trace_refs=self._trace_refs(session),
                        artifact_refs=self._artifact_refs(session),
                        final_url=self._final_url(session),
                        step_count=session.step_count,
                        failure_reason=str(exc),
                    )
                    return self._finish(session, report)
                self._emit_observation_ready(step_index, observation_before)
                decision = self._decide_with_runtime_validation(
                    session=session,
                    observation=observation_before,
                )

                thought = decision.to_agent_thought()
                session.add_thought(thought)
                self._emit_planner_decision(step_index, decision)
                self._emit_token_usage(session, step_index)

                if decision.decision_type == PlannerDecisionType.ASK_USER:
                    return self._handle_ask_user(
                        session=session,
                        step_index=step_index,
                        observation=observation_before,
                        thought=thought,
                        decision=decision,
                    )

                if decision.decision_type == PlannerDecisionType.FAIL:
                    return self._handle_planner_failure(
                        session=session,
                        step_index=step_index,
                        observation=observation_before,
                        thought=thought,
                        decision=decision,
                    )

                if decision.decision_type == PlannerDecisionType.FINISH:
                    return self._execute_action_step(
                        session=session,
                        step_index=step_index,
                        observation_before=observation_before,
                        decision=decision,
                        action=decision.to_finish_action(),
                    ) or self._build_stopped_report(
                        session,
                        "The runtime stopped without a final report after finish_task.",
                    )

                action = decision.to_agent_action()
                if self._is_repeated_action_without_progress(action, session):
                    return self._handle_repeated_action_stop(
                        session=session,
                        step_index=step_index,
                        observation=observation_before,
                        thought=thought,
                        decision=decision,
                        action=action,
                    )
                if self._is_repetitive_exploration_loop(
                    action=action,
                    session=session,
                    current_observation=observation_before,
                ):
                    return self._handle_repeated_action_stop(
                        session=session,
                        step_index=step_index,
                        observation=observation_before,
                        thought=thought,
                        decision=decision,
                        action=action,
                    )

                guardrail_decision = self.safety_guardrails.classify_action(action)
                self._events.emit(
                    GuardrailCheck(
                        timestamp=utc_now(),
                        step_number=step_index,
                        requires_confirmation=guardrail_decision.requires_confirmation,
                        reason=truncate_text(guardrail_decision.reason, 240),
                        matched_signals=tuple(guardrail_decision.matched_signals[:12]),
                    )
                )
                if (
                    decision.decision_type == PlannerDecisionType.REQUEST_CONFIRMATION
                    or guardrail_decision.requires_confirmation
                ):
                    return self._pause_for_confirmation(
                        session=session,
                        step_index=step_index,
                        observation=observation_before,
                        thought=thought,
                        decision=decision,
                        action=action,
                        reason=guardrail_decision.reason,
                        consequences=guardrail_decision.matched_signals,
                    )

                report = self._execute_action_step(
                    session=session,
                    step_index=step_index,
                    observation_before=observation_before,
                    decision=decision,
                    action=action,
                )
                if report is not None:
                    return report

            return self._finish(session, self._max_steps_report(session))
        finally:
            # Don't stop browser if waiting for confirmation or user input
            # to allow seamless resume via continue_after_confirmation/continue_after_user_answer
            if not self.keep_browser_open and session.status not in {
                RuntimeStatus.WAITING_FOR_CONFIRMATION,
                RuntimeStatus.WAITING_FOR_USER,
                RuntimeStatus.WAITING_FOR_INTERVENTION,
            }:
                try:
                    self.browser.stop()
                except Exception:
                    pass

    def _handle_ask_user(
        self,
        *,
        session: RuntimeSession,
        step_index: int,
        observation: AgentObservation,
        thought,
        decision: PlannerDecision,
    ) -> FinalReport:
        intervention = self._detect_human_intervention(
            question=decision.user_question or "",
            observation=observation,
        )
        if intervention is not None:
            return self._handle_human_intervention(
                session=session,
                step_index=step_index,
                observation=observation,
                thought=thought,
                decision=decision,
                request=intervention,
            )

        question = PendingUserQuestion(question=decision.user_question or "")
        session.set_pending_user_question(question)
        progress_outcome = ProgressOutcome(
            made_progress=False,
            summary="Runtime paused because the planner needs user input.",
            signals=["planner requested user input"],
            no_progress_streak=session.no_progress_streak,
        )
        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.WAITING_FOR_USER,
            summary="The runtime requires more information from the user.",
            completed=False,
            actions_taken=self._actions_taken(session),
            open_questions=[question.question],
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count + 1,
            pending_user_question=question,
        )
        trace_item = self.trace_recorder.record(
            step_index=step_index,
            observation=observation,
            thought=thought,
            planner_decision=decision,
            progress_outcome=progress_outcome,
            state_transition="running -> waiting_for_user",
            report=report,
            notes=["Planner requested additional user information."],
        )
        session.add_trace_item(trace_item)
        report.trace_refs = self._trace_refs(session)
        report.artifact_refs = self._artifact_refs(session)
        session.record_history(
            f"step {step_index}: planner asked the user a blocking question."
        )
        self._events.emit(
            UserInputRequested(
                timestamp=utc_now(),
                step_number=step_index,
                question=question.question,
            )
        )
        session.increment_step()
        self._emit_step_completed(step_index, progress_outcome.summary, report)
        return self._finish(session, report)

    def _detect_human_intervention(
        self,
        *,
        question: str,
        observation: AgentObservation,
    ) -> HumanInterventionRequest | None:
        """Translate planner ask_user prompts into typed browser handoffs when applicable."""

        haystack = " ".join(
            [
                question,
                observation.page_title or "",
                observation.page_url or "",
                observation.summary or "",
                observation.visible_text_excerpt or "",
            ]
        ).lower()

        if any(token in haystack for token in ("captcha", "капча", "не робот", "anti-bot")):
            return HumanInterventionRequest(
                kind=HumanInterventionKind.CAPTCHA,
                instruction=(
                    "Пройдите капчу или anti-bot проверку в открытом окне браузера."
                ),
                prompt=question or "Сайт показал anti-bot challenge, и агент поставил задачу на паузу.",
                resume_hint="Когда откроется целевая страница сайта, вернитесь и продолжите запуск.",
                allowed_actions=[
                    "Решить капчу",
                    "Подождать редирект на сайт",
                ],
            )

        if any(token in haystack for token in ("2fa", "two-factor", "two factor", "sms", "код подтверждения", "verification code")):
            return HumanInterventionRequest(
                kind=HumanInterventionKind.TWO_FACTOR,
                instruction="Подтвердите вход вручную: введите код или завершите 2FA.",
                prompt=question or "Сайт запросил дополнительное подтверждение личности.",
                resume_hint="После успешного входа вернитесь и продолжите запуск.",
                allowed_actions=[
                    "Ввести код подтверждения",
                    "Подтвердить вход вручную",
                ],
            )

        if any(token in haystack for token in ("login", "log in", "sign in", "войд", "авториз", "личный кабинет")):
            return HumanInterventionRequest(
                kind=HumanInterventionKind.LOGIN,
                instruction="Войдите в аккаунт в открытом окне браузера.",
                prompt=question or "Для продолжения сайту нужна авторизация пользователя.",
                resume_hint="Когда окажетесь в личном кабинете или на нужной странице, продолжите запуск.",
                allowed_actions=[
                    "Войти в аккаунт",
                    "Разрешить сайту завершить редиректы после логина",
                ],
            )

        if any(token in haystack for token in ("review", "проверьте", "подтвердите отклик", "confirm application", "сопроводительное письмо")):
            return HumanInterventionRequest(
                kind=HumanInterventionKind.REVIEW,
                instruction="Проверьте подготовленные данные в браузере и убедитесь, что всё выглядит верно.",
                prompt=question or "Нужен ручной review перед чувствительным действием.",
                resume_hint="Если всё в порядке, продолжите запуск.",
                allowed_actions=[
                    "Проверить данные на странице",
                    "Убедиться, что можно продолжать",
                ],
            )

        return None

    def _handle_human_intervention(
        self,
        *,
        session: RuntimeSession,
        step_index: int,
        observation: AgentObservation,
        thought,
        decision: PlannerDecision,
        request: HumanInterventionRequest,
    ) -> FinalReport:
        session.set_pending_human_intervention(request)
        progress_outcome = ProgressOutcome(
            made_progress=False,
            summary="Runtime paused for a manual browser checkpoint.",
            signals=[f"human checkpoint: {request.kind.value}"],
            no_progress_streak=session.no_progress_streak,
        )
        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.WAITING_FOR_INTERVENTION,
            summary="The runtime is waiting for the operator to complete a manual browser step.",
            completed=False,
            actions_taken=self._actions_taken(session),
            open_questions=[request.instruction],
            next_steps=[
                request.instruction,
                request.resume_hint or "Resume the run after the manual browser step is complete.",
            ],
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count + 1,
            pending_human_intervention=request,
        )
        trace_item = self.trace_recorder.record(
            step_index=step_index,
            observation=observation,
            thought=thought,
            planner_decision=decision,
            progress_outcome=progress_outcome,
            state_transition="running -> waiting_for_intervention",
            report=report,
            notes=[request.prompt],
        )
        session.add_trace_item(trace_item)
        report.trace_refs = self._trace_refs(session)
        report.artifact_refs = self._artifact_refs(session)
        session.record_history(
            f"step {step_index}: paused for human checkpoint `{request.kind.value}`."
        )
        self._events.emit(
            HumanInterventionRequested(
                timestamp=utc_now(),
                step_number=step_index,
                kind=request.kind.value,
                instruction=request.instruction,
                prompt=request.prompt,
                resume_hint=request.resume_hint,
                allowed_actions=tuple(request.allowed_actions[:12]),
            )
        )
        session.increment_step()
        self._emit_step_completed(step_index, progress_outcome.summary, report)
        return self._finish(session, report)

    def _handle_planner_failure(
        self,
        *,
        session: RuntimeSession,
        step_index: int,
        observation: AgentObservation,
        thought,
        decision: PlannerDecision,
    ) -> FinalReport:
        progress_outcome = ProgressOutcome(
            made_progress=False,
            summary="Runtime stopped because the planner could not continue safely.",
            signals=["planner returned fail"],
            no_progress_streak=session.no_progress_streak + 1,
        )
        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.FAILED,
            summary=decision.failure_reason or "Planner failed to choose a safe next step.",
            completed=False,
            actions_taken=self._actions_taken(session),
            next_steps=["Inspect the planner output and trace artifacts."],
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count + 1,
            failure_reason=decision.failure_reason,
        )
        trace_item = self.trace_recorder.record(
            step_index=step_index,
            observation=observation,
            thought=thought,
            planner_decision=decision,
            progress_outcome=progress_outcome,
            state_transition="running -> failed",
            report=report,
            notes=["Planner returned an explicit failure decision."],
        )
        session.add_trace_item(trace_item)
        report.trace_refs = self._trace_refs(session)
        report.artifact_refs = self._artifact_refs(session)
        session.record_history(f"step {step_index}: planner failed to continue safely.")
        session.register_progress(progress_outcome)
        session.increment_step()
        session.failure_reason = decision.failure_reason
        self._emit_step_completed(step_index, progress_outcome.summary, report)
        return self._finish(session, report)

    def _handle_repeated_action_stop(
        self,
        *,
        session: RuntimeSession,
        step_index: int,
        observation: AgentObservation,
        thought,
        decision: PlannerDecision,
        action: AgentAction,
    ) -> FinalReport:
        progress_outcome = ProgressOutcome(
            made_progress=False,
            summary="Runtime stopped to avoid repeating the same action without progress.",
            signals=["repeated action without progress"],
            no_progress_streak=session.no_progress_streak + 1,
        )
        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.FAILED,
            summary=(
                f"Runtime stopped because the planner repeatedly chose `{action.tool_name}` "
                "without observable progress."
            ),
            completed=False,
            actions_taken=self._actions_taken(session),
            next_steps=["Inspect the planner rationale and progress detection signals."],
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count + 1,
            failure_reason=(
                f"Repeated `{action.tool_name}` without progress. "
                "The loop stopped to avoid getting stuck."
            ),
        )
        trace_item = self.trace_recorder.record(
            step_index=step_index,
            observation=observation,
            thought=thought,
            planner_decision=decision,
            action=action,
            progress_outcome=progress_outcome,
            state_transition="running -> failed",
            report=report,
            notes=["Loop protection stopped a repeated no-progress action."],
        )
        session.add_trace_item(trace_item)
        report.trace_refs = self._trace_refs(session)
        report.artifact_refs = self._artifact_refs(session)
        session.record_history(
            f"step {step_index}: repeated `{action.tool_name}` without progress."
        )
        session.register_progress(progress_outcome)
        session.increment_step()
        session.failure_reason = report.failure_reason
        self._emit_step_completed(step_index, progress_outcome.summary, report)
        return self._finish(session, report)

    def _pause_for_confirmation(
        self,
        *,
        session: RuntimeSession,
        step_index: int,
        observation: AgentObservation,
        thought,
        decision: PlannerDecision,
        action: AgentAction,
        reason: str,
        consequences: list[str],
    ) -> FinalReport:
        session.add_action(action)
        tool_call = ToolCall(
            action_id=action.action_id,
            skill_name=action.tool_name,
            arguments=action.parameters,
        )
        session.add_tool_call(tool_call)
        request = self.confirmation_manager.build_request(
            action,
            reason=reason or decision.rationale,
            consequences=consequences,
        )
        session.set_pending_confirmation(request, action=action, decision=decision)
        tool_result = ToolResult(
            call_id=tool_call.call_id,
            skill_name=tool_call.skill_name,
            status=ToolExecutionStatus.WAITING_FOR_CONFIRMATION,
            message=reason or "Action requires explicit confirmation.",
            data={"confirmation_request": request.model_dump(mode="json")},
            duration_ms=0,
        )
        session.add_tool_result(tool_result)
        progress_outcome = ProgressOutcome(
            made_progress=False,
            summary="Execution paused pending user confirmation.",
            signals=["confirmation required"],
            no_progress_streak=session.no_progress_streak,
        )
        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.WAITING_FOR_CONFIRMATION,
            summary=(
                f"Waiting for confirmation before `{action.tool_name}` can run "
                f"(request_id={request.request_id})."
            ),
            completed=False,
            actions_taken=self._actions_taken(session),
            open_questions=[request.prompt],
            next_steps=[
                "Approve or reject the pending confirmation request in an interactive terminal.",
                "If you used --json, re-run without it or use --ui for inline Y/N prompts.",
                f"Request ID: {request.request_id}",
            ],
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count + 1,
            pending_confirmation=request,
        )
        trace_item = self.trace_recorder.record(
            step_index=step_index,
            observation=observation,
            thought=thought,
            planner_decision=decision,
            action=action,
            tool_call=tool_call,
            tool_result=tool_result,
            progress_outcome=progress_outcome,
            state_transition="running -> waiting_for_confirmation",
            report=report,
            notes=consequences or ["Safety guardrails required confirmation."],
        )
        session.add_trace_item(trace_item)
        report.trace_refs = self._trace_refs(session)
        report.artifact_refs = self._artifact_refs(session)
        session.record_history(
            f"step {step_index}: paused for confirmation before `{action.tool_name}`."
        )
        self._events.emit(
            ConfirmationRequested(
                timestamp=utc_now(),
                step_number=step_index,
                action_name=request.action_name,
                reason=truncate_text(request.reason, 320),
                prompt=request.prompt,
                consequences=tuple(request.consequences[:12]),
                risk_level=request.risk_level.value,
            )
        )
        session.increment_step()
        self._emit_step_completed(step_index, progress_outcome.summary, report)
        return self._finish(session, report)

    def _execute_action_step(
        self,
        *,
        session: RuntimeSession,
        step_index: int,
        observation_before: AgentObservation,
        decision: PlannerDecision,
        action: AgentAction,
        record_action: bool = True,
        notes: list[str] | None = None,
    ) -> FinalReport | None:
        thought = session.latest_thought or decision.to_agent_thought()
        if record_action:
            session.add_action(action)
        tool_call = ToolCall(
            action_id=action.action_id,
            skill_name=action.tool_name,
            arguments=action.parameters,
        )
        session.add_tool_call(tool_call)

        tool_result = self._execute_skill(
            action, tool_call, session, step_index=step_index
        )
        session.add_tool_result(tool_result)

        observation_after = self._extract_observation(tool_result)
        if observation_after is not None:
            session.add_observation(observation_after)
        elif tool_result.status == ToolExecutionStatus.SUCCESS and action.tool_name != "finish_task":
            observation_after = self._observe_current_page(session, step_index=step_index)
            self._emit_observation_ready(step_index, observation_after)

        if action.tool_name == "finish_task" and tool_result.status == ToolExecutionStatus.SUCCESS:
            progress_outcome = ProgressOutcome(
                made_progress=True,
                summary="Task finished through an explicit planner finish decision.",
                signals=["finish decision executed"],
                no_progress_streak=0,
            )
        else:
            progress_outcome = self.progress_detector.evaluate(
                previous_observation=observation_before,
                current_observation=observation_after or observation_before,
                tool_result=tool_result,
                planner_decision=decision,
                previous_no_progress_streak=session.no_progress_streak,
            )
        session.register_progress(progress_outcome)

        report: FinalReport | None = None
        state_transition: str | None = None
        trace_notes = list(notes or [])

        if tool_result.status == ToolExecutionStatus.ERROR:
            report = FinalReport(
                session_id=session.session_id,
                status=RuntimeStatus.FAILED,
                summary=f"Runtime failed while executing `{action.tool_name}`.",
                completed=False,
                actions_taken=self._actions_taken(session),
                next_steps=["Inspect the structured tool result and trace artifacts."],
                trace_refs=self._trace_refs(session),
                artifact_refs=self._artifact_refs(session),
                final_url=self._final_url(session),
                step_count=session.step_count + 1,
                failure_reason=tool_result.error_message or tool_result.message,
            )
            state_transition = "running -> failed"
            trace_notes.append("Execution stopped because the skill returned an error.")
            session.failure_reason = report.failure_reason
        elif action.tool_name == "finish_task":
            report = self._build_finish_report(session, tool_result, step_count=session.step_count + 1)
            state_transition = f"running -> {report.status.value}"
            session.completion_reason = report.completion_reason
        elif progress_outcome.no_progress_streak >= session.settings.max_no_progress_steps:
            report = FinalReport(
                session_id=session.session_id,
                status=RuntimeStatus.FAILED,
                summary=(
                    "Runtime stopped after multiple steps without observable progress."
                ),
                completed=False,
                actions_taken=self._actions_taken(session),
                next_steps=[
                    "Inspect the latest page state and planner rationale.",
                    "Provide a clarifying instruction or extend the skill set.",
                ],
                trace_refs=self._trace_refs(session),
                artifact_refs=self._artifact_refs(session),
                final_url=self._final_url(session),
                step_count=session.step_count + 1,
                failure_reason=progress_outcome.summary,
            )
            state_transition = "running -> failed"
            trace_notes.append("Loop protection stopped the session after stagnation.")
            session.failure_reason = report.failure_reason

        trace_item = self.trace_recorder.record(
            step_index=step_index,
            observation=observation_after or observation_before,
            thought=thought,
            planner_decision=decision,
            action=action,
            tool_call=tool_call,
            tool_result=tool_result,
            progress_outcome=progress_outcome,
            state_transition=state_transition,
            report=report,
            notes=trace_notes,
        )
        session.add_trace_item(trace_item)
        if report is not None:
            report.trace_refs = self._trace_refs(session)
            report.artifact_refs = self._artifact_refs(session)
        session.record_history(
            self._history_line(
                step_index=step_index,
                action=action,
                tool_result=tool_result,
                progress_outcome=progress_outcome,
                report=report,
            )
        )
        session.increment_step()
        self._emit_step_completed(step_index, progress_outcome.summary, report)

        if report is not None:
            return self._finish(session, report)
        return None

    def _observe_current_page(
        self, session: RuntimeSession, *, step_index: int
    ) -> AgentObservation:
        skill = self.skill_registry.get("observe_page")
        payload = skill.validate_input({})
        self._events.emit(
            SkillExecutionStarted(
                timestamp=utc_now(),
                step_number=step_index,
                skill_name="observe_page",
                target_summary=None,
            )
        )
        step_started = perf_counter()
        try:
            output_payload = skill.execute(self._context(session), payload)
        except SkillExecutionError as exc:
            duration = self._elapsed_ms(step_started)
            details = exc.data.get("details")
            detail_suffix = (
                f" Details: {details}"
                if isinstance(details, str) and details
                else ""
            )
            self._events.emit(
                SkillExecutionCompleted(
                    timestamp=utc_now(),
                    step_number=step_index,
                    skill_name="observe_page",
                    status=ToolExecutionStatus.ERROR.value,
                    message=truncate_text(f"{exc.message}{detail_suffix}", 200),
                    duration_ms=duration,
                )
            )
            raise RuntimeError(f"{exc.message}{detail_suffix}") from exc
        except Exception as exc:
            duration = self._elapsed_ms(step_started)
            message = (
                "Failed to observe the current page. "
                f"{exc.__class__.__name__}: {exc}"
            )
            self._events.emit(
                SkillExecutionCompleted(
                    timestamp=utc_now(),
                    step_number=step_index,
                    skill_name="observe_page",
                    status=ToolExecutionStatus.ERROR.value,
                    message=truncate_text(message, 200),
                    duration_ms=duration,
                )
            )
            raise RuntimeError(message) from exc

        output_data = output_payload.model_dump(mode="json")
        observation_payload = output_data.get("observation")
        if not isinstance(observation_payload, dict):
            duration = self._elapsed_ms(step_started)
            self._events.emit(
                SkillExecutionCompleted(
                    timestamp=utc_now(),
                    step_number=step_index,
                    skill_name="observe_page",
                    status=ToolExecutionStatus.ERROR.value,
                    message="Invalid observation payload.",
                    duration_ms=duration,
                )
            )
            raise RuntimeError("observe_page did not return an observation payload.")
        observation = AgentObservation.model_validate(observation_payload)
        session.add_observation(observation)
        duration = self._elapsed_ms(step_started)
        self._events.emit(
            SkillExecutionCompleted(
                timestamp=utc_now(),
                step_number=step_index,
                skill_name="observe_page",
                status=ToolExecutionStatus.SUCCESS.value,
                message="Page observed.",
                duration_ms=duration,
            )
        )
        return observation

    def _execute_skill(
        self,
        action: AgentAction,
        tool_call: ToolCall,
        session: RuntimeSession,
        *,
        step_index: int,
    ) -> ToolResult:
        step_started = perf_counter()
        target = format_tool_target(action.tool_name, action.parameters)
        self._events.emit(
            SkillExecutionStarted(
                timestamp=utc_now(),
                step_number=step_index,
                skill_name=action.tool_name,
                target_summary=target,
            )
        )
        try:
            skill = self.skill_registry.get(action.tool_name)
            payload = skill.validate_input(action.parameters)
            output_payload = skill.execute(self._context(session), payload)
            output_data = output_payload.model_dump(mode="json")
            result = ToolResult(
                call_id=tool_call.call_id,
                skill_name=tool_call.skill_name,
                status=ToolExecutionStatus.SUCCESS,
                message=self._tool_result_message(action.tool_name, output_data),
                data=output_data,
                artifacts=self._extract_artifacts(output_data),
                duration_ms=self._elapsed_ms(step_started),
            )
            self._events.emit(
                SkillExecutionCompleted(
                    timestamp=utc_now(),
                    step_number=step_index,
                    skill_name=action.tool_name,
                    status=result.status.value,
                    message=truncate_text(result.message, 240),
                    duration_ms=result.duration_ms,
                )
            )
            return result
        except SkillExecutionError as exc:
            result = ToolResult(
                call_id=tool_call.call_id,
                skill_name=tool_call.skill_name,
                status=ToolExecutionStatus.ERROR,
                message=exc.message,
                data=exc.data,
                artifacts=exc.artifacts,
                error_code=exc.error_code,
                error_message=exc.message,
                duration_ms=self._elapsed_ms(step_started),
            )
            self._events.emit(
                SkillExecutionCompleted(
                    timestamp=utc_now(),
                    step_number=step_index,
                    skill_name=action.tool_name,
                    status=result.status.value,
                    message=truncate_text(result.message, 240),
                    duration_ms=result.duration_ms,
                )
            )
            return result
        except Exception as exc:
            failure_message = (
                f"Skill `{action.tool_name}` failed: "
                f"{exc.__class__.__name__}: {exc}"
            )
            result = ToolResult(
                call_id=tool_call.call_id,
                skill_name=tool_call.skill_name,
                status=ToolExecutionStatus.ERROR,
                message=failure_message,
                error_code="skill_execution_error",
                error_message=f"{exc.__class__.__name__}: {exc}",
                duration_ms=self._elapsed_ms(step_started),
            )
            self._events.emit(
                SkillExecutionCompleted(
                    timestamp=utc_now(),
                    step_number=step_index,
                    skill_name=action.tool_name,
                    status=result.status.value,
                    message=truncate_text(result.message, 240),
                    duration_ms=result.duration_ms,
                )
            )
            return result

    def _context(self, session: RuntimeSession) -> SkillContext:
        return SkillContext(
            session=session,
            browser=self.browser,
            trace_recorder=self.trace_recorder,
            safety_guardrails=self.safety_guardrails,
            confirmation_manager=self.confirmation_manager,
        )

    def _extract_observation(self, tool_result: ToolResult) -> AgentObservation | None:
        observation_payload = tool_result.data.get("observation")
        if not isinstance(observation_payload, dict):
            return None
        return AgentObservation.model_validate(observation_payload)

    def _build_finish_report(
        self,
        session: RuntimeSession,
        tool_result: ToolResult,
        *,
        step_count: int,
    ) -> FinalReport:
        status = RuntimeStatus(tool_result.data["status"])
        summary = tool_result.data["summary"]
        return FinalReport(
            session_id=session.session_id,
            status=status,
            summary=summary,
            completed=status == RuntimeStatus.COMPLETED,
            actions_taken=self._actions_taken(session),
            open_questions=tool_result.data.get("open_questions", []),
            next_steps=tool_result.data.get("next_steps", []),
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=tool_result.data.get("final_url") or self._final_url(session),
            step_count=step_count,
            completion_reason=summary if status == RuntimeStatus.COMPLETED else None,
            failure_reason=summary if status == RuntimeStatus.FAILED else None,
        )

    def _startup_failure_report(
        self,
        session: RuntimeSession,
        exc: Exception,
    ) -> FinalReport:
        return FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.FAILED,
            summary="Runtime failed before the browser session became available.",
            completed=False,
            actions_taken=self._actions_taken(session),
            next_steps=self._startup_next_steps(exc),
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count,
            failure_reason=str(exc),
        )

    def _max_steps_report(self, session: RuntimeSession) -> FinalReport:
        return FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.STOPPED,
            summary="The runtime reached the maximum configured step count.",
            completed=False,
            actions_taken=self._actions_taken(session),
            next_steps=["Increase `max_steps` or improve progress detection."],
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count,
            failure_reason="Maximum step count reached.",
        )

    def _build_stopped_report(
        self,
        session: RuntimeSession,
        summary: str,
    ) -> FinalReport:
        return FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.STOPPED,
            summary=summary,
            completed=False,
            actions_taken=self._actions_taken(session),
            trace_refs=self._trace_refs(session),
            artifact_refs=self._artifact_refs(session),
            final_url=self._final_url(session),
            step_count=session.step_count,
        )

    def _tool_result_message(
        self,
        skill_name: str,
        output_data: dict[str, object],
    ) -> str:
        message = output_data.get("message")
        if isinstance(message, str) and message:
            return message
        if skill_name == "observe_page":
            return "Captured a structured observation of the current page."
        if skill_name == "finish_task":
            summary = output_data.get("summary")
            if isinstance(summary, str) and summary:
                return summary
        return f"Skill `{skill_name}` completed successfully."

    def _extract_artifacts(self, output_data: dict[str, object]) -> list[str]:
        artifacts: list[str] = []
        observation = output_data.get("observation")
        if isinstance(observation, dict):
            raw_refs = observation.get("artifact_refs", [])
            if isinstance(raw_refs, list):
                artifacts.extend(str(item) for item in raw_refs)
        return list(dict.fromkeys(artifacts))

    def _actions_taken(self, session: RuntimeSession) -> list[str]:
        return [action.tool_name for action in session.actions]

    def _trace_refs(self, session: RuntimeSession) -> list[str]:
        return [item.trace_id for item in session.trace_items]

    def _artifact_refs(self, session: RuntimeSession) -> list[str]:
        artifact_refs: list[str] = []
        if session.latest_observation is not None:
            artifact_refs.extend(session.latest_observation.artifact_refs)
        for result in session.tool_results:
            artifact_refs.extend(result.artifacts)
        artifact_refs.extend(self.trace_recorder.artifact_refs())
        return list(dict.fromkeys(artifact_refs))

    def _final_url(self, session: RuntimeSession) -> str | None:
        if session.latest_observation is None:
            return session.task.start_url
        return session.latest_observation.page_url

    def _startup_next_steps(self, exc: Exception) -> list[str]:
        message = str(exc)
        if "playwright install" in message.lower() or "executable doesn't exist" in message.lower():
            return [
                "Run `python -m playwright install chromium` (same Python as pipx uses).",
                "Or run: browser-agent setup",
                "Retry the CLI after the browser runtime is available.",
            ]
        return [
            "Inspect the browser startup error details.",
            "Retry after fixing the local Playwright environment.",
        ]

    def _elapsed_ms(self, started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)

    def _is_repeated_action_without_progress(
        self,
        action: AgentAction,
        session: RuntimeSession,
    ) -> bool:
        if session.no_progress_streak == 0 or len(session.actions) < 2:
            return False
        recent = session.actions[-2:]
        return all(
            previous.tool_name == action.tool_name
            and previous.parameters == action.parameters
            for previous in recent
        )

    def _is_repetitive_exploration_loop(
        self,
        *,
        action: AgentAction,
        session: RuntimeSession,
        current_observation: AgentObservation,
    ) -> bool:
        if action.tool_name not in self._EXPLORATION_SKILLS:
            return False

        recent_actions = [item.tool_name for item in session.actions[-5:]] + [action.tool_name]
        if len(recent_actions) < 6:
            return False
        if any(name not in self._EXPLORATION_SKILLS for name in recent_actions):
            return False
        if "scroll_viewport" not in recent_actions or "extract_page_text" not in recent_actions:
            return False

        recent_urls = [item.current_url for item in session.trace_items[-5:] if item.current_url]
        if len(recent_urls) < 5:
            return False
        if len(set(recent_urls + [current_observation.page_url])) != 1:
            return False

        if session.no_progress_streak >= 2:
            return True

        recent_trace_items = session.trace_items[-5:]
        return all(
            self._is_weak_exploration_progress(item) for item in recent_trace_items
        )

    def _is_weak_exploration_progress(self, trace_item) -> bool:
        progress_outcome = getattr(trace_item, "progress_outcome", None)
        action_name = getattr(trace_item, "action_name", None)
        if progress_outcome is None or action_name not in self._EXPLORATION_SKILLS:
            return False
        signals = set(progress_outcome.signals or [])
        if not signals:
            return True
        return signals.issubset(self._WEAK_EXPLORATION_PROGRESS_SIGNALS)

    def _decide_with_runtime_validation(
        self,
        *,
        session: RuntimeSession,
        observation: AgentObservation,
    ) -> PlannerDecision:
        planner_context = session.build_planner_context(
            available_skills=self.available_skills,
        )

        for attempt in range(self._MAX_PLANNER_REPLAN_ATTEMPTS + 1):
            decision = self._planner_decision_with_fallback(planner_context)
            validated_decision = self._validate_runtime_decision(
                decision,
                observation,
                session=session,
            )
            if not self._is_recoverable_validation_failure(validated_decision):
                return validated_decision

            reason = (
                validated_decision.failure_reason
                or "Planner targeting validation failed."
            )
            auto_finish_decision = self._maybe_finish_after_validation_failure(
                session=session,
                observation=observation,
                reason=reason,
            )
            if auto_finish_decision is not None:
                session.record_history(
                    "Runtime validation determined the current page already has enough "
                    "evidence; converting the rejected planner action into finish. "
                    f"Reason: {reason}"
                )
                return auto_finish_decision
            session.record_history(
                "Planner decision was rejected by runtime validation; requesting "
                f"replan ({attempt + 1}/{self._MAX_PLANNER_REPLAN_ATTEMPTS + 1}). "
                f"Reason: {reason}"
            )
            if attempt >= self._MAX_PLANNER_REPLAN_ATTEMPTS:
                return PlannerDecision.safe_fail(
                    (
                        "Planner kept producing invalid element targeting after "
                        f"{attempt + 1} attempts. Last issue: {reason}"
                    ),
                    rationale=self._RECOVERABLE_VALIDATION_RATIONALE,
                )

            planner_context = planner_context.model_copy(
                update={
                    "trace_summary": [
                        *planner_context.trace_summary,
                        (
                            "Runtime validation rejected the previous planner action: "
                            f"{reason}"
                        ),
                        "Choose a different action or use the observed element_id.",
                    ]
                }
            )

        return PlannerDecision.safe_fail(
            "Planner could not produce a valid action after runtime validation.",
        )

    def _maybe_finish_after_validation_failure(
        self,
        *,
        session: RuntimeSession,
        observation: AgentObservation,
        reason: str,
    ) -> PlannerDecision | None:
        reason_lower = reason.lower()
        if "enough extracted evidence to answer" in reason_lower:
            return self._auto_finish_with_collected_evidence(
                session=session,
                observation=observation,
            )
        if (
            "multiple price or value mentions" in reason_lower
            and self._task_looks_information_seeking(session.task.request)
            and self._has_same_page_rich_price_evidence(session, observation)
        ):
            return self._auto_finish_with_collected_evidence(
                session=session,
                observation=observation,
            )
        if (
            "non-truncated page text was already extracted from the same page" in reason_lower
            and self._task_looks_information_seeking(session.task.request)
            and self._has_same_page_rich_price_evidence(session, observation)
        ):
            return self._auto_finish_with_collected_evidence(
                session=session,
                observation=observation,
            )
        return None

    def _auto_finish_with_collected_evidence(
        self,
        *,
        session: RuntimeSession,
        observation: AgentObservation,
    ) -> PlannerDecision:
        return PlannerDecision(
            decision_type=PlannerDecisionType.FINISH,
            rationale=(
                "Runtime validation determined that the current page already contains "
                "enough evidence to answer honestly, so it is assembling the final "
                "user-facing response from the evidence already collected."
            ),
            finish_reason=self._build_auto_finish_summary(
                session=session,
                observation=observation,
            ),
            completion_confidence=0.9,
            progress_assessment=PlannerProgressState.SUBSTANTIAL_PROGRESS,
        )

    def _build_auto_finish_summary(
        self,
        *,
        session: RuntimeSession,
        observation: AgentObservation,
    ) -> str:
        prefers_russian = self._task_prefers_russian(session.task.request)
        findings = self._collected_evidence_snippets(session, observation)
        actions = self._describe_completed_actions(
            session,
            prefers_russian=prefers_russian,
        )
        source_url = observation.page_url or self._final_url(session)
        page_title = " ".join((observation.page_title or "").split()).strip()

        if prefers_russian:
            found_text = (
                "; ".join(findings)
                if findings
                else self._fallback_evidence_summary(observation, prefers_russian=True)
            )
            lines = [f"Что нашел: {found_text}."]
            if actions:
                lines.append(f"Что сделал: {', '.join(actions)}.")
            if page_title and source_url:
                lines.append(f"Источник: {page_title} - {source_url}.")
            elif source_url:
                lines.append(f"Источник: {source_url}.")
            elif page_title:
                lines.append(f"Источник: {page_title}.")
            return "\n".join(lines)

        found_text = (
            "; ".join(findings)
            if findings
            else self._fallback_evidence_summary(observation, prefers_russian=False)
        )
        lines = [f"Found: {found_text}."]
        if actions:
            lines.append(f"Did: {', '.join(actions)}.")
        if page_title and source_url:
            lines.append(f"Source: {page_title} - {source_url}.")
        elif source_url:
            lines.append(f"Source: {source_url}.")
        elif page_title:
            lines.append(f"Source: {page_title}.")
        return "\n".join(lines)

    def _collected_evidence_snippets(
        self,
        session: RuntimeSession,
        observation: AgentObservation,
        *,
        limit: int = 4,
    ) -> list[str]:
        planner_state = session.planner_state()
        candidate_sources: list[str] = []

        extracted_text = (planner_state.latest_extracted_text or "").strip()
        if extracted_text:
            candidate_sources.append(extracted_text)

        visible_text = (observation.visible_text_excerpt or "").strip()
        if visible_text:
            candidate_sources.append(visible_text)

        observation_summary = (observation.summary or "").strip()
        if observation_summary:
            candidate_sources.append(observation_summary)

        for source_text in candidate_sources:
            snippets = self._extract_evidence_snippets(source_text, limit=limit)
            if snippets:
                return snippets

        return []

    def _extract_evidence_snippets(self, text: str, *, limit: int = 4) -> list[str]:
        import re

        if not text.strip():
            return []

        parts = [
            " ".join(part.split()).strip(" -•\t\r\n")
            for part in re.split(r"(?:[\r\n]+|(?<=[.!?])\s+)", text)
        ]
        parts = [part for part in parts if part]

        snippets: list[str] = []
        for part in parts:
            if self._count_currency_mentions(part) <= 0:
                continue
            cleaned = truncate_text(part.rstrip(" .;:,"), 140)
            if cleaned and cleaned not in snippets:
                snippets.append(cleaned)
            if len(snippets) >= limit:
                return snippets

        if snippets:
            return snippets

        normalized = " ".join(text.split()).strip()
        if not normalized:
            return []
        return [truncate_text(normalized.rstrip(" .;:,"), 180)]

    def _fallback_evidence_summary(
        self,
        observation: AgentObservation,
        *,
        prefers_russian: bool,
    ) -> str:
        source_text = (
            (observation.summary or "").strip()
            or (observation.visible_text_excerpt or "").strip()
        )
        if source_text:
            return truncate_text(" ".join(source_text.split()).rstrip(" .;:,"), 180)
        if prefers_russian:
            return "на текущей странице уже хватало данных для честного ответа"
        return "the current page already contained enough evidence to answer honestly"

    def _describe_completed_actions(
        self,
        session: RuntimeSession,
        *,
        prefers_russian: bool,
    ) -> list[str]:
        action_map_en = {
            "navigate": "opened the relevant page",
            "click_element": "used a page control to open the relevant section",
            "extract_page_text": "read the page text",
            "get_interactive_elements": "checked the visible controls",
            "observe_page": "inspected the current page",
            "scroll_viewport": "scanned the page content",
            "type_text": "entered text into the page",
            "select_option": "selected a page option",
            "wait_for_element": "waited for the relevant page state",
        }
        action_map_ru = {
            "navigate": "открыл нужную страницу",
            "click_element": "перешел через элемент на странице к нужному разделу",
            "extract_page_text": "считал текст страницы",
            "get_interactive_elements": "проверил видимые элементы управления",
            "observe_page": "осмотрел текущую страницу",
            "scroll_viewport": "просмотрел содержимое страницы",
            "type_text": "ввел текст на странице",
            "select_option": "выбрал опцию на странице",
            "wait_for_element": "дождался нужного состояния страницы",
        }
        action_map = action_map_ru if prefers_russian else action_map_en

        described: list[str] = []
        seen: set[str] = set()
        for action in session.actions:
            if action.tool_name == "finish_task":
                continue
            phrase = action_map.get(action.tool_name)
            if phrase is None:
                phrase = (
                    f"выполнил шаг `{action.tool_name}`"
                    if prefers_russian
                    else f"executed `{action.tool_name}`"
                )
            if phrase in seen:
                continue
            seen.add(phrase)
            described.append(phrase)
        return described[-4:]

    def _task_prefers_russian(self, request: str) -> bool:
        return any("\u0400" <= char <= "\u04ff" for char in request)

    def _planner_decision_with_fallback(self, planner_context) -> PlannerDecision:
        try:
            return self.planner.decide(planner_context)
        except Exception as exc:
            return PlannerDecision.safe_fail(
                f"Planner raised an unexpected exception: {exc}"
            )

    def _is_recoverable_validation_failure(self, decision: PlannerDecision) -> bool:
        return (
            decision.decision_type == PlannerDecisionType.FAIL
            and decision.rationale == self._RECOVERABLE_VALIDATION_RATIONALE
        )

    def _recoverable_validation_fail(self, reason: str) -> PlannerDecision:
        return PlannerDecision.safe_fail(
            reason,
            rationale=self._RECOVERABLE_VALIDATION_RATIONALE,
        )

    def _validate_runtime_decision(
        self,
        decision: PlannerDecision,
        observation: AgentObservation | None,
        *,
        session: RuntimeSession | None = None,
    ) -> PlannerDecision:
        decision = self._validate_element_targeting(
            decision,
            observation,
            session=session,
        )
        if self._is_recoverable_validation_failure(decision):
            return decision
        decision = self._validate_redundant_information_refinement(
            decision,
            observation,
            session=session,
        )
        if self._is_recoverable_validation_failure(decision):
            return decision
        return self._validate_redundant_exploration(
            decision,
            observation,
            session=session,
        )

    def _validate_element_targeting(
        self,
        decision: PlannerDecision,
        observation: AgentObservation | None,
        *,
        session: RuntimeSession | None = None,
    ) -> PlannerDecision:
        """Validate that element targeting follows the policy.

        Rejects decisions that:
        1. Use raw selector when element_id is available in observation
        2. Use ambiguous selectors that match multiple elements
        """
        if decision.decision_type not in {
            PlannerDecisionType.ACT,
            PlannerDecisionType.REQUEST_CONFIRMATION,
        }:
            return decision

        if not decision.chosen_skill:
            return decision

        if decision.chosen_skill not in {
            "click_element",
            "type_text",
            "select_option",
            "press_key",
            "upload_file",
        }:
            return decision

        skill_input = decision.skill_input or {}
        element_id = skill_input.get("element_id")
        selector = skill_input.get("selector")

        if element_id:
            if (
                decision.chosen_skill == "click_element"
                and observation is not None
                and session is not None
            ):
                target_element = self._find_observed_element_by_id(observation, str(element_id))
                if target_element and self._is_redundant_reading_click(
                    decision,
                    observation,
                    target_element,
                    session,
                ):
                    return self._recoverable_validation_fail(
                        "Redundant click on a navigation-like element after the page text "
                        "was already extracted from the same page. Prefer finishing, "
                        "summarizing, or a different non-click action."
                    )
            return decision

        # No selector provided either - let skill validation handle this
        if not selector:
            return decision

        # Using raw selector without element_id - validate against observation
        if observation:
            # Check if this is a generic text selector that matches observed elements
            if self._looks_like_generic_text_selector(selector):
                for element in observation.interactive_elements:
                    if self._selector_matches_element(selector, element):
                        # This selector matches an element that has an element_id
                        # The planner should have used element_id
                        return self._recoverable_validation_fail(
                            f"Targeting policy violation: raw selector '{selector}' "
                            f"matches observed element {element.element_id} but element_id was not used. "
                            f"When an element is in the observation, always use its element_id."
                        )

            # Check for ambiguity (selector matches multiple elements)
            matching_count = self._count_matching_observed_elements(selector, observation)
            if matching_count > 1:
                return self._recoverable_validation_fail(
                    f"Ambiguous target: selector '{selector}' matches {matching_count} elements "
                    f"in the observation. Use element_id for precise targeting."
                )

        return decision

    def _validate_redundant_exploration(
        self,
        decision: PlannerDecision,
        observation: AgentObservation | None,
        *,
        session: RuntimeSession | None = None,
    ) -> PlannerDecision:
        if decision.decision_type not in {
            PlannerDecisionType.ACT,
            PlannerDecisionType.REQUEST_CONFIRMATION,
        }:
            return decision
        if decision.chosen_skill not in {
            "scroll_viewport",
            "extract_page_text",
            "get_interactive_elements",
            "observe_page",
        }:
            return decision
        if observation is None or session is None:
            return decision

        planner_state = session.planner_state()
        if (
            decision.chosen_skill in {"get_interactive_elements", "observe_page"}
            and planner_state.latest_action_name == decision.chosen_skill
            and planner_state.latest_url == observation.page_url
            and planner_state.latest_tool_status == ToolExecutionStatus.SUCCESS
        ):
            return self._recoverable_validation_fail(
                f"The current observation already includes the result of the most recent "
                f"`{decision.chosen_skill}` call on this page. Do not repeat the same "
                "read-only inspection step without a new interaction."
            )

        extracted_text = (planner_state.latest_extracted_text or "").strip()
        if not extracted_text or planner_state.latest_extracted_text_truncated is True:
            return decision
        if (
            planner_state.latest_extracted_text_url
            and planner_state.latest_extracted_text_url != observation.page_url
        ):
            return decision

        if decision.chosen_skill == "extract_page_text":
            if len(extracted_text) < 1500:
                return decision
            return self._recoverable_validation_fail(
                "Non-truncated page text was already extracted from the same page. "
                "Prefer finishing with the evidence already collected, or use a "
                "different interaction only when new content is clearly hidden."
            )

        if self._count_currency_mentions(extracted_text) >= 4:
            return self._recoverable_validation_fail(
                "Non-truncated page text from the same page already contains "
                "multiple price or value mentions. Do not keep scrolling a "
                "read-only listing without new evidence; prefer finishing with "
                "the collected evidence or choosing a genuinely different action."
            )

        return decision

    def _validate_redundant_information_refinement(
        self,
        decision: PlannerDecision,
        observation: AgentObservation | None,
        *,
        session: RuntimeSession | None = None,
    ) -> PlannerDecision:
        if decision.decision_type not in {
            PlannerDecisionType.ACT,
            PlannerDecisionType.REQUEST_CONFIRMATION,
        }:
            return decision
        if decision.chosen_skill not in {"click_element", "type_text", "select_option"}:
            return decision
        if observation is None or session is None:
            return decision
        if not self._task_looks_information_seeking(session.task.request):
            return decision
        if not self._has_same_page_rich_price_evidence(session, observation):
            return decision

        target_context = self._describe_interaction_target(
            decision=decision,
            observation=observation,
        )
        if not target_context:
            return decision

        if (
            decision.chosen_skill == "type_text"
            and self._looks_like_search_or_filter_entry(target_context)
        ):
            return self._recoverable_validation_fail(
                "The current page already contains enough extracted evidence to answer "
                "the information request. Do not use a search or filter input on the "
                "same listing just to refine the results; prefer finishing with the "
                "evidence already collected."
            )

        if self._looks_like_listing_refinement_control(target_context):
            return self._recoverable_validation_fail(
                "The current page already contains enough extracted evidence to answer "
                "the information request. Do not click sort, filter, or search "
                "refinement controls on the same listing; prefer finishing with the "
                "evidence already collected."
            )

        return decision

    def _count_currency_mentions(self, text: str) -> int:
        import re

        patterns = (
            r"(?<!\d)\d{1,3}(?:[ \u00a0]\d{3})*(?:[.,]\d{2})?\s*[₽$€£](?!\w)",
            r"(?<!\d)\d{1,3}(?:[ \u00a0]\d{3})*(?:[.,]\d{2})?\s*(?:руб\.?|рублей|р\.)(?!\w)",
        )
        total = 0
        for pattern in patterns:
            total += len(re.findall(pattern, text, flags=re.IGNORECASE))
        return total

    def _find_observed_element_by_id(
        self,
        observation: AgentObservation,
        element_id: str,
    ) -> InteractiveElement | None:
        for element in observation.interactive_elements:
            if element.element_id == element_id:
                return element
        return None

    def _is_redundant_reading_click(
        self,
        decision: PlannerDecision,
        observation: AgentObservation,
        element: InteractiveElement,
        session: RuntimeSession,
    ) -> bool:
        planner_state = session.planner_state()
        if planner_state.latest_action_name == "scroll_viewport":
            return False
        extracted_text = (planner_state.latest_extracted_text or "").strip()
        if not extracted_text or planner_state.latest_extracted_text_truncated is True:
            return False
        if len(extracted_text) < 1200:
            return False
        if (
            planner_state.latest_extracted_text_url
            and planner_state.latest_extracted_text_url != observation.page_url
        ):
            return False

        role = (element.role or "").lower()
        tag = (element.tag or "").lower()
        if role not in {"link", "button"} and tag not in {"a", "button"}:
            return False

        label = " ".join((element.text or element.label or "").split()).strip()
        if len(label) < 4:
            return False
        label_lower = label.lower()
        if any(token in label_lower for token in ("http://", "https://", "www.")):
            return False
        if "." in label_lower and any(ch.isalpha() for ch in label_lower):
            if " " not in label_lower or "+" in label_lower:
                return False
        href = str(element.attributes.get("href", "") or "").strip().lower()
        if href and not href.startswith(("#", "javascript:")):
            return False

        rationale_text = (
            f"{decision.rationale or ''} {decision.expected_outcome or ''}"
        ).lower()
        reveal_keywords = (
            "expand",
            "expanded",
            "accordion",
            "toggle",
            "reveal",
            "show more",
            "раскры",
            "развер",
            "скрыт",
            "показат",
            "аккордеон",
        )
        if any(keyword in rationale_text for keyword in reveal_keywords):
            return False

        reading_keywords = (
            "read",
            "reading",
            "continue reading",
            "document",
            "page text",
            "same page",
            "summarize",
            "inspect the text",
            "прочит",
            "чтени",
            "текст",
            "документ",
            "страниц",
            "суммари",
        )
        if not any(keyword in rationale_text for keyword in reading_keywords):
            return False

        text_lower = extracted_text.lower()
        title_lower = " ".join((observation.page_title or "").split()).strip().lower()
        if label_lower == title_lower:
            return True
        return label_lower in text_lower

    def _task_looks_information_seeking(self, request: str) -> bool:
        request_lower = request.lower()
        info_keywords = (
            "find",
            "look up",
            "show",
            "list",
            "compare",
            "which",
            "what",
            "review",
            "inspect",
            "глянь",
            "найд",
            "поищ",
            "посмотр",
            "покаж",
            "спис",
            "сравн",
            "какие",
            "какой",
            "что",
            "сколько",
            "до ",
            "under ",
            "budget",
            "cheapest",
            "price",
            "цена",
            "дешев",
        )
        return any(keyword in request_lower for keyword in info_keywords)

    def _has_same_page_rich_price_evidence(
        self,
        session: RuntimeSession,
        observation: AgentObservation,
    ) -> bool:
        planner_state = session.planner_state()
        extracted_text = (planner_state.latest_extracted_text or "").strip()
        if not extracted_text or planner_state.latest_extracted_text_truncated is True:
            return False
        if (
            planner_state.latest_extracted_text_url
            and planner_state.latest_extracted_text_url != observation.page_url
        ):
            return False
        return self._count_currency_mentions(extracted_text) >= 3

    def _describe_interaction_target(
        self,
        *,
        decision: PlannerDecision,
        observation: AgentObservation,
    ) -> str:
        skill_input = decision.skill_input or {}
        parts: list[str] = []

        element_id = skill_input.get("element_id")
        if isinstance(element_id, str) and element_id:
            element = self._find_observed_element_by_id(observation, element_id)
            if element is not None:
                parts.extend(
                    [
                        element.label,
                        element.text or "",
                        element.aria_label or "",
                        element.placeholder or "",
                        element.selector,
                    ]
                )

        field_id = skill_input.get("field_id")
        if isinstance(field_id, str) and field_id:
            field = self._find_observed_field_by_id(observation, field_id)
            if field is not None:
                parts.extend(
                    [
                        field.label or "",
                        field.name or "",
                        field.placeholder or "",
                        field.selector,
                    ]
                )

        selector = skill_input.get("selector")
        if isinstance(selector, str) and selector:
            parts.append(selector)
            field = self._find_observed_field_by_selector(observation, selector)
            if field is not None:
                parts.extend(
                    [
                        field.label or "",
                        field.name or "",
                        field.placeholder or "",
                    ]
                )

        option_text = skill_input.get("option_text")
        option_value = skill_input.get("option_value")
        if isinstance(option_text, str) and option_text:
            parts.append(option_text)
        if isinstance(option_value, str) and option_value:
            parts.append(option_value)

        parts.extend([decision.rationale or "", decision.expected_outcome or ""])
        return " ".join(part for part in parts if part).lower()

    def _find_observed_field_by_id(
        self,
        observation: AgentObservation,
        field_id: str,
    ):
        for field in observation.form_fields:
            if field.field_id == field_id:
                return field
        return None

    def _find_observed_field_by_selector(
        self,
        observation: AgentObservation,
        selector: str,
    ):
        for field in observation.form_fields:
            if field.selector == selector:
                return field
        return None

    def _looks_like_search_or_filter_entry(self, text: str) -> bool:
        keywords = (
            "search",
            "find",
            "query",
            "filter",
            "искать",
            "поиск",
            "найти",
            "фильтр",
        )
        return any(keyword in text for keyword in keywords)

    def _looks_like_listing_refinement_control(self, text: str) -> bool:
        keywords = (
            "search",
            "find",
            "query",
            "filter",
            "sort",
            "price",
            "best price",
            "low to high",
            "high to low",
            "cheap",
            "cheapest",
            "искать",
            "поиск",
            "найти",
            "фильтр",
            "сорт",
            "цена",
            "лучшая цена",
            "дешев",
            "дорог",
            "новин",
            "популяр",
        )
        return any(keyword in text for keyword in keywords)

    def _looks_like_generic_text_selector(self, selector: str) -> bool:
        """Check if selector appears to be a generic text-based selector."""
        import re

        selector_lower = selector.lower().strip()

        # text="..." patterns
        if re.match(r'^text=["\']', selector_lower):
            return True

        # role=... patterns without specific name
        if selector_lower.startswith("role=") and "name=" not in selector_lower:
            return True

        return False

    def _selector_matches_element(
        self,
        selector: str,
        element: InteractiveElement,
    ) -> bool:
        """Check if a text-based selector likely matches an element."""
        import re

        selector_lower = selector.lower()
        element_text = (element.text or "").lower()
        element_label = (element.label or "").lower()

        # Extract text from text="..." pattern
        match = re.search(r'text=["\'](.+?)["\']', selector, re.IGNORECASE)
        if match:
            search_text = match.group(1).lower()
            return search_text in element_text or search_text in element_label

        # For non-text selectors, check if selector is contained in element identifiers
        if selector_lower in element_text or selector_lower in element_label:
            return True

        return False

    def _count_matching_observed_elements(
        self,
        selector: str,
        observation: AgentObservation,
    ) -> int:
        """Count how many observed elements match the selector."""
        import re

        count = 0

        match = re.search(r'text=["\'](.+?)["\']', selector, re.IGNORECASE)
        if not match:
            return 0

        search_text = match.group(1).lower()

        for element in observation.interactive_elements:
            element_text = (element.text or "").lower()
            element_label = (element.label or "").lower()
            if search_text in element_text or search_text in element_label:
                count += 1

        return count

    def _history_line(
        self,
        *,
        step_index: int,
        action: AgentAction,
        tool_result: ToolResult,
        progress_outcome: ProgressOutcome,
        report: FinalReport | None,
    ) -> str:
        status = tool_result.status.value
        parts = [
            f"step {step_index}",
            f"action={action.tool_name}",
            f"status={status}",
            f"progress={'yes' if progress_outcome.made_progress else 'no'}",
        ]
        if report is not None:
            parts.append(f"session={report.status.value}")
        return " | ".join(parts)
