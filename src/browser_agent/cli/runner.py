"""Core run loop CLI (`browser-agent run` / bare task) for the browser agent runtime."""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from typing import Sequence

from browser_agent.browser.engine import PlaywrightBrowserEngine
from browser_agent.cli.bootstrap import infer_explicit_start_url
from browser_agent.config import (
    RuntimeSettings,
    home_config_path,
    planner_env_configured,
)
from browser_agent.llm.parser import PlannerResponseParser
from browser_agent.llm.planner import LLMPlanner
from browser_agent.llm.provider import (
    GoogleGenerativeLanguageProvider,
    OpenAICompatibleProvider,
    TrackingLLMProvider,
)
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import FinalReport, RuntimeStatus, UserTask, new_id
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationDecision, ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry


def build_run_parser() -> argparse.ArgumentParser:
    """Create the parser for `browser-agent run` (and legacy bare-task invocation)."""

    parser = argparse.ArgumentParser(
        prog="browser-agent run",
        description=(
            "Run the browser agent multi-step runtime. "
            "Use --ui for the Rich Agent Console (live phases, steps, tokens, confirmations)."
        ),
        add_help=True,
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="Natural-language task to run.",
    )
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
    parser.add_argument(
        "--ui-mode",
        choices=("demo", "debug"),
        default="demo",
        help="UI presentation mode for --ui: demo is split-screen friendly, debug shows full detail.",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help=(
            "Keep the browser open and continue the conversation after each completed run. "
            "Type `exit` to finish the chat session."
        ),
    )
    parser.add_argument(
        "--skip-setup-check",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def parse_run_args(argv: Sequence[str] | None) -> Namespace:
    """Parse run-mode argv."""

    parser = build_run_parser()
    values = list(argv) if argv is not None else None
    if hasattr(parser, "parse_intermixed_args"):
        return parser.parse_intermixed_args(values)
    return parser.parse_args(values)


def run_cli_from_args(args: Namespace, *, task_override: str | None = None) -> FinalReport:
    """Execute the runtime from a parsed run-namespace."""

    if args.ui and args.json:
        print("[ERROR] --ui and --json cannot be used together.", file=sys.stderr)
        report = FinalReport(
            session_id=new_id("session"),
            status=RuntimeStatus.STOPPED,
            summary="Invalid CLI flags.",
            completed=False,
            step_count=0,
        )
        return report

    if args.chat and args.json:
        print("[ERROR] --chat and --json cannot be used together.", file=sys.stderr)
        report = FinalReport(
            session_id=new_id("session"),
            status=RuntimeStatus.STOPPED,
            summary="Invalid CLI flags.",
            completed=False,
            step_count=0,
        )
        return report

    task_text = task_override if task_override is not None else (" ".join(args.task).strip() or input("Task> ").strip())
    settings = RuntimeSettings.from_env()
    if args.max_steps is not None:
        settings = settings.model_copy(update={"max_steps": args.max_steps})
    if args.headed:
        settings = settings.model_copy(update={"headless": False})
        if settings.action_delay_ms <= 0:
            settings = settings.model_copy(
                update={"action_delay_ms": 350, "highlight_actions": True}
            )
    if args.capture_screenshots:
        settings = settings.model_copy(update={"capture_screenshots": True})

    if not getattr(args, "skip_setup_check", False) and not planner_env_configured(settings):
        report = FinalReport(
            session_id=new_id("session"),
            status=RuntimeStatus.STOPPED,
            summary=(
                "Setup required. Configure the planner API (global config or environment).\n\n"
                f"Run: browser-agent setup\n\n"
                f"Config file: {home_config_path()}"
            ),
            completed=False,
            next_steps=[
                "Run `browser-agent setup` to create ~/.browser-agent/config.yaml",
                "Or set BROWSER_AGENT_PLANNER_* environment variables (see .env.example).",
                "Run `browser-agent doctor` to verify your installation.",
            ],
            step_count=0,
        )
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            print(render_text_report(report, session=None))
        return report

    skill_registry = build_default_registry()
    _, planner_error = build_planner(settings, skill_registry, session=None)
    if planner_error is not None:
        session = RuntimeSession(
            task=UserTask(request=task_text, start_url=args.start_url),
            settings=settings,
        )
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
                "Or run: browser-agent setup",
            ],
            step_count=0,
        )
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            print(render_text_report(report, session=session))
        return report

    browser = build_browser_engine(settings)
    try:
        if args.chat:
            return run_cli_chat(
                args=args,
                settings=settings,
                skill_registry=skill_registry,
                browser=browser,
                initial_task_text=task_text,
                initial_start_url=args.start_url,
            )

        return run_single_task(
            args=args,
            settings=settings,
            skill_registry=skill_registry,
            browser=browser,
            task_text=task_text,
            start_url=args.start_url,
            keep_browser_open=False,
            render_output=True,
        )
    finally:
        if args.chat:
            try:
                browser.stop()
            except Exception:
                pass


