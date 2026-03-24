"""Configuration helpers for the browser agent foundation."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class RuntimeSettings(BaseModel):
    """Runtime settings loaded from environment variables or CLI defaults."""

    headless: bool = True
    max_steps: int = 8
    max_no_progress_steps: int = 3
    default_timeout_ms: int = 5_000
    max_text_chars: int = 4_000
    trace_dir: Path = Field(default_factory=lambda: Path("traces"))
    artifact_dir: Path = Field(default_factory=lambda: Path("artifacts"))
    capture_screenshots: bool = False
    bootstrap_mode: bool = True
    allow_external_navigation: bool = True
    planner_enabled: bool = False
    planner_provider: str = "openai_compatible"
    planner_base_url: str | None = None
    planner_model: str | None = None
    planner_api_key: str | None = None
    planner_timeout_seconds: float = 30.0
    planner_temperature: float = 0.0

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        """Build settings from the process environment."""

        return cls(
            headless=os.getenv("BROWSER_AGENT_HEADLESS", "true").lower() == "true",
            max_steps=int(os.getenv("BROWSER_AGENT_MAX_STEPS", "8")),
            max_no_progress_steps=int(
                os.getenv("BROWSER_AGENT_MAX_NO_PROGRESS_STEPS", "3")
            ),
            default_timeout_ms=int(os.getenv("BROWSER_AGENT_TIMEOUT_MS", "5000")),
            max_text_chars=int(os.getenv("BROWSER_AGENT_MAX_TEXT_CHARS", "4000")),
            trace_dir=Path(os.getenv("BROWSER_AGENT_TRACE_DIR", "traces")),
            artifact_dir=Path(os.getenv("BROWSER_AGENT_ARTIFACT_DIR", "artifacts")),
            capture_screenshots=os.getenv(
                "BROWSER_AGENT_CAPTURE_SCREENSHOTS",
                "false",
            ).lower()
            == "true",
            bootstrap_mode=os.getenv("BROWSER_AGENT_BOOTSTRAP_MODE", "true").lower() == "true",
            allow_external_navigation=os.getenv(
                "BROWSER_AGENT_ALLOW_EXTERNAL_NAVIGATION",
                "true",
            ).lower()
            == "true",
            planner_enabled=os.getenv("BROWSER_AGENT_PLANNER_ENABLED", "false").lower()
            == "true",
            planner_provider=os.getenv(
                "BROWSER_AGENT_PLANNER_PROVIDER",
                "openai_compatible",
            ),
            planner_base_url=os.getenv("BROWSER_AGENT_PLANNER_BASE_URL"),
            planner_model=os.getenv("BROWSER_AGENT_PLANNER_MODEL"),
            planner_api_key=os.getenv("BROWSER_AGENT_PLANNER_API_KEY"),
            planner_timeout_seconds=float(
                os.getenv("BROWSER_AGENT_PLANNER_TIMEOUT_SECONDS", "30")
            ),
            planner_temperature=float(
                os.getenv("BROWSER_AGENT_PLANNER_TEMPERATURE", "0")
            ),
        )
