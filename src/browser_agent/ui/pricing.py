"""Best-effort USD estimates from token counts (demo only)."""

from __future__ import annotations

# Rough $/1K tokens (input, output) — update as needed; unknown models return None.
_MODEL_RATES_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "gemini-flash-latest": (0.000075, 0.0003),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini-1.5-pro": (0.00125, 0.005),
}


def estimate_cost_usd(
    model_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    if not model_name or prompt_tokens < 0 or completion_tokens < 0:
        return None
    key = model_name.strip().lower()
    rates = _MODEL_RATES_PER_1K.get(key)
    if rates is None:
        for prefix, r in _MODEL_RATES_PER_1K.items():
            if key.startswith(prefix) or prefix in key:
                rates = r
                break
    if rates is None:
        return None
    inp, out = rates
    return (prompt_tokens / 1000.0) * inp + (completion_tokens / 1000.0) * out
