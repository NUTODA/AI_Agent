"""Terminal-style CLI for the browser agent foundation."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from browser_agent.browser.engine import StubBrowserEngine
from browser_agent.browser.page_state import PageState
from browser_agent.config import RuntimeSettings
from browser_agent.llm.planner import FoundationPlanner
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import FinalReport, UserTask
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="browser-agent",
        description="Bootstrap the browser agent foundation runtime.",
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
    return parser


def build_initial_page_state(start_url: str | None) -> PageState:
    """Create a small initial page snapshot for bootstrap mode."""

    if start_url:
        return PageState(
            url=start_url,
            title="Bootstrap Session",
            summary="Stub browser prepared for the requested starting URL.",
            text_excerpt=f"Bootstrap mode prepared a stub browser page at {start_url}.",
        )
    return PageState(
        summary="Stub browser started without an explicit starting URL.",
        text_excerpt="Bootstrap mode is ready to capture the first observation.",
    )


def render_text_report(report: FinalReport) -> str:
    """Format a readable terminal summary."""

    lines = [
        "Browser Agent Foundation",
        "========================",
        f"Status: {report.status.value}",
        f"Summary: {report.summary}",
    ]
    if report.actions_taken:
        lines.append(f"Actions: {', '.join(report.actions_taken)}")
    if report.open_questions:
        lines.append("Open questions:")
        lines.extend(f"- {item}" for item in report.open_questions)
    if report.next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {item}" for item in report.next_steps)
    if report.final_url:
        lines.append(f"Final URL: {report.final_url}")
    return "\n".join(lines)


def run_cli(argv: Sequence[str] | None = None) -> FinalReport:
    """Run the bootstrap runtime and return the final report."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    task_text = args.task or input("Task> ").strip()
    settings = RuntimeSettings.from_env()
    if args.max_steps is not None:
        settings = settings.model_copy(update={"max_steps": args.max_steps})

    task = UserTask(
        request=task_text,
        start_url=args.start_url,
    )
    session = RuntimeSession(task=task, settings=settings)
    browser = StubBrowserEngine(initial_state=build_initial_page_state(args.start_url))
    loop = RuntimeLoop(
        planner=FoundationPlanner(),
        skill_registry=build_default_registry(),
        browser=browser,
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(),
    )
    report = loop.run(session)

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(render_text_report(report))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint used by the console script."""

    run_cli(argv)
    return 0
