"""Terminal-style CLI for the browser agent runtime."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from browser_agent.browser.engine import PlaywrightBrowserEngine
from browser_agent.config import RuntimeSettings
from browser_agent.llm.parser import PlannerResponseParser
from browser_agent.llm.planner import LLMPlanner
from browser_agent.llm.provider import OpenAICompatibleProvider
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import FinalReport, RuntimeStatus, UserTask
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="browser-agent",
        description="Run the browser agent multi-step runtime.",
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
    """Format a readable terminal summary."""

    lines = [
        "Browser Agent",
        "=============",
        f"Status: {report.status.value}",
        f"Steps: {report.step_count}",
        f"Summary: {report.summary}",
    ]
    if session is not None and session.trace_items:
        lines.append("Step trace:")
        for item in session.trace_items:
            chosen_action = item.action_name or (
                item.planner_decision_type.value if item.planner_decision_type else "none"
            )
            item_status = item.status.value if item.status else "no_tool_result"
            lines.append(f"- step {item.step_index}: {chosen_action} -> {item_status}")
    if report.actions_taken:
        lines.append(f"Actions: {', '.join(report.actions_taken)}")
    if report.pending_confirmation is not None:
        lines.append("Pending confirmation:")
        lines.append(f"- {report.pending_confirmation.prompt}")
    if report.pending_user_question is not None:
        lines.append("Pending user question:")
        lines.append(f"- {report.pending_user_question.question}")
    if report.open_questions:
        lines.append("Open questions:")
        lines.extend(f"- {item}" for item in report.open_questions)
    if report.next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {item}" for item in report.next_steps)
    if report.final_url:
        lines.append(f"Final URL: {report.final_url}")
    if report.artifact_refs:
        lines.append("Artifacts:")
        lines.extend(f"- {item}" for item in report.artifact_refs)
    return "\n".join(lines)


def build_planner(
    settings: RuntimeSettings,
    skill_registry,
) -> tuple[LLMPlanner | None, str | None]:
    """Build the configured planner or return a clear configuration error."""

    if not settings.planner_enabled:
        return None, (
            "Planner is not configured. Set `BROWSER_AGENT_PLANNER_ENABLED=true` and "
            "provide an OpenAI-compatible endpoint plus model name."
        )
    if settings.planner_provider != "openai_compatible":
        return None, (
            f"Unsupported planner provider `{settings.planner_provider}`. "
            "Only `openai_compatible` is currently implemented."
        )
    if not settings.planner_base_url:
        return None, "Planner is enabled but `BROWSER_AGENT_PLANNER_BASE_URL` is missing."
    if not settings.planner_model:
        return None, "Planner is enabled but `BROWSER_AGENT_PLANNER_MODEL` is missing."

    provider = OpenAICompatibleProvider(
        base_url=settings.planner_base_url,
        model_name=settings.planner_model,
        api_key=settings.planner_api_key,
        timeout_seconds=settings.planner_timeout_seconds,
        temperature=settings.planner_temperature,
    )
    parser = PlannerResponseParser(skill_registry=skill_registry)
    return LLMPlanner(provider=provider, parser=parser), None


def run_cli(argv: Sequence[str] | None = None) -> FinalReport:
    """Run the multi-step runtime and return the final report."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

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
    planner, planner_error = build_planner(settings, skill_registry)
    if planner is None:
        report = FinalReport(
            session_id=session.session_id,
            status=RuntimeStatus.STOPPED,
            summary=planner_error or "Planner is not configured.",
            completed=False,
            next_steps=[
                "Set `BROWSER_AGENT_PLANNER_ENABLED=true`.",
                "Set `BROWSER_AGENT_PLANNER_BASE_URL` to an OpenAI-compatible endpoint.",
                "Set `BROWSER_AGENT_PLANNER_MODEL` to the planner model name.",
            ],
            step_count=0,
        )
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            print(render_text_report(report, session=session))
        return report

    browser = build_browser_engine(settings)
    loop = RuntimeLoop(
        planner=planner,
        skill_registry=skill_registry,
        browser=browser,
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(trace_dir=settings.trace_dir),
    )
    report = loop.run(session)

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(render_text_report(report, session=session))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint used by the console script."""

    run_cli(argv)
    return 0
