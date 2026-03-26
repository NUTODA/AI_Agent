"""Terminal-style CLI for the browser agent runtime."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from browser_agent.browser.engine import PlaywrightBrowserEngine
from browser_agent.config import RuntimeSettings
from browser_agent.llm.parser import PlannerResponseParser
from browser_agent.llm.planner import LLMPlanner
from browser_agent.llm.provider import (
    GoogleGenerativeLanguageProvider,
    OpenAICompatibleProvider,
    TrackingLLMProvider,
)
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import FinalReport, RuntimeStatus, UserTask
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationDecision, ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="browser-agent",
        description=(
            "Run the browser agent multi-step runtime. "
            "Use --ui for the Rich Agent Console (live phases, steps, tokens, confirmations)."
        ),
    )
    parser.add_argument("task", nargs="?", help="Natural-language task to run.")
    parser.add_argument("--start-url", help="Optional starting URL for the session.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum runtime steps before the loop stops.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Render the final report as JSON.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Launch the browser with a visible window.",
    )
    parser.add_argument(
        "--capture-screenshots",
        action="store_true",
        help="Capture one screenshot artifact at each observation point.",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help=(
            "Rich Agent Console: live layout with phases (OBSERVE/PLAN/ACT/…), "
            "human-readable status, step cards, token/cost panel, and inline Y/N confirmations. "
            "Incompatible with --json."
        ),
    )
    return parser


def build_browser_engine(settings: RuntimeSettings) -> PlaywrightBrowserEngine:
    """Create the real browser adapter used by the CLI runtime."""

    return PlaywrightBrowserEngine(
        headless=settings.headless,
        default_timeout_ms=settings.default_timeout_ms,
        max_text_chars=settings.max_text_chars,
        artifact_dir=settings.artifact_dir,
        capture_screenshots=settings.capture_screenshots,
    )


def render_text_report(report: FinalReport, *, session: RuntimeSession | None = None) -> str:
    """Format a demo-readable terminal summary."""

    # Status indicator
    status_emoji = ""
    if report.status == RuntimeStatus.COMPLETED:
        status_emoji = ""
    elif report.status == RuntimeStatus.FAILED:
        status_emoji = ""
    elif report.status == RuntimeStatus.STOPPED:
        status_emoji = ""
    elif report.status in (RuntimeStatus.WAITING_FOR_CONFIRMATION, RuntimeStatus.WAITING_FOR_USER):
        status_emoji = ""

    lines = [
        "",
        "╔══════════════════════════════════════════════════════════════╗",
        "║                    BROWSER AGENT RESULT                      ║",
        "╚══════════════════════════════════════════════════════════════╝",
        "",
    ]

    # Status block
    lines.append(f"Status:   {status_emoji} {report.status.value.upper()}")
    lines.append(f"Outcome:  {'Completed' if report.completed else 'Incomplete'}")
    lines.append(f"Steps:    {report.step_count}")
    lines.append("")

    # Task summary
    if report.summary:
        lines.append("─" * 60)
        lines.append("SUMMARY")
        lines.append("─" * 60)
        lines.append(report.summary)
        lines.append("")

    # Original task context (if available in session)
    if session is not None:
        lines.append("─" * 60)
        lines.append("ORIGINAL TASK")
        lines.append("─" * 60)
        lines.append(session.task.request)
        lines.append("")

    # Actions taken
    if report.actions_taken:
        lines.append("─" * 60)
        lines.append("ACTIONS TAKEN")
        lines.append("─" * 60)
        for i, action in enumerate(report.actions_taken, 1):
            lines.append(f"  {i}. {action}")
        lines.append("")

    # Step trace with details
    if session is not None and session.trace_items:
        lines.append("─" * 60)
        lines.append("EXECUTION TRACE")
        lines.append("─" * 60)
        for item in session.trace_items:
            chosen_action = item.action_name or (
                item.planner_decision_type.value if item.planner_decision_type else "none"
            )
            item_status = item.status.value if item.status else "pending"

            # Status indicator for each step
            step_emoji = ""
            if item_status == "success":
                step_emoji = ""
            elif item_status == "error":
                step_emoji = ""
            elif item_status == "waiting_for_confirmation":
                step_emoji = ""

            lines.append(f"  Step {item.step_index + 1}: {chosen_action} {step_emoji}")

            if item.rationale_summary:
                rationale = item.rationale_summary
                if len(rationale) > 70:
                    rationale = rationale[:67] + "..."
                lines.append(f"    └─ {rationale}")

            if item.current_url and item.step_index == 0:
                url_display = item.current_url[:60] + "..." if len(item.current_url) > 60 else item.current_url
                lines.append(f"    └─ URL: {url_display}")

            if item.progress_outcome and not item.progress_outcome.made_progress:
                lines.append(f"    ⚠ No progress detected")
        lines.append("")

    # Confirmations requested
    confirmations_requested = []
    if session is not None:
        for item in session.trace_items:
            if item.state_transition and "waiting_for_confirmation" in item.state_transition:
                if item.action_name:
                    confirmations_requested.append(item.action_name)

    if confirmations_requested:
        lines.append("─" * 60)
        lines.append("CONFIRMATIONS REQUESTED")
        lines.append("─" * 60)
        for action in confirmations_requested:
            lines.append(f"  • {action}")
        lines.append("")

    # Pending states (if session is still active)
    if report.pending_confirmation is not None:
        lines.append("─" * 60)
        lines.append("PENDING CONFIRMATION")
        lines.append("─" * 60)
        lines.append(f"  Action: {report.pending_confirmation.action_name}")
        lines.append(f"  Reason: {report.pending_confirmation.reason}")
        if report.pending_confirmation.consequences:
            lines.append("  Consequences:")
            for consequence in report.pending_confirmation.consequences:
                lines.append(f"    - {consequence}")
        lines.append(f"\n  Prompt: {report.pending_confirmation.prompt}")
        lines.append("")

    if report.pending_user_question is not None:
        lines.append("─" * 60)
        lines.append("PENDING USER QUESTION")
        lines.append("─" * 60)
        lines.append(f"  {report.pending_user_question.question}")
        lines.append("")

    # Open questions
    if report.open_questions:
        lines.append("─" * 60)
        lines.append("OPEN QUESTIONS")
        lines.append("─" * 60)
        for item in report.open_questions:
            lines.append(f"  • {item}")
        lines.append("")

    # Next steps / recommendations
    if report.next_steps:
        lines.append("─" * 60)
        lines.append("RECOMMENDED NEXT STEPS")
        lines.append("─" * 60)
        for item in report.next_steps:
            lines.append(f"  → {item}")
        lines.append("")

    # Final URL
    if report.final_url:
        lines.append("─" * 60)
        lines.append("FINAL URL")
        lines.append("─" * 60)
        lines.append(f"  {report.final_url}")
        lines.append("")

    # Artifacts
    if report.artifact_refs:
        lines.append("─" * 60)
        lines.append("ARTIFACTS")
        lines.append("─" * 60)
        for item in report.artifact_refs:
            lines.append(f"  📄 {item}")
        lines.append("")

    # Session metadata
    if report.failure_reason:
        lines.append("─" * 60)
        lines.append("FAILURE REASON")
        lines.append("─" * 60)
        lines.append(f"  {report.failure_reason}")
        lines.append("")

    if report.completion_reason:
        lines.append("─" * 60)
        lines.append("COMPLETION REASON")
        lines.append("─" * 60)
        lines.append(f"  {report.completion_reason}")
        lines.append("")

    # Footer
    lines.append("═" * 60)
    lines.append(f"Session ID: {report.session_id}")
    lines.append(f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("═" * 60)
    lines.append("")

    return "\n".join(lines)


def build_planner(
    settings: RuntimeSettings,
    skill_registry,
    *,
    session: RuntimeSession | None = None,
) -> tuple[LLMPlanner | None, str | None]:
    """Build the configured planner or return a clear configuration error."""

    if not settings.planner_enabled:
        return None, (
            "Planner is not configured. Set `BROWSER_AGENT_PLANNER_ENABLED=true` and "
            "provide an endpoint plus model name."
        )
    if settings.planner_provider not in ("openai_compatible", "google_compatible"):
        return None, (
            f"Unsupported planner provider `{settings.planner_provider}`. "
            "Supported: `openai_compatible`, `google_compatible`."
        )
    if not settings.planner_base_url:
        return None, "Planner is enabled but `BROWSER_AGENT_PLANNER_BASE_URL` is missing."
    if not settings.planner_model:
        return None, "Planner is enabled but `BROWSER_AGENT_PLANNER_MODEL` is missing."

    if settings.planner_provider == "openai_compatible":
        provider: OpenAICompatibleProvider | GoogleGenerativeLanguageProvider = (
            OpenAICompatibleProvider(
                base_url=settings.planner_base_url,
                model_name=settings.planner_model,
                api_key=settings.planner_api_key,
                timeout_seconds=settings.planner_timeout_seconds,
                temperature=settings.planner_temperature,
            )
        )
    else:  # google_compatible
        provider = GoogleGenerativeLanguageProvider(
            base_url=settings.planner_base_url,
            model_name=settings.planner_model,
            api_key=settings.planner_api_key,
            timeout_seconds=settings.planner_timeout_seconds,
            temperature=settings.planner_temperature,
        )

    if session is not None:
        provider = TrackingLLMProvider(provider, session.llm_usage)

    parser = PlannerResponseParser(skill_registry=skill_registry)
    return LLMPlanner(provider=provider, parser=parser), None


def run_cli(argv: Sequence[str] | None = None) -> FinalReport:
    """Run the multi-step runtime and return the final report."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.ui and args.json:
        parser.error("--ui and --json cannot be used together.")

    task_text = args.task or input("Task> ").strip()
    settings = RuntimeSettings.from_env()
    if args.max_steps is not None:
        settings = settings.model_copy(update={"max_steps": args.max_steps})
    if args.headed:
        settings = settings.model_copy(update={"headless": False})
    if args.capture_screenshots:
        settings = settings.model_copy(update={"capture_screenshots": True})

    task = UserTask(
        request=task_text,
        start_url=args.start_url,
    )
    session = RuntimeSession(task=task, settings=settings)
    skill_registry = build_default_registry()
    planner, planner_error = build_planner(settings, skill_registry, session=session)
    if planner is None:
        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.STOPPED,
            summary=planner_error or "Planner is not configured.",
            completed=False,
            next_steps=[
                "Set `BROWSER_AGENT_PLANNER_ENABLED=true`.",
                "Set `BROWSER_AGENT_PLANNER_PROVIDER` to `openai_compatible` or `google_compatible`.",
                "Set `BROWSER_AGENT_PLANNER_BASE_URL` to the provider endpoint.",
                "Set `BROWSER_AGENT_PLANNER_MODEL` to the planner model name.",
                "Set `BROWSER_AGENT_PLANNER_API_KEY` to your API key.",
            ],
            step_count=0,
        )
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            print(render_text_report(report, session=session))
        return report

    browser = build_browser_engine(settings)
    if args.ui:
        from browser_agent.ui.console import AgentConsoleApp

        console_app = AgentConsoleApp(session=session, settings=settings)
        loop = RuntimeLoop(
            planner=planner,
            skill_registry=skill_registry,
            browser=browser,
            safety_guardrails=SafetyGuardrails(),
            confirmation_manager=ConfirmationManager(),
            trace_recorder=TraceRecorder(trace_dir=settings.trace_dir),
            event_emitter=console_app,
            planner_display_name=settings.planner_model,
            planner_provider_kind=settings.planner_provider,
        )
        return console_app.run_interactive_loop(loop)

    loop = RuntimeLoop(
        planner=planner,
        skill_registry=skill_registry,
        browser=browser,
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(trace_dir=settings.trace_dir),
    )
    report = run_cli_interactive(loop, session, args_json=args.json)

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(render_text_report(report, session=session))
    return report


