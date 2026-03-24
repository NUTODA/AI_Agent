"""Package entrypoint for the browser agent foundation."""

from __future__ import annotations

from browser_agent.cli.app import main as cli_main


def main() -> int:
    """Run the CLI entrypoint."""

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
