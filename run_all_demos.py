#!/usr/bin/env python3
"""Run all three demo scenarios automatically with auto-confirm."""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Load environment from .env.browser-agent
from dotenv import load_dotenv
env_file = Path(__file__).parent / ".env.browser-agent"
if env_file.exists():
    load_dotenv(env_file)
    print(f"Loaded environment from {env_file}")

from browser_agent.browser.engine import PlaywrightBrowserEngine
from browser_agent.config import RuntimeSettings
from browser_agent.llm.parser import PlannerResponseParser
from browser_agent.llm.planner import LLMPlanner
from browser_agent.llm.provider import OpenAICompatibleProvider
from browser_agent.runtime.loop import RuntimeLoop
from browser_agent.runtime.models import FinalReport, RuntimeStatus, UserTask
from browser_agent.runtime.session import RuntimeSession
from browser_agent.runtime.trace import TraceRecorder
from browser_agent.safety.confirmations import ConfirmationDecision, ConfirmationManager
from browser_agent.safety.guardrails import SafetyGuardrails
from browser_agent.skills.registry import build_default_registry


def auto_confirm_manager(report):
    """Automatically approve all confirmations."""
    if report.pending_confirmation is None:
        return None
    request = report.pending_confirmation
    print(f"[AUTO-APPROVE] {request.action_name} - {request.reason}")
    return ConfirmationDecision(
        request_id=request.request_id,
        approved=True,
    )


def run_demo(name: str, url: str, task: str, settings: RuntimeSettings) -> FinalReport:
    """Run a single demo scenario."""
    print("\n" + "="*70)
    print(f"  DEMO: {name}")
    print(f"  URL: {url}")
    print(f"  TASK: {task}")
    print("="*70 + "\n")

    # Increase max steps for demos to handle confirmation overhead
    demo_settings = settings.model_copy()
    demo_settings.max_steps = 25

    user_task = UserTask(request=task, start_url=url)
    session = RuntimeSession(task=user_task, settings=demo_settings)
    skill_registry = build_default_registry()

    # Build planner
    provider = OpenAICompatibleProvider(
        base_url=demo_settings.planner_base_url,
        model_name=demo_settings.planner_model,
        api_key=demo_settings.planner_api_key,
        timeout_seconds=demo_settings.planner_timeout_seconds,
        max_retries=demo_settings.planner_retries,
        retry_backoff_seconds=demo_settings.planner_retry_backoff_seconds,
        temperature=demo_settings.planner_temperature,
    )
    parser = PlannerResponseParser(skill_registry=skill_registry)
    planner = LLMPlanner(provider=provider, parser=parser)

    # Build browser and loop
    browser = PlaywrightBrowserEngine(
        headless=demo_settings.headless,
        default_timeout_ms=demo_settings.default_timeout_ms,
        max_text_chars=demo_settings.max_text_chars,
        artifact_dir=demo_settings.artifact_dir,
        capture_screenshots=demo_settings.capture_screenshots,
    )

    loop = RuntimeLoop(
        planner=planner,
        skill_registry=skill_registry,
        browser=browser,
        safety_guardrails=SafetyGuardrails(),
        confirmation_manager=ConfirmationManager(),
        trace_recorder=TraceRecorder(trace_dir=demo_settings.trace_dir),
    )

    # Run with auto-confirm
    report = loop.run(session)

    while report.status not in {RuntimeStatus.COMPLETED, RuntimeStatus.STOPPED, RuntimeStatus.FAILED}:
        if report.status == RuntimeStatus.WAITING_FOR_CONFIRMATION:
            decision = auto_confirm_manager(report)
            if decision is None:
                break
            report = loop.continue_after_confirmation(session, decision)
        elif report.status == RuntimeStatus.WAITING_FOR_USER:
            # Auto-respond with empty answer
            report = loop.continue_after_user_answer(session, "")
        else:
            break

    browser.stop()

    # Print summary
    print(f"\n{'='*70}")
    print(f"  RESULT: {report.status.value.upper()}")
    print(f"  STEPS: {report.step_count}")
    if report.summary:
        print(f"  SUMMARY: {report.summary}")
    if report.failure_reason:
        print(f"  ERROR: {report.failure_reason}")
    print(f"{'='*70}\n")

    return report


def main():
    settings = RuntimeSettings.from_env()

    print("\n" + "#"*70)
    print("#  BROWSER AGENT - DEMO SCENARIOS")
    print("#"*70)
    print(f"\nProvider: {settings.planner_provider}")
    print(f"Model: {settings.planner_model}")
    print(f"Base URL: {settings.planner_base_url}")

    # Demo 1: Inbox Management
    report1 = run_demo(
        name="Inbox Management - Mark Spam",
        url="http://localhost:8765/inbox_demo.html",
        task="Mark the suspicious emails as spam. Look for obvious spam indicators like suspicious sender names or unrealistic offers.",
        settings=settings,
    )

    # Demo 2: Food Ordering
    report2 = run_demo(
        name="Food Ordering - Simple Order",
        url="http://localhost:8765/food_demo.html",
        task="Order a Classic Burger and a Soft Drink",
        settings=settings,
    )

    # Demo 3: Job Applications
    report3 = run_demo(
        name="Job Applications - Filter and Apply",
        url="http://localhost:8765/jobs_demo.html",
        task="Filter for remote full-time jobs and show me the Senior Frontend Developer listing",
        settings=settings,
    )

    # Final summary
    print("\n" + "#"*70)
    print("#  FINAL SUMMARY")
    print("#"*70)
    print(f"\nDemo 1 (Inbox): {report1.status.value} - {report1.step_count} steps")
    print(f"Demo 2 (Food):  {report2.status.value} - {report2.step_count} steps")
    print(f"Demo 3 (Jobs):  {report3.status.value} - {report3.step_count} steps")

    all_passed = all(
        r.status == RuntimeStatus.COMPLETED for r in [report1, report2, report3]
    )
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