def prompt_for_confirmation(report: FinalReport) -> ConfirmationDecision | None:
    """Display a confirmation request and capture user response."""

    if report.pending_confirmation is None:
        return None

    request = report.pending_confirmation
    print("\n" + "=" * 60)
    print("CONFIRMATION REQUIRED")
    print("=" * 60)
    print(f"Action: {request.action_name}")
    print(f"Reason: {request.reason}")
    print(f"Risk Level: {request.risk_level.value}")
    if request.consequences:
        print("Potential consequences:")
        for consequence in request.consequences:
            print(f"  - {consequence}")
    print(f"\n{request.prompt}")
    print("-" * 60)

    while True:
        response = input("Approve? (yes/no): ").strip().lower()
        if response in ("yes", "y"):
            return ConfirmationDecision(
                request_id=request.request_id,
                approved=True,
            )
        if response in ("no", "n"):
            notes = input("Reason for rejection (optional): ").strip()
            return ConfirmationDecision(
                request_id=request.request_id,
                approved=False,
                reviewer_notes=notes if notes else None,
            )
        print("Please enter 'yes' or 'no'.")


def prompt_for_user_answer(report: FinalReport) -> str | None:
    """Display a user question and capture the answer."""

    if report.pending_user_question is None:
        return None

    question = report.pending_user_question
    print("\n" + "=" * 60)
    print("USER INPUT REQUIRED")
    print("=" * 60)
    print(f"Question: {question.question}")
    print("-" * 60)

    answer = input("Your answer: ").strip()
    return answer if answer else None


