"""Remap stale element_id references after a fresh observation (e.g. post-confirmation resume)."""

from __future__ import annotations

from browser_agent.runtime.models import AgentAction, AgentObservation, InteractiveElement


_TARGETING_SKILLS = frozenset(
    {
        "click_element",
        "type_text",
        "select_option",
        "press_key",
        "upload_file",
    }
)


def _normalize_selector(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def _interactive_candidate_keys(element: InteractiveElement) -> set[str]:
    keys = {element.selector} | set(element.selector_candidates or [])
    return {_normalize_selector(k) for k in keys if k}


def _interactive_signature_overlap(a: InteractiveElement, b: InteractiveElement) -> bool:
    """True if selector / candidate sets overlap (same DOM node across snapshots)."""

    ak = _interactive_candidate_keys(a)
    bk = _interactive_candidate_keys(b)
    return bool(ak & bk)


def _find_interactive_by_id(
    observations: list[AgentObservation],
    element_id: str,
) -> InteractiveElement | None:
    for obs in reversed(observations):
        for el in obs.interactive_elements:
            if el.element_id == element_id:
                return el
    return None


def _match_interactive_in_observation(
    pre_observation: AgentObservation,
    old: InteractiveElement,
) -> InteractiveElement | None:
    """Pick the best current element that corresponds to `old` (by selector overlap)."""

    old_primary = _normalize_selector(old.selector)
    best: InteractiveElement | None = None
    for new_el in pre_observation.interactive_elements:
        if not _interactive_signature_overlap(old, new_el):
            continue
        if _normalize_selector(new_el.selector) == old_primary:
            return new_el
        if best is None:
            best = new_el
    return best


def _fallback_selector_from_interactive(old: InteractiveElement) -> str | None:
    if old.selector and str(old.selector).strip():
        return str(old.selector)
    for candidate in old.selector_candidates or []:
        if candidate and str(candidate).strip():
            return str(candidate)
    return None


def remap_stale_element_references(
    action: AgentAction,
    pre_observation: AgentObservation,
    prior_observations: list[AgentObservation],
) -> AgentAction:
    """If `element_id` is missing from the fresh observation, remap or fall back to selector.

    Each new page snapshot assigns new random `element_id` values; after human confirmation
    the runtime re-observes, so the approved action may still reference a stale id.
    """

    if action.tool_name not in _TARGETING_SKILLS:
        return action

    params = dict(action.parameters)
    element_id = params.get("element_id")
    if not element_id or not isinstance(element_id, str):
        return action

    if any(el.element_id == element_id for el in pre_observation.interactive_elements):
        return action

    old_el = _find_interactive_by_id(prior_observations, element_id)
    if old_el is None:
        return action

    new_el = _match_interactive_in_observation(pre_observation, old_el)
    if new_el is not None:
        params["element_id"] = new_el.element_id
        return action.model_copy(update={"parameters": params})

    fallback = _fallback_selector_from_interactive(old_el)
    if fallback:
        params.pop("element_id", None)
        params["selector"] = fallback
        return action.model_copy(update={"parameters": params})

    return action
