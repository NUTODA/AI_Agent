"""Planner-driven bootstrap for bare browser-agent runs."""

from __future__ import annotations

import json
import re
from argparse import Namespace
from textwrap import dedent
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from browser_agent.config import RuntimeSettings
from browser_agent.llm.provider import (
    GoogleGenerativeLanguageProvider,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    OpenAICompatibleProvider,
)

DOMAIN_PATTERN = re.compile(
    r"(?P<domain>(?:[a-z0-9-]+\.)+[a-z]{2,})(?P<path>/[^\s]*)?",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)


class BootstrapDecision(BaseModel):
    """Typed bootstrap decision for the first page the agent should open."""

    mode: Literal["direct_url", "search_url", "none"]
    target_url: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_summary: str = ""


class BootstrapPlanner:
    """Small planner that chooses an initial URL before the main runtime starts."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings

    def decide(self, task_text: str) -> BootstrapDecision | None:
        if not self._settings.planner_enabled:
            return None
        if not self._settings.planner_base_url or not self._settings.planner_model:
            return None

        provider = self._build_provider()
        response = provider.complete(
            LLMRequest(
                messages=_build_bootstrap_messages(task_text),
                response_format={"type": "json_object"},
            )
        )
        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"Bootstrap planner returned non-JSON content: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise LLMProviderError("Bootstrap planner returned a non-object payload.")

        try:
            decision = BootstrapDecision.model_validate(payload)
        except ValidationError as exc:
            raise LLMProviderError(
                f"Bootstrap planner returned an invalid decision: {exc}"
            ) from exc

        if decision.mode in {"direct_url", "search_url"} and not decision.target_url:
            raise LLMProviderError(
                "Bootstrap planner omitted `target_url` for a URL-opening decision."
            )
        return decision

    def _build_provider(
        self,
    ) -> OpenAICompatibleProvider | GoogleGenerativeLanguageProvider:
        if self._settings.planner_provider == "google_compatible":
            return GoogleGenerativeLanguageProvider(
                base_url=self._settings.planner_base_url or "",
                model_name=self._settings.planner_model or "",
                api_key=self._settings.planner_api_key,
                timeout_seconds=self._settings.planner_timeout_seconds,
                max_retries=self._settings.planner_retries,
                retry_backoff_seconds=self._settings.planner_retry_backoff_seconds,
                temperature=self._settings.planner_temperature,
            )
        return OpenAICompatibleProvider(
            base_url=self._settings.planner_base_url or "",
            model_name=self._settings.planner_model or "",
            api_key=self._settings.planner_api_key,
            timeout_seconds=self._settings.planner_timeout_seconds,
            max_retries=self._settings.planner_retries,
            retry_backoff_seconds=self._settings.planner_retry_backoff_seconds,
            temperature=self._settings.planner_temperature,
        )


def apply_smart_bootstrap(args: Namespace, *, bare_mode: bool) -> Namespace:
    """Apply product-friendly defaults for natural-language entrypoint usage."""

    if getattr(args, "json", False):
        return args

    updates: dict[str, object] = {}

    if bare_mode:
        if not getattr(args, "ui", False):
            updates["ui"] = True
        if not getattr(args, "headed", False):
            updates["headed"] = True

    if not getattr(args, "start_url", None):
        task_text = " ".join(getattr(args, "task", []) or []).strip()
        settings = RuntimeSettings.from_env()
        decision = resolve_bootstrap_decision(task_text, settings=settings)
        if decision is not None and decision.target_url:
            updates["start_url"] = decision.target_url

    if not updates:
        return args
    return Namespace(**{**vars(args), **updates})


def resolve_bootstrap_decision(
    task_text: str,
    *,
    settings: RuntimeSettings,
) -> BootstrapDecision | None:
    """Resolve a starting page for the task."""

    explicit = infer_explicit_start_url(task_text)
    if explicit:
        return BootstrapDecision(
            mode="direct_url",
            target_url=explicit,
            confidence=1.0,
            reason_summary="The user request already contains a concrete URL or domain.",
        )

    planner = BootstrapPlanner(settings)
    return planner.decide(task_text)


def infer_explicit_start_url(task_text: str) -> str | None:
    """Return a start URL only for explicit URLs or domains present in the task text."""

    text = task_text.strip()
    if not text:
        return None

    explicit_url = URL_PATTERN.search(text)
    if explicit_url:
        return explicit_url.group(0)

    domain_match = DOMAIN_PATTERN.search(text)
    if domain_match:
        domain = domain_match.group("domain").lower()
        path = domain_match.group("path") or ""
        return f"https://{domain}{path}"

    return None


def _build_bootstrap_messages(task_text: str) -> list[LLMMessage]:
    system = dedent(
        """
        You are a bootstrap planner for a browser agent.

        Your only job is to decide what page should be opened first for the task.

        Return exactly one JSON object with this schema:
        {
          "mode": "direct_url" | "search_url" | "none",
          "target_url": "https://...",
          "confidence": 0.0,
          "reason_summary": "short explanation"
        }

        Rules:
        - Prefer `direct_url` when the task clearly refers to a known specific site or official page.
        - Use `search_url` when you are not confident enough to open one specific site directly.
        - Use `none` only if opening a page first would be misleading or unnecessary.
        - If mode is `direct_url` or `search_url`, `target_url` must be a full absolute URL.
        - If mode is `search_url`, provide a search engine URL that encodes a useful query for the task.
        - Keep `reason_summary` concise and user-facing.
        - Do not ask follow-up questions.
        - Do not include markdown or extra text.
        """
    ).strip()
    user = f"Task: {task_text}"
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
