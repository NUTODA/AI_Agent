"""Planner-driven bootstrap for bare browser-agent runs."""

from __future__ import annotations

import json
import re
from argparse import Namespace
from textwrap import dedent
from typing import Literal
from urllib.parse import quote_plus, urlparse

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
BRAND_HINT_PATTERN = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9._-]{2,}")
LOCAL_INTENT_PATTERN = re.compile(
    r"\b(закаж|куп|каталог|меню|товар|достав|ресторан|суши|пицц|аптек|магазин|"
    r"официальн|official|menu|catalog|store|shop|restaurant|delivery|book)\w*\b",
    re.IGNORECASE,
)
LOCATION_HINT_PATTERN = re.compile(
    r"\b(в|во|на|по|рядом|near|in)\s+[A-Za-zА-Яа-яЁё0-9-]{2,}",
    re.IGNORECASE,
)


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
    decision = planner.decide(task_text)
    if decision is None:
        return None
    return _normalize_bootstrap_decision(task_text, decision)


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


def _normalize_bootstrap_decision(
    task_text: str,
    decision: BootstrapDecision,
) -> BootstrapDecision:
    if (
        decision.mode == "search_url"
        and decision.target_url
        and _should_avoid_google_bootstrap(task_text, decision.target_url)
    ):
        query = _build_non_google_search_query(task_text)
        return decision.model_copy(
            update={
                "target_url": f"https://duckduckgo.com/?q={quote_plus(query)}",
                "reason_summary": (
                    decision.reason_summary
                    or "Using a lower-friction search bootstrap for a branded task."
                ),
            }
        )
    return decision


def _should_avoid_google_bootstrap(task_text: str, target_url: str) -> bool:
    hostname = (urlparse(target_url).hostname or "").lower()
    return "google." in hostname and _looks_like_brand_or_local_task(task_text)


def _looks_like_brand_or_local_task(task_text: str) -> bool:
    normalized = task_text.strip()
    if not normalized:
        return False
    return bool(
        LOCAL_INTENT_PATTERN.search(normalized)
        or LOCATION_HINT_PATTERN.search(normalized)
        or _extract_brandish_tokens(normalized)
    )


def _build_non_google_search_query(task_text: str) -> str:
    query = task_text.strip()
    if not query:
        return "official site"
    if _extract_brandish_tokens(query):
        return f"{query} официальный сайт"
    return query


def _extract_brandish_tokens(task_text: str) -> list[str]:
    tokens = BRAND_HINT_PATTERN.findall(task_text)
    stopwords = {
        "закажи",
        "заказать",
        "закажем",
        "найди",
        "найти",
        "открой",
        "посмотри",
        "купить",
        "меню",
        "каталог",
        "доставка",
        "ресторан",
        "суши",
        "роллов",
        "роллы",
        "пицца",
        "магазин",
        "официальный",
        "official",
        "site",
        "store",
        "shop",
        "near",
        "рядом",
        "питере",
        "петербурге",
        "москве",
    }
    return [
        token
        for token in tokens
        if token.lower() not in stopwords and len(token) >= 4
    ][:4]


def _build_bootstrap_messages(task_text: str) -> list[LLMMessage]:
    brand_hint = ", ".join(_extract_brandish_tokens(task_text)) or "none"
    local_intent = "yes" if _looks_like_brand_or_local_task(task_text) else "no"
    system = dedent(
        f"""
        You are a bootstrap planner for a browser agent.

        Your only job is to decide what page should be opened first for the task.

        Return exactly one JSON object with this schema:
        {{
          "mode": "direct_url" | "search_url" | "none",
          "target_url": "https://...",
          "confidence": 0.0,
          "reason_summary": "short explanation"
        }}

        Rules:
        - Prefer `direct_url` when the task clearly refers to a known specific site or official page.
        - Treat named brands, stores, restaurants, catalogs, and local-service requests as strong hints toward an official site.
        - For branded or catalog tasks, avoid Google result pages as the first hop when a plausible official site can be opened directly.
        - Use `search_url` when you are not confident enough to open one specific site directly.
        - Use `none` only if opening a page first would be misleading or unnecessary.
        - If mode is `direct_url` or `search_url`, `target_url` must be a full absolute URL.
        - If mode is `search_url`, provide a search engine URL that encodes a useful query for the task. Prefer lower-friction search engines over Google when the task is branded or local.
        - Keep `reason_summary` concise and user-facing.
        - Do not ask follow-up questions.
        - Do not include markdown or extra text.

        Task hints:
        - brand_like_tokens: {brand_hint}
        - branded_or_local_intent: {local_intent}
        """
    ).strip()
    user = f"Task: {task_text}"
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
