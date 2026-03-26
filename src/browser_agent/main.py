"""Package entrypoint for the browser agent foundation."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from browser_agent.config import apply_home_config_to_environment


def _load_dotenv_files() -> None:
    """Load `.env` then `.env.browser-agent` from the current working directory."""

    cwd = Path.cwd()
    for name in (".env", ".env.browser-agent"):
        path = cwd / name
        if path.is_file():
            # Later file wins; values override home config and earlier .env keys.
            load_dotenv(path, override=True)


def main() -> int:
    """Run the CLI entrypoint (console script target)."""

    apply_home_config_to_environment()
    _load_dotenv_files()
    from browser_agent.cli.main import app

    return app()
