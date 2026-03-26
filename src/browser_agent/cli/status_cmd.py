"""`browser-agent status` — quick summary."""

from __future__ import annotations

import sys

from browser_agent import __version__
from browser_agent.config import (
    home_config_path,
    load_home_config_file,
    planner_env_configured,
    RuntimeSettings,
)


def run_status() -> int:
    print(f"browser-agent {__version__}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    path = home_config_path()
    print(f"Config: {path} ({'exists' if path.is_file() else 'missing'})")
    cfg = load_home_config_file()
    if cfg:
        print(f"  provider: {cfg.provider}")
        print(f"  base_url: {cfg.base_url}")
        print(f"  model: {cfg.model}")
        print("  api_key: (set)" if cfg.api_key.strip() else "  api_key: (empty)")
    settings = RuntimeSettings.from_env()
    ok = planner_env_configured(settings)
    print(f"Planner ready: {'yes' if ok else 'no'}")
    return 0
