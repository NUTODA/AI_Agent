"""Bundled local demo pages and HTTP server for offline demos."""

from __future__ import annotations

from pathlib import Path


def demo_pages_dir() -> Path:
    """Directory containing static demo HTML (works from source tree and wheel)."""

    return Path(__file__).resolve().parent / "pages"


__all__ = ["demo_pages_dir"]
