"""Rich layout builders for Agent Console (pure functions from state)."""

from __future__ import annotations

from rich import box
from rich.console import Group
from rich.layout import Layout
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from browser_agent.ui.formatting import (
    format_step_line_compact,
    humanize_result_status,
    humanize_skill_name,
    truncate_text,
)
from browser_agent.ui.models import AgentConsoleState, TimelineStepView

PALETTE = {
    "bg": "#0B0F10",
    "fg": "#E6EDF3",
    "muted": "#8B949E",
    "border": "#2A3136",
    "accent": "#7CFF5B",
    "info": "#35C2FF",
    "warning": "#FFCC66",
    "danger": "#FF6B6B",
    "panel": "#12181B",
}


def _phase_markup(phase: str) -> str:
    """Colored phase label for top bar."""
    p = phase.upper()
    styles = {
        "IDLE": PALETTE["muted"],
        "OBSERVE": PALETTE["info"],
        "PLAN": PALETTE["info"],
        "GUARDRAIL": PALETTE["warning"],
        "ACT": PALETTE["accent"],
        "WAITING_CONFIRMATION": PALETTE["warning"],
        "WAITING_USER": PALETTE["info"],
        "FINISHED": f"bold {PALETTE['accent']}",
        "FAILED": f"bold {PALETTE['danger']}",
    }
    st = styles.get(p, PALETTE["fg"])
    return f"[{st}]{p}[/{st}]"


def _top_bar(state: AgentConsoleState) -> Panel:
    task = escape(truncate_text(state.task, 68))
    status_style = (
        PALETTE["warning"]
        if state.status == "waiting"
        else PALETTE["accent"]
        if state.status == "running"
        else PALETTE["danger"]
        if state.status == "failed"
        else PALETTE["fg"]
    )
    step_disp = escape(state.step_display or "—")
    model_disp = escape(state.model_name or "—")
    line1 = f"[bold]Task[/] {task}"
    phase = _phase_markup(state.display_phase)
    summary_raw = (truncate_text(state.human_summary, 140) or "").strip()
    if not summary_raw:
        narrative = f"[{PALETTE['muted']}]…[/]"
    else:
        narrative = f"[italic]{escape(summary_raw)}[/italic]"
    line2 = (
        f"[{status_style} bold]{state.status.upper()}[/]   "
        f"│   [bold]Phase[/] {phase}   "
        f"│   [bold]Step[/] {step_disp}   "
        f"│   [bold]Model[/] {model_disp}"
    )
    line3 = f"[bold]Now[/] {narrative}"
    body = Text.from_markup(f"{line1}\n{line2}")
    if state.ui_mode == "demo":
        body = Text.from_markup(f"{line1}\n{line2}\n{line3}")
    return Panel(
        body,
        box=box.ROUNDED,
        title="[bold]Agent Console[/]",
        padding=(0, 1),
        border_style=PALETTE["border"],
    )


def _status_panel(state: AgentConsoleState) -> Panel:
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(style=PALETTE["info"], justify="right")
    tbl.add_column(style=PALETTE["fg"])
    approx = " [dim](estimated)[/]" if state.tokens_approximate else ""
    cost = (
        f"${state.estimated_cost_usd:.4f}"
        if state.estimated_cost_usd is not None
        else "N/A"
    )
    if state.tokens_approximate and state.estimated_cost_usd is not None:
        cost += " [dim](approx)[/]"
    dur = "—"
    if state.run_started_at is not None:
        from datetime import datetime, timezone

        delta = datetime.now(timezone.utc) - state.run_started_at
        sec = int(delta.total_seconds())
        dur = f"{sec // 60:02d}:{sec % 60:02d}"
    lat = "—"
    if state.llm_latency_count > 0:
        avg = state.llm_latency_sum_ms / state.llm_latency_count
        lat = f"{avg:.0f} ms{approx}"

    tbl.add_row("URL", escape(truncate_text(state.current_url or "—", 72)))
    tbl.add_row("Title", escape(truncate_text(state.page_title or "—", 60)))
    tbl.add_row("[bold]Tokens[/]", "")
    tbl.add_row("Model", f"{escape(state.model_name or '—')}{approx}")
    tbl.add_row("Requests", str(state.llm_request_count))
    tbl.add_row("Prompt", f"{state.prompt_tokens_total:,}{approx}")
    tbl.add_row("Completion", f"{state.completion_tokens_total:,}{approx}")
    tbl.add_row("Total", f"{state.total_tokens_total:,}{approx}")
    tbl.add_row("Est. cost", cost)
    tbl.add_row("Latency avg", lat)
    tbl.add_row("Duration", dur)
    return Panel(
        tbl,
        title="Status & tokens",
        border_style=PALETTE["info"],
        box=box.ROUNDED,
    )