def build_browser_engine(settings: RuntimeSettings) -> PlaywrightBrowserEngine:
    """Create the real browser adapter used by the CLI runtime."""

    return PlaywrightBrowserEngine(
        headless=settings.headless,
        default_timeout_ms=settings.default_timeout_ms,
        max_text_chars=settings.max_text_chars,
        artifact_dir=settings.artifact_dir,
        capture_screenshots=settings.capture_screenshots,
        action_delay_ms=settings.action_delay_ms,
        highlight_actions=settings.highlight_actions,
    )


def build_runtime_loop(
    *,
    settings: RuntimeSettings,
    skill_registry,
    browser,
    planner,
    event_emitter=None,
    keep_browser_open: bool = False,
) -> RuntimeLoop:
    """Create a runtime loop for one task turn."""

    return RuntimeLoop(
        planner=planner,
        skill_registry=skill_registry,
        browser=browser,
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(trace_dir=settings.trace_dir),
        event_emitter=event_emitter,
        planner_display_name=settings.planner_model,
        planner_provider_kind=settings.planner_provider,
        keep_browser_open=keep_browser_open,
    )


def run_single_task(
    *,
    args: Namespace,
    settings: RuntimeSettings,
    skill_registry,
    browser,
    task_text: str,
    start_url: str | None,
    keep_browser_open: bool,
    render_output: bool,
) -> FinalReport:
    """Execute one task turn against the current browser session."""

    session = RuntimeSession(
        task=UserTask(
            request=task_text,
            start_url=start_url,
        ),
        settings=settings,
    )
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
                "Or run: browser-agent setup",
            ],
            step_count=0,
        )
        if render_output:
            if args.json:
                print(json.dumps(report.model_dump(mode="json"), indent=2))
            else:
                print(render_text_report(report, session=session))
        return report

    if args.ui:
        from browser_agent.ui.console import AgentConsoleApp

        console_app = AgentConsoleApp(
            session=session,
            settings=settings,
            ui_mode=args.ui_mode,
        )
        loop = build_runtime_loop(
            settings=settings,
            skill_registry=skill_registry,
            browser=browser,
            planner=planner,
            event_emitter=console_app,
            keep_browser_open=keep_browser_open,
        )
        return console_app.run_interactive_loop(loop)

    loop = build_runtime_loop(
        settings=settings,
        skill_registry=skill_registry,
        browser=browser,
        planner=planner,
        keep_browser_open=keep_browser_open,
    )
    report = run_cli_interactive(loop, session, args_json=args.json)

    if render_output:
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            print(render_text_report(report, session=session))
    return report


def run_cli_chat(
    *,
    args: Namespace,
    settings: RuntimeSettings,
    skill_registry,
    browser,
    initial_task_text: str,
    initial_start_url: str | None,
) -> FinalReport:
    """Run a multi-turn chat session while keeping the browser alive."""

    print(
        "[browser-agent] Chat mode is active. The browser will stay open between turns. "
        "Type `exit` when you're done."
    )
    report = run_single_task(
        args=args,
        settings=settings,
        skill_registry=skill_registry,
        browser=browser,
        task_text=initial_task_text,
        start_url=initial_start_url,
        keep_browser_open=True,
        render_output=False,
    )
    if not args.ui:
        print_chat_response(report)

    while True:
        next_task = prompt_for_chat_message()
        if next_task is None:
            return report

        chat_answer = maybe_answer_from_previous_run(
            next_task,
            previous_report=report,
            settings=settings,
        )
        if chat_answer is not None:
            print(f"\nAssistant: {chat_answer}\n")
            continue

        report = run_single_task(
            args=args,
            settings=settings,
            skill_registry=skill_registry,
            browser=browser,
            task_text=next_task,
            start_url=infer_explicit_start_url(next_task),
            keep_browser_open=True,
            render_output=False,
        )
        if not args.ui:
            print_chat_response(report)


