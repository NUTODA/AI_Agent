"""Runtime package exports."""

from __future__ import annotations

__all__ = ["RuntimeLoop", "RuntimeSession", "TraceRecorder"]


def __getattr__(name: str):
    if name == "RuntimeLoop":
        from browser_agent.runtime.loop import RuntimeLoop

        return RuntimeLoop
    if name == "RuntimeSession":
        from browser_agent.runtime.session import RuntimeSession

        return RuntimeSession
    if name == "TraceRecorder":
        from browser_agent.runtime.trace import TraceRecorder

        return TraceRecorder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
