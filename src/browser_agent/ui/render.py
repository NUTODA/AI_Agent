"""Rich layout builders for Agent Console (pure functions from state)."""

from __future__ import annotations

from rich import box
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from browser_agent.ui.models import AgentConsoleState, TimelineStepView


def _top_bar(state: AgentConsoleState) -> Panel:
    task = state.task[:70] + ("…" if len(state.task) > 70 else "")
    line = (
        f"[bold]Task[/] {task}   │   [bold]Status[/] {state.status.upper()}   │   "
        f"[bold]Step[/] {state.step_display}   │   [bold]Phase[/] {state.phase}   │   "
        f"[bold]Model[/] {state.model_name or '—'} "
        f"({state.provider_kind or '—'})"
    )
    return Panel(Text.from_markup(line), box=box.ROUNDED, title="Agent Console", padding=(0, 1))


def _status_panel(state: AgentConsoleState) -> Panel:
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(style="cyan", justify="right")
    tbl.add_column(style="white")
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
    tbl.add_row("URL", state.current_url or "—")
    tbl.add_row("Title", (state.page_title or "—")[:60])
    tbl.add_row("Tokens (total)", f"{state.total_tokens_total:,}{approx}")
    tbl.add_row("Requests", str(state.llm_request_count))
    tbl.add_row("Est. cost", cost)
    tbl.add_row("Duration", dur)
    return Panel(tbl, title="Status", border_style="blue", box=box.ROUNDED)


def _timeline_panel(state: AgentConsoleState) -> Panel:
    if not state.timeline:
        return Panel(
            Text("Waiting for steps…", style="dim"),
            title="Steps (latest)",
            border_style="green",
            box=box.ROUNDED,
        )
    body = "\n\n".join(_format_step_card(s) for s in state.timeline)
    return Panel(
        Text.from_markup(body),
        title="Steps (latest)",
        border_style="green",
        box=box.ROUNDED,
    )


def _format_step_card(step: TimelineStepView) -> str:
    tgt = step.target_summary or "—"
    res = step.result_status or "—"
    prog = step.progress_note or "—"
    exp = step.expected_outcome or "—"
    return (
        f"[bold magenta]Step {step.step_number + 1}[/] [yellow]{step.phase_label}[/]\n"
        f"  [bold]Reason:[/] {step.rationale_summary}\n"
        f"  [bold]Expected:[/] {exp}\n"
        f"  [bold]Skill:[/] {step.skill_name or '—'}\n"
        f"  [bold]Target:[/] {tgt}\n"
        f"  [bold]Result:[/] {res}\n"
        f"  [bold]Progress:[/] {prog}"
    )


def _right_panel(state: AgentConsoleState) -> Panel:
    obs = state.observation_summary or "—"
    if len(obs) > 500:
        obs = obs[:497] + "..."
    warns = "\n".join(f"• {w}" for w in state.observation_warnings[:6]) or "—"
    dec = state.last_decision_type or "—"
    rat = state.last_rationale or "—"
    if len(rat) > 280:
        rat = rat[:277] + "..."
    tbl = Table.grid(padding=(0, 1))
    tbl.add_row("[bold]Observation[/]", obs)
    tbl.add_row("[bold]Interactive elements[/]", str(state.interactive_element_count))
    tbl.add_row("[bold]Warnings[/]", warns)
    tbl.add_row("[bold]Last decision[/]", f"{dec}\n{rat}")
    return Panel(tbl, title="Current state", border_style="yellow", box=box.ROUNDED)


def _bottom_panel(state: AgentConsoleState) -> Panel:
    if state.bottom_mode == "confirm":
        cons = "\n".join(f"  • {c}" for c in state.confirm_consequences) or "  —"
        body = (
            f"[bold red]CONFIRMATION REQUIRED[/]\n\n"
            f"[bold]Action:[/] {state.confirm_action}\n"
            f"[bold]Reason:[/] {state.confirm_reason}\n"
            f"[bold]Context:[/]\n{cons}\n\n"
            f"[green][Y][/] Yes    [red][N][/] No"
        )
        return Panel(Text.from_markup(body), title="Input", border_style="red", box=box.ROUNDED)
    if state.bottom_mode == "input":
        body = (
            f"[bold cyan]AGENT NEEDS INPUT[/]\n\n"
            f"[bold]Question:[/]\n{state.input_question}\n\n"
            f"[dim]Answer when prompted below…[/]"
        )
        return Panel(Text.from_markup(body), title="Input", border_style="cyan", box=box.ROUNDED)
    return Panel(
        Text.from_markup("[dim]Idle — running or waiting for next event…[/]"),
        title="Input",
        border_style="dim",
        box=box.ROUNDED,
    )


def build_layout(state: AgentConsoleState) -> Layout:
    """Main operator layout: top, middle (3 cols), bottom."""
    layout = Layout()
    layout.split_column(
        Layout(name="top", size=3),
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
    layout["middle"]["center"].update(_timeline_panel(state))
    layout["middle"]["right"].update(_right_panel(state))
    layout["bottom"].update(_bottom_panel(state))
    return layout


def build_final_summary_panel(state: AgentConsoleState) -> Panel:
    body = "\n".join(state.final_summary_lines) or "Done."
    return Panel(
        Text(body, overflow="fold"),
        title="[bold]RUN SUMMARY[/]",
        border_style="magenta",
        box=box.DOUBLE,
    )
