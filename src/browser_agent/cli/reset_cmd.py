"""`browser-agent reset` — remove home config."""

from __future__ import annotations

import argparse

from rich.prompt import Confirm

from browser_agent.cli.ux import log_ok, log_warn
from browser_agent.config import delete_home_config_file, home_config_path


def run_reset(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="browser-agent reset")
    parser.add_argument("-y", "--yes", action="store_true", help="Do not prompt")
    args = parser.parse_args(argv or [])

    path = home_config_path()
    if not path.is_file():
        log_warn(f"No config at {path}")
        return 0

    if not args.yes:
        if not Confirm.ask(f"Delete {path}?", default=False):
            log_warn("Cancelled.")
            return 1

    if delete_home_config_file():
        log_ok("Removed ~/.browser-agent/config.yaml")
    return 0