def print_chat_response(report: FinalReport) -> None:
    """Print a concise assistant-style reply for chat mode."""

    message = (
        (report.completion_reason or "").strip()
        or (report.summary or "").strip()
        or (report.failure_reason or "").strip()
        or "Task finished."
    )
    if report.status == RuntimeStatus.FAILED:
        label = "Assistant (failed)"
    elif report.status == RuntimeStatus.STOPPED:
        label = "Assistant (partial)"
    else:
        label = "Assistant"
    print(f"\n{label}: {message}\n")


def maybe_answer_from_previous_run(
    message: str,
    *,
    previous_report: FinalReport,
    settings: RuntimeSettings,
) -> str | None:
    """Answer meta follow-up questions about the previous run without starting a new one."""

    normalized = " ".join(message.lower().split())
    if not normalized:
        return None
    if not _looks_like_meta_followup(normalized):
        return None
    return build_previous_run_answer(
        normalized,
        previous_report=previous_report,
        settings=settings,
    )


def _looks_like_meta_followup(message: str) -> bool:
    """Heuristic: distinguish chat about the previous run from a new browser task."""

    meta_markers = (
        "ошиб",
        "упал",
        "сломал",
        "сломался",
        "не получилось",
        "не вышло",
        "не сработал",
        "почему",
        "зачем",
        "что пошло не так",
        "что случилось",
        "что ты сделал",
        "что сделал",
        "какая ошибка",
        "какой шаг",
        "на каком шаге",
        "где останов",
        "почему останов",
        "почему словил",
        "почему ты",
        "почему агент",
        "log",
        "logs",
        "trace",
        "traces",
        "runtime",
        "navigate",
        "timeout",
    )
    question_starters = (
        "почему",
        "зачем",
        "что",
        "где",
        "какая",
        "какой",
        "на каком",
        "why",
        "what",
        "where",
        "which",
    )
    if any(marker in message for marker in meta_markers):
        return True
    return message.endswith("?") and message.startswith(question_starters)


def build_previous_run_answer(
    message: str,
    *,
    previous_report: FinalReport,
    settings: RuntimeSettings,
) -> str:
    """Build a short conversational answer from the previous run summary."""

    status = previous_report.status
    action = previous_report.actions_taken[0] if previous_report.actions_taken else None
    failure_reason = (previous_report.failure_reason or "").strip()
    summary = (previous_report.summary or "").strip()
    final_url = (previous_report.final_url or "about:blank").strip() or "about:blank"
    timeout_seconds = max(1, int(round(settings.default_timeout_ms / 1000.0)))

    if any(token in message for token in ("что ты сделал", "что сделал", "какой шаг", "на каком шаге")):
        if previous_report.actions_taken:
            return (
                f"В прошлом запуске я успел сделать {previous_report.step_count} шаг(ов): "
                f"{', '.join(previous_report.actions_taken)}. "
                f"Последний известный URL: {final_url}."
            )
        return (
            f"В прошлом запуске я почти не успел выполнить действий. "
            f"Статус был `{status.value}`, последний известный URL: {final_url}."
        )

    if status == RuntimeStatus.FAILED:
        if action == "navigate":
            return (
                f"Я словил ошибку на шаге `navigate`: переход на страницу не завершился в пределах "
                f"таймаута примерно {timeout_seconds} сек., поэтому runtime остановился. "
                f"По последнему состоянию браузер остался на `{final_url}`, то есть целевая страница так и не успела открыться. "
                f"Ближайшая причина из отчёта: {failure_reason or summary or 'navigate timed out'}."
            )
        return (
            f"Прошлый запуск завершился со статусом `failed`. "
            f"Сбой произошёл на действии `{action or 'unknown'}`. "
            f"Причина из отчёта: {failure_reason or summary or 'точная причина не была записана'}. "
            f"Последний известный URL: {final_url}."
        )

    if status == RuntimeStatus.STOPPED:
        return (
            f"Прошлый запуск остановился со статусом `stopped`. "
            f"Причина: {failure_reason or summary or 'runtime остановился без дополнительной детали'}. "
            f"Последний известный URL: {final_url}."
        )

    return (
        f"Прошлый запуск завершился со статусом `{status.value}`. "
        f"Коротко: {previous_report.completion_reason or summary or 'задача завершилась без дополнительного комментария'}."
    )