def _error_panel(state: AgentConsoleState) -> Panel | None:
    if not state.error_title:
        return None
    hint = state.error_hint or ""
    body = (
        f"[bold red]ERROR[/] [bold]{escape(state.error_title)}[/]\n"
        f"{escape(state.error_explanation or '—')}"
    )
    if hint:
        body += f"\n[dim]Hint:[/] {escape(hint)}"
    return Panel(
        Text.from_markup(body),
        title="Issue",
        border_style=PALETTE["danger"],
        box=box.ROUNDED,
    )


def _timeline_panel(state: AgentConsoleState) -> Panel:
    if not state.timeline:
        return Panel(
            Text("Waiting for steps…", style="dim"),
            title="Steps (latest)",
            border_style=PALETTE["accent"],
            box=box.ROUNDED,
        )
    body = "\n\n".join(_format_step_card(s) for s in state.timeline)
    return Panel(
        Text.from_markup(body),
        title="Steps (latest)",
        border_style=PALETTE["accent"],
        box=box.ROUNDED,
    )


def _format_step_card(step: TimelineStepView) -> str:
    tgt = escape(truncate_text(step.target_summary or "—", 90))
    res = escape(step.result_display or humanize_result_status(step.result_status))
    prog = escape(truncate_text(step.progress_note or "—", 100))
    exp = escape(truncate_text(step.expected_outcome or "—", 100))
    reason = escape(truncate_text(step.rationale_summary, 120))
    sk = escape(step.skill_display or humanize_skill_name(step.skill_name))
    phase = escape(step.phase_label or "—")
    return (
        f"[bold {PALETTE['info']}]Step {step.step_number + 1}[/]   "
        f"[{PALETTE['warning']}]{phase}[/]\n"
        f"  [dim]Reason[/]     {reason}\n"
        f"  [dim]Skill[/]      {sk}\n"
        f"  [dim]Target[/]     {tgt}\n"
        f"  [dim]Expected[/]   {exp}\n"
        f"  [dim]Result[/]     {res}\n"
        f"  [dim]Progress[/]   {prog}"
    )


def _right_panel(state: AgentConsoleState) -> Panel:
    obs = state.observation_summary or "—"
    obs = escape(truncate_text(obs, 420))
    warns = escape(
        "\n".join(f"• {truncate_text(w, 72)}" for w in state.observation_warnings[:6]) or "—"
    )
    dec = escape(state.last_decision_type or "—")
    rat = escape(truncate_text(state.last_rationale or "—", 220))
    tbl = Table.grid(padding=(0, 1))
    tbl.add_row("[bold]Observation[/]", obs)
    tbl.add_row("[bold]Interactive[/]", str(state.interactive_element_count))
    tbl.add_row("[bold]Warnings[/]", warns)
    tbl.add_row("[bold]Last decision[/]", f"{dec}\n{rat}")
    return Panel(
        tbl,
        title="Current state",
        border_style=PALETTE["warning"],
        box=box.ROUNDED,
    )


def _current_action_panel(state: AgentConsoleState) -> Panel:
    why = escape(truncate_text(state.last_rationale or "Working through the next safe step.", 180))
    expected = escape(
        truncate_text(state.last_expected_outcome or "Waiting for a visible success signal.", 180)
    )
    now = escape(truncate_text(state.human_summary or "Working…", 180))
    body = Text.from_markup(
        f"[bold]Current action[/]\n{now}\n\n"
        f"[bold]Why[/]\n{why}\n\n"
        f"[bold]Expected[/]\n{expected}"
    )
    return Panel(
        body,
        title="Execution focus",
        border_style=PALETTE["accent"],
        box=box.ROUNDED,
    )


