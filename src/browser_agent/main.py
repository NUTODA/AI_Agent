"""Package entrypoint for the browser agent foundation."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from browser_agent.cli.app import main as cli_main


def _load_dotenv_files() -> None:
    """Load `.env` then `.env.browser-agent` from the current working directory."""

    cwd = Path.cwd()
    for name in (".env", ".env.browser-agent"):
        path = cwd / name
        if path.is_file():
            load_dotenv(path, override=True)


def main() -> int:
    """Run the CLI entrypoint."""

    _load_dotenv_files()
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
