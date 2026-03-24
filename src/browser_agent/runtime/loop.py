"""Runtime orchestration loop for the browser agent foundation."""

from __future__ import annotations

from browser_agent.browser.engine import BrowserEngine
from browser_agent.llm.planner import Planner
from browser_agent.runtime.models import (
    AgentAction,
    AgentObservation,
    FinalReport,
    RuntimeStatus,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
)
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.base import SkillContext
from browser_agent.skills.registry import SkillRegistry


class RuntimeLoop:
    """Coordinate planning, safety checks, skill execution, and reporting."""

    def __init__(
        self,
        *,
        planner: Planner,
        skill_registry: SkillRegistry,
        browser: BrowserEngine,
        safety_guardrails: SafetyGuardrails,
        confirmation_manager: ConfirmationManager,
        trace_recorder: TraceRecorder,
    ) -> None:
        self.planner = planner
        self.skill_registry = skill_registry
        self.browser = browser
        self.safety_guardrails = safety_guardrails
        self.confirmation_manager = confirmation_manager
        self.trace_recorder = trace_recorder

    def run(self, session: RuntimeSession) -> FinalReport:
        """Execute the runtime loop until completion or a controlled stop."""

        session.start()
        self.browser.start()

        for step_index in range(session.settings.max_steps):
            decision = self.planner.decide(session.summary())
            session.add_thought(decision.thought)

            if decision.user_question:
                report = FinalReport(
                    session_id=session.session_id,
                    status=RuntimeStatus.WAITING_FOR_USER,
                    summary="The runtime requires more information from the user.",
                    completed=False,
                    actions_taken=self._actions_taken(session),
                    open_questions=[decision.user_question],
                    trace_refs=self._trace_refs(session),
                    final_url=self._final_url(session),
                )
                return session.complete(report)

            action = decision.action
            if action is None:
                report = FinalReport(
                    session_id=session.session_id,
                    status=RuntimeStatus.STOPPED,
                    summary="Planner returned no next action.",
                    completed=False,
                    actions_taken=self._actions_taken(session),
                    trace_refs=self._trace_refs(session),
                    final_url=self._final_url(session),
                )
                return session.complete(report)

            if self._is_repeated_action(action, session):
                report = FinalReport(
                    session_id=session.session_id,
                    status=RuntimeStatus.STOPPED,
                    summary=(
                        "The runtime stopped to avoid repeating the same action "
                        "without progress."
                    ),
                    completed=False,
                    actions_taken=self._actions_taken(session),
                    next_steps=[
                        "Inspect the planner output and browser state transition logic."
                    ],
                    trace_refs=self._trace_refs(session),
                    final_url=self._final_url(session),
                )
                return session.complete(report)

            session.add_action(action)
            tool_call = ToolCall(
                action_id=action.action_id,
                skill_name=action.tool_name,
                arguments=action.parameters,
            )
            session.add_tool_call(tool_call)

            guardrail_decision = self.safety_guardrails.classify_action(action)
            if guardrail_decision.requires_confirmation:
                request = self.confirmation_manager.build_request(
                    action,
                    reason=guardrail_decision.reason,
                    consequences=guardrail_decision.matched_signals,
                )
                session.set_pending_confirmation(request)
                tool_result = ToolResult(
                    call_id=tool_call.call_id,
                    skill_name=tool_call.skill_name,
                    status=ToolExecutionStatus.WAITING_FOR_CONFIRMATION,
                    message=guardrail_decision.reason,
                    data={"confirmation_request": request.model_dump(mode="json")},
                )
                session.add_tool_result(tool_result)
                trace_item = self.trace_recorder.record(
                    step_index=step_index,
                    observation=session.latest_observation,
                    thought=decision.thought,
                    action=action,
                    tool_call=tool_call,
                    tool_result=tool_result,
                    notes=guardrail_decision.matched_signals,
                )
                session.add_trace_item(trace_item)
                report = FinalReport(
                    session_id=session.session_id,
                    status=RuntimeStatus.WAITING_FOR_USER,
                    summary=(
                        f"Waiting for confirmation before `{action.tool_name}` can run."
                    ),
                    completed=False,
                    actions_taken=self._actions_taken(session),
                    open_questions=[request.prompt],
                    next_steps=["Approve or reject the pending confirmation request."],
                    trace_refs=self._trace_refs(session),
                    final_url=self._final_url(session),
                )
                return session.complete(report)

            try:
                skill = self.skill_registry.get(action.tool_name)
                payload = skill.validate_input(action.parameters)
                output_payload = skill.execute(self._context(session), payload)
                tool_result = ToolResult(
                    call_id=tool_call.call_id,
                    skill_name=tool_call.skill_name,
                    status=ToolExecutionStatus.SUCCESS,
                    message=f"Skill `{action.tool_name}` completed successfully.",
                    data=output_payload.model_dump(mode="json"),
                )
            except Exception as exc:
                tool_result = ToolResult(
                    call_id=tool_call.call_id,
                    skill_name=tool_call.skill_name,
                    status=ToolExecutionStatus.ERROR,
                    message=f"Skill `{action.tool_name}` failed.",
                    error_code="skill_execution_error",
                    error_message=str(exc),
                )
                session.add_tool_result(tool_result)
                trace_item = self.trace_recorder.record(
                    step_index=step_index,
                    observation=session.latest_observation,
                    thought=decision.thought,
                    action=action,
                    tool_call=tool_call,
                    tool_result=tool_result,
                    notes=["Execution stopped because a skill raised an exception."],
                )
                session.add_trace_item(trace_item)
                report = FinalReport(
                    session_id=session.session_id,
                    status=RuntimeStatus.FAILED,
                    summary=f"Runtime failed while executing `{action.tool_name}`.",
                    completed=False,
                    actions_taken=self._actions_taken(session),
                    next_steps=["Inspect the tool result error and trace item."],
                    trace_refs=self._trace_refs(session),
                    final_url=self._final_url(session),
                )
                return session.complete(report)

            session.add_tool_result(tool_result)
            observation = self._extract_observation(tool_result)
            if observation is not None:
                session.add_observation(observation)

            trace_item = self.trace_recorder.record(
                step_index=step_index,
                observation=observation or session.latest_observation,
                thought=decision.thought,
                action=action,
                tool_call=tool_call,
                tool_result=tool_result,
            )
            session.add_trace_item(trace_item)

            if action.tool_name == "finish_task":
                return session.complete(self._build_finish_report(session, tool_result))

        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.STOPPED,
            summary="The runtime reached the maximum configured step count.",
            completed=False,
            actions_taken=self._actions_taken(session),
            next_steps=["Increase `max_steps` or improve progress detection."],
            trace_refs=self._trace_refs(session),
            final_url=self._final_url(session),
        )
        return session.complete(report)

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
        if not observation_payload:
            return None
        return AgentObservation.model_validate(observation_payload)

    def _build_finish_report(
        self,
        session: RuntimeSession,
        tool_result: ToolResult,
    ) -> FinalReport:
        status = RuntimeStatus(tool_result.data["status"])
        return FinalReport(
            session_id=session.session_id,
            status=status,
            summary=tool_result.data["summary"],
            completed=status == RuntimeStatus.COMPLETED,
            actions_taken=self._actions_taken(session),
            open_questions=tool_result.data.get("open_questions", []),
            next_steps=tool_result.data.get("next_steps", []),
            trace_refs=self._trace_refs(session),
            final_url=self._final_url(session),
        )

    def _actions_taken(self, session: RuntimeSession) -> list[str]:
        return [action.tool_name for action in session.actions]

    def _trace_refs(self, session: RuntimeSession) -> list[str]:
        return [item.trace_id for item in session.trace_items]

    def _final_url(self, session: RuntimeSession) -> str | None:
        if session.latest_observation is None:
            return session.task.start_url
        return session.latest_observation.page_url

    def _is_repeated_action(
        self,
        action: AgentAction,
        session: RuntimeSession,
    ) -> bool:
        if len(session.actions) < 2:
            return False
        recent = session.actions[-2:]
        return all(
            previous.tool_name == action.tool_name
            and previous.parameters == action.parameters
            for previous in recent
        )