def _recent_progress_panel(state: AgentConsoleState) -> Panel:
    steps = state.timeline[-3:]
    if not steps:
        body = Text("Waiting for the first completed step…", style=PALETTE["muted"])
    else:
        lines = "\n".join(format_step_line_compact(step) for step in steps)
        body = Text(lines, style=PALETTE["fg"])
    return Panel(
        body,
        title="Recent progress",
        border_style=PALETTE["info"],
        box=box.ROUNDED,
    )


def _compact_state_panel(state: AgentConsoleState) -> Panel:
    url = escape(truncate_text(state.current_url or "—", 72))
    title = escape(truncate_text(state.page_title or "—", 48))
    warnings = state.observation_warnings[:2]
    warning_line = (
        "\n".join(f"• {truncate_text(w, 56)}" for w in warnings) if warnings else "None"
    )
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(style=PALETTE["info"], justify="right")
    tbl.add_column(style=PALETTE["fg"])
    tbl.add_row("URL", url)
    tbl.add_row("Page", title)
    tbl.add_row("Interactive", str(state.interactive_element_count))
    if warnings:
        tbl.add_row("Warnings", warning_line)
    return Panel(
        tbl,
        title="State",
        border_style=PALETTE["border"],
        box=box.ROUNDED,
    )


def _bottom_panel(state: AgentConsoleState) -> Panel:
    if state.bottom_mode == "confirm":
        cons = escape(
            "\n".join(f"  • {truncate_text(c, 76)}" for c in state.confirm_consequences) or "  —"
        )
        body = (
            f"[bold red]CONFIRMATION REQUIRED[/]\n\n"
            f"[bold]Action:[/] {escape(state.confirm_action or '—')}\n"
            f"[bold]Reason:[/] {escape(truncate_text(state.confirm_reason, 200))}\n"
            f"[bold]Context:[/]\n{cons}\n\n"
            f"[green][Y][/] Yes    [red][N][/] No"
        )
        return Panel(
            Text.from_markup(body),
            title="Confirmation",
            border_style=PALETTE["danger"],
            box=box.ROUNDED,
        )
    if state.bottom_mode == "input":
        body = (
            f"[bold cyan]AGENT NEEDS INPUT[/]\n\n"
            f"[bold]Question:[/]\n{escape(truncate_text(state.input_question, 400))}\n\n"
            "[dim]This box is read-only. When input is needed, the live view pauses and you type "
            "in the separate prompt on the main terminal (below), not here.[/]"
        )
        return Panel(
            Text.from_markup(body),
            title="Question",
            border_style=PALETTE["info"],
            box=box.ROUNDED,
        )
    if state.ui_mode == "demo":
        body = (
            "[bold white]Running autonomously.[/]\n"
            "[dim]The dashboard pauses only when approval or your input is required.[/]"
        )
        return Panel(
            Text.from_markup(body),
            title="Operator",
            border_style=PALETTE["border"],
            box=box.ROUNDED,
        )
    body = (
        "[bold white]Status only — not a text field.[/]\n"
        "[white]Do not type while the agent is running; keys are not read here and may flicker under the layout.[/]\n\n"
        "[dim]When the runtime pauses, the dashboard pauses and you answer in the separate prompt for:[/]\n"
        "  [cyan]•[/] [white]Safety confirmation[/] [dim]— Y/N[/]\n"
        "  [cyan]•[/] [white]Planner ask_user[/] [dim]— free text[/]"
    )
    return Panel(
        Text.from_markup(body),
        title="Operator",
        border_style=PALETTE["border"],
        box=box.ROUNDED,
    )