def prompt_for_chat_message() -> str | None:
    """Read the next user turn for CLI chat mode."""

    while True:
        try:
            answer = input("You: ")
        except EOFError:
            return None
        except KeyboardInterrupt:
            print()
            return None

        text = answer.strip()
        if text.lower() in {"exit", "quit", "/exit", "/quit"}:
            return None
        if text:
            return text


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

    if report.pending_human_intervention is not None:
        request = report.pending_human_intervention
        lines.append("─" * 60)
        lines.append("PENDING HUMAN CHECKPOINT")
        lines.append("─" * 60)
        lines.append(f"  Kind: {request.kind.value}")
        lines.append(f"  Instruction: {request.instruction}")
        lines.append(f"  Reason: {request.prompt}")
        if request.allowed_actions:
            lines.append("  Allowed actions:")
            for action in request.allowed_actions:
                lines.append(f"    - {action}")
        if request.resume_hint:
            lines.append(f"  Resume: {request.resume_hint}")
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
                max_retries=settings.planner_retries,
                retry_backoff_seconds=settings.planner_retry_backoff_seconds,
                temperature=settings.planner_temperature,
            )
        )
    else:  # google_compatible
        provider = GoogleGenerativeLanguageProvider(
            base_url=settings.planner_base_url,
            model_name=settings.planner_model,
            api_key=settings.planner_api_key,
            timeout_seconds=settings.planner_timeout_seconds,
            max_retries=settings.planner_retries,
            retry_backoff_seconds=settings.planner_retry_backoff_seconds,
            temperature=settings.planner_temperature,
        )

    if session is not None:
        provider = TrackingLLMProvider(provider, session.llm_usage)

    parser = PlannerResponseParser(skill_registry=skill_registry)
    return LLMPlanner(provider=provider, parser=parser), None


def run_cli(argv: Sequence[str] | None = None) -> FinalReport:
    """Run the multi-step runtime and return the final report."""

    args = parse_run_args(argv)
    return run_cli_from_args(args)


def prompt_for_confirmation(report: FinalReport) -> ConfirmationDecision | None:
    """Display a confirmation request and capture user response."""

    if report.pending_confirmation is None:
        return None

    request = report.pending_confirmation
    print("\n" + "=" * 60)
    print("CONFIRMATION REQUIRED")
    print("=" * 60)
    print(f"Request ID: {request.request_id}")
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
    return answer


def prompt_for_human_intervention(report: FinalReport) -> str | None:
    """Pause until the operator completes a manual browser checkpoint."""

    if report.pending_human_intervention is None:
        return None

    request = report.pending_human_intervention
    print("\n" + "=" * 60)
    print("MANUAL BROWSER STEP REQUIRED")
    print("=" * 60)
    print(f"Checkpoint: {request.kind.value}")
    print(f"Do this: {request.instruction}")
    print(f"Why paused: {request.prompt}")
    if request.allowed_actions:
        print("Allowed actions:")
        for action in request.allowed_actions:
            print(f"  - {action}")
    if request.resume_hint:
        print(f"\nResume: {request.resume_hint}")
    print("-" * 60)
    note = input("Press Enter when done (or leave a short note): ").strip()
    return note


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
                print(
                    "[browser-agent] --json disables interactive approval prompts. "
                    "Re-run without --json or use `browser-agent run --ui` to approve or reject.",
                    file=sys.stderr,
                )
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
                print(
                    "[browser-agent] --json disables interactive user-input prompts. "
                    "Re-run without --json or use `browser-agent run --ui`.",
                    file=sys.stderr,
                )
                print(json.dumps(report.model_dump(mode="json"), indent=2))
                return report

            answer = prompt_for_user_answer(report)
            if answer is None:
                answer = ""

            print(f"\n[Answer received] Continuing execution...")
            report = loop.continue_after_user_answer(session, answer)

        elif report.status == RuntimeStatus.WAITING_FOR_INTERVENTION:
            if args_json:
                print(
                    "[browser-agent] --json disables interactive browser-checkpoint prompts. "
                    "Re-run without --json or use `browser-agent run --ui`.",
                    file=sys.stderr,
                )
                print(json.dumps(report.model_dump(mode="json"), indent=2))
                return report

            note = prompt_for_human_intervention(report)
            if note is None:
                note = ""

            print("\n[Checkpoint completed] Continuing execution...")
            report = loop.continue_after_human_intervention(session, note)

        else:
            # Unknown state, break to avoid infinite loop
            break

    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Legacy entrypoint; prefer browser_agent.cli.main:app."""

    run_cli(argv)
    return 0