def is_terminal_status(status: RuntimeStatus) -> bool:
    """Check if the runtime has reached a terminal state."""

    return status in {
        RuntimeStatus.COMPLETED,
        RuntimeStatus.STOPPED,
        RuntimeStatus.FAILED,
    }


def run_cli_interactive(
    loop: RuntimeLoop,
    session: RuntimeSession,
    args_json: bool,
) -> FinalReport:
    """Run the CLI with interactive resume support for pending states."""

    report = loop.run(session)

    # Handle pending states with interactive prompts
    while not is_terminal_status(report.status):
        if report.status == RuntimeStatus.WAITING_FOR_CONFIRMATION:
            if args_json:
                # In JSON mode, we can't interact, so return the pending report
                print(json.dumps(report.model_dump(mode="json"), indent=2))
                return report

            decision = prompt_for_confirmation(report)
            if decision is None:
                # Should not happen, but handle gracefully
                break

            if decision.approved:
                print("\n[Approved] Continuing execution...")
            else:
                print("\n[Rejected] Stopping execution...")

            report = loop.continue_after_confirmation(session, decision)

        elif report.status == RuntimeStatus.WAITING_FOR_USER:
            if args_json:
                # In JSON mode, we can't interact, so return the pending report
                print(json.dumps(report.model_dump(mode="json"), indent=2))
                return report

            answer = prompt_for_user_answer(report)
            if answer is None:
                answer = ""

            print(f"\n[Answer received] Continuing execution...")
            report = loop.continue_after_user_answer(session, answer)

        else:
            # Unknown state, break to avoid infinite loop
            break

    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint used by the console script."""

    run_cli(argv)
    return 0