def _center_stack(state: AgentConsoleState) -> Layout:
    err = _error_panel(state)
    if err is None:
        lay = Layout()
        lay.update(_timeline_panel(state))
        return lay
    layout = Layout()
    layout.split_column(
        Layout(name="err", size=9),
        Layout(name="steps", ratio=1),
    )
    layout["err"].update(err)
    layout["steps"].update(_timeline_panel(state))
    return layout


def build_layout(state: AgentConsoleState, width: int | None = None) -> Layout:
    """Main operator layout with mode-aware presentation."""
    if state.ui_mode == "demo":
        return build_layout_demo(state)
    return build_layout_debug(state, width=width)


def build_layout_demo(state: AgentConsoleState) -> Layout:
    bottom_size = 8 if state.bottom_mode in {"confirm", "input"} else 5
    layout = Layout()
    layout.split_column(
        Layout(name="top", size=5),
        Layout(name="hero", size=9),
        Layout(name="progress", size=6),
        Layout(name="state", size=7),
        Layout(name="bottom", size=bottom_size),
    )
    layout["top"].update(_top_bar(state))
    layout["hero"].update(_current_action_panel(state))
    layout["progress"].update(_recent_progress_panel(state))
    if state.error_title:
        layout["state"].update(
            Group(
                _error_panel(state),
                _compact_state_panel(state),
            )
        )
    else:
        layout["state"].update(_compact_state_panel(state))
    layout["bottom"].update(_bottom_panel(state))
    return layout


def build_layout_debug(state: AgentConsoleState, width: int | None = None) -> Layout:
    """Debug operator layout, adaptive to terminal width."""
    if width is not None and width < 110:
        layout = Layout()
        layout.split_column(
            Layout(name="top", size=5),
            Layout(name="status", size=13),
            Layout(name="center", ratio=1),
            Layout(name="right", size=12),
            Layout(name="bottom", size=12),
        )
        layout["top"].update(_top_bar(state))
        layout["status"].update(_status_panel(state))
        layout["center"].update(_center_stack(state))
        layout["right"].update(_right_panel(state))
        layout["bottom"].update(_bottom_panel(state))
        return layout
    if width is not None and width < 150:
        layout = Layout()
        layout.split_column(
            Layout(name="top", size=5),
            Layout(name="middle", ratio=1),
            Layout(name="bottom", size=12),
        )
        layout["top"].update(_top_bar(state))
        layout["middle"].split_row(
            Layout(name="main", ratio=2),
            Layout(name="side", ratio=1),
        )
        layout["middle"]["main"].update(_center_stack(state))
        layout["middle"]["side"].split_column(
            Layout(name="status", ratio=1),
            Layout(name="state", ratio=1),
        )
        layout["middle"]["side"]["status"].update(_status_panel(state))
        layout["middle"]["side"]["state"].update(_right_panel(state))
        layout["bottom"].update(_bottom_panel(state))
        return layout

    layout = Layout()
    layout.split_column(
        Layout(name="top", size=5),
        Layout(name="middle", ratio=1),
        Layout(name="bottom", size=12),
    )
    layout["top"].update(_top_bar(state))
    layout["middle"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="center", ratio=2),
        Layout(name="right", ratio=1),
    )
    layout["middle"]["left"].update(_status_panel(state))
    layout["middle"]["center"].update(_center_stack(state))
    layout["middle"]["right"].update(_right_panel(state))
    layout["bottom"].update(_bottom_panel(state))
    return layout


def build_final_summary_panel(state: AgentConsoleState) -> Panel:
    lines = state.final_summary_lines
    if not lines:
        body = Text("Done.")
        return Panel(body, title="[bold]Run summary[/]", border_style="magenta", box=box.DOUBLE)
    text = Text()
    headline = lines[0]
    st = state.status.lower()
    head_style = "bold red" if st == "failed" else "bold green" if st == "completed" else "bold yellow"
    text.append(headline + "\n", style=head_style)
    for line in lines[1:]:
        text.append(line + "\n")
    border = "red" if st == "failed" else "green" if st == "completed" else "yellow"
    return Panel(
        text,
        title="[bold]Run summary[/]",
        border_style=border,
        box=box.DOUBLE,
    )
