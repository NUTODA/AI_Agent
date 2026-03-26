"""Configuration helpers for the browser agent foundation."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Minimum Python for this package (keep in sync with pyproject requires-python).
MIN_PYTHON = (3, 10)


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
    planner_timeout_seconds: float = 90.0
    planner_retries: int = 2
    planner_retry_backoff_seconds: float = 0.75
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
            bootstrap_mode=os.getenv("BROWSER_AGENT_BOOTSTRAP_MODE", "true").lower()
            == "true",
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
                os.getenv("BROWSER_AGENT_PLANNER_TIMEOUT_SECONDS", "90")
            ),
            planner_retries=int(os.getenv("BROWSER_AGENT_PLANNER_RETRIES", "2")),
            planner_retry_backoff_seconds=float(
                os.getenv("BROWSER_AGENT_PLANNER_RETRY_BACKOFF_SECONDS", "0.75")
            ),
            planner_temperature=float(
                os.getenv("BROWSER_AGENT_PLANNER_TEMPERATURE", "0")
            ),
        )


# --- User home config (~/.browser-agent/config.yaml) ---


def home_agent_dir() -> Path:
    return Path.home() / ".browser-agent"


def home_config_path() -> Path:
    return home_agent_dir() / "config.yaml"


class UserHomeConfig(BaseModel):
    """Friendly fields persisted in ~/.browser-agent/config.yaml."""

    provider: str = "openrouter"
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    def planner_backend(self) -> str:
        """Maps UI provider label to RuntimeSettings.planner_provider."""

        p = self.provider.lower().strip()
        if p in ("google", "gemini"):
            return "google_compatible"
        return "openai_compatible"


def default_base_url_for_provider(label: str) -> str:
    p = label.lower().strip()
    if p == "openai":
        return "https://api.openai.com/v1"
    if p == "openrouter":
        return "https://openrouter.ai/api/v1"
    if p in ("google", "gemini"):
        return "https://generativelanguage.googleapis.com/v1beta"
    return "https://api.openai.com/v1"


def provider_presets() -> list[tuple[str, str, str]]:
    """(label, default base_url, example model) for prompts."""

    return [
        ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
        ("openrouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
        ("google", "https://generativelanguage.googleapis.com/v1beta", "gemini-2.0-flash"),
        ("custom", "", ""),
    ]


def load_home_config_file() -> UserHomeConfig | None:
    path = home_config_path()
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return UserHomeConfig(
        provider=str(raw.get("provider") or "openrouter"),
        base_url=str(raw.get("base_url") or ""),
        api_key=str(raw.get("api_key") or ""),
        model=str(raw.get("model") or ""),
    )


def save_home_config(cfg: UserHomeConfig) -> None:
    """Write config and restrict permissions when the OS allows it."""

    d = home_agent_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = home_config_path()
    payload = {
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "api_key": cfg.api_key,
        "model": cfg.model,
    }
    path.write_text(yaml.safe_dump(payload, default_flow_style=False), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def delete_home_config_file() -> bool:
    path = home_config_path()
    if path.is_file():
        path.unlink()
        return True
    return False


def apply_home_config_to_environment() -> None:
    """Apply ~/.browser-agent/config.yaml to os.environ if keys are unset.

    Precedence: existing environment variables win (user / shell).
    """

    cfg = load_home_config_file()
    if cfg is None:
        return

    def set_if_absent(key: str, value: str | None) -> None:
        if value is None or value == "":
            return
        if os.getenv(key) is None:
            os.environ[key] = value

    set_if_absent("BROWSER_AGENT_PLANNER_ENABLED", "true")
    set_if_absent("BROWSER_AGENT_PLANNER_PROVIDER", cfg.planner_backend())
    set_if_absent("BROWSER_AGENT_PLANNER_BASE_URL", cfg.base_url or None)
    set_if_absent("BROWSER_AGENT_PLANNER_MODEL", cfg.model or None)
    set_if_absent("BROWSER_AGENT_PLANNER_API_KEY", cfg.api_key or None)


def home_config_covers_planner() -> bool:
    """True if home config exists and has the minimum fields to run the planner."""

    cfg = load_home_config_file()
    if cfg is None:
        return False
    return bool(cfg.base_url.strip() and cfg.model.strip() and cfg.api_key.strip())


def planner_env_configured(settings: RuntimeSettings) -> bool:
    """Whether planner can be constructed (same rules as build_planner)."""

    if not settings.planner_enabled:
        return False
    if settings.planner_provider not in ("openai_compatible", "google_compatible"):
        return False
    return bool(settings.planner_base_url and settings.planner_model)
