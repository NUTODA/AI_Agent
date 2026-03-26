#!/usr/bin/env python3
"""Locate planner `fail` steps in a session JSONL trace.

Each line is one ExecutionTraceItem (JSON). Prints entries where
`planner_decision_type` is `fail`, or where `report_summary` matches
an optional substring.

For the companion Markdown trace, open the same session's `session_<id>.md`:
- **Final Summary** repeats the last line's `report_summary` (exact failure text).
- **Step N** in the file uses N = step_index + 1.

Example:
  python scripts/find_planner_failure_in_trace.py traces/session_800514ee0096.jsonl
  python scripts/find_planner_failure_in_trace.py traces/session_800514ee0096.jsonl \\
      --contains "JSON object"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "jsonl",
        type=Path,
        help="Path to session_*.jsonl",
    )
    p.add_argument(
        "--contains",
        metavar="TEXT",
        default=None,
        help="Only show rows whose report_summary contains TEXT",
    )
    args = p.parse_args()
    path: Path = args.jsonl
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 1

    needle = args.contains
    matches: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"{path}:{line_no}: invalid JSON: {exc}", file=sys.stderr)
                return 1
            if row.get("planner_decision_type") != "fail":
                continue
            summary = row.get("report_summary") or ""
            if needle is not None and needle not in summary:
                continue
            matches.append(row)

    if not matches:
        print("No matching trace rows.")
        return 0

    for row in matches:
        si = row.get("step_index")
        summary = row.get("report_summary")
        st = row.get("state_transition")
        pdt = row.get("planner_decision_type")
        human = (si + 1) if isinstance(si, int) else "?"
        print(f"step_index={si} (Step {human} in session_*.md)")
        print(f"  planner_decision_type={pdt!r}")
        print(f"  state_transition={st!r}")
        print(f"  report_summary={summary!r}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
