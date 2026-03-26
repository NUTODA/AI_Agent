"""Rich layout builders for Agent Console (pure functions from state)."""

from __future__ import annotations

from rich import box
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from browser_agent.ui.formatting import humanize_result_status, humanize_skill_name, truncate_text
from browser_agent.ui.models import AgentConsoleState, TimelineStepView


def _phase_markup(phase: str) -> str:
    """Colored phase label for top bar."""
    p = phase.upper()
    styles = {
        "IDLE": "dim",
        "OBSERVE": "cyan",
        "PLAN": "blue",
        "GUARDRAIL": "yellow",
        "ACT": "green",
        "WAITING_CONFIRMATION": "magenta",
        "WAITING_USER": "bright_cyan",
        "FINISHED": "bold green",
        "FAILED": "bold red",
    }
    st = styles.get(p, "white")
    return f"[{st}]{p}[/{st}]"


def _top_bar(state: AgentConsoleState) -> Panel:
    task = truncate_text(state.task, 68)
    status_style = (
        "yellow"
        if state.status == "waiting"
        else "green"
        if state.status == "running"
        else "red"
        if state.status == "failed"
        else "white"
    )
    line1 = (
        f"[bold]Task[/] {task}   │   [{status_style}]{state.status.upper()}[/]   │   "
        f"[bold]Step[/] {state.step_display}   │   "
        f"[bold]Model[/] {state.model_name or '—'} [dim]({state.provider_kind or '—'})[/]"
    )
    phase = _phase_markup(state.display_phase)
    narrative = truncate_text(state.human_summary, 140) or "[dim]…[/]"
    line2 = f"[bold]Phase[/] {phase}   │   [italic]{narrative}[/italic]"
    body = Text.from_markup(f"{line1}\n{line2}")
    return Panel(body, box=box.ROUNDED, title="Agent Console", padding=(0, 1))


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
    lat = "—"
    if state.llm_latency_count > 0:
        avg = state.llm_latency_sum_ms / state.llm_latency_count
        lat = f"{avg:.0f} ms{approx}"

    tbl.add_row("URL", truncate_text(state.current_url or "—", 72))
    tbl.add_row("Title", truncate_text(state.page_title or "—", 60))
    tbl.add_row("[bold]Tokens[/]", "")
    tbl.add_row("Model", f"{state.model_name or '—'}{approx}")
    tbl.add_row("Requests", str(state.llm_request_count))
    tbl.add_row("Prompt", f"{state.prompt_tokens_total:,}{approx}")
    tbl.add_row("Completion", f"{state.completion_tokens_total:,}{approx}")
    tbl.add_row("Total", f"{state.total_tokens_total:,}{approx}")
    tbl.add_row("Est. cost", cost)
    tbl.add_row("Latency avg", lat)
    tbl.add_row("Duration", dur)
    return Panel(tbl, title="Status & tokens", border_style="blue", box=box.ROUNDED)


def _error_panel(state: AgentConsoleState) -> Panel | None:
    if not state.error_title:
        return None
    hint = state.error_hint or ""
    body = (
        f"[bold red]ERROR[/] [bold]{state.error_title}[/]\n"
        f"{state.error_explanation or '—'}"
    )
    if hint:
        body += f"\n[dim]Hint:[/] {hint}"
    return Panel(
        Text.from_markup(body),
        title="Issue",
        border_style="red",
        box=box.ROUNDED,
    )


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
    tgt = truncate_text(step.target_summary or "—", 90)
    res = step.result_display or humanize_result_status(step.result_status)
    prog = truncate_text(step.progress_note or "—", 100)
    exp = truncate_text(step.expected_outcome or "—", 100)
    reason = truncate_text(step.rationale_summary, 120)
    sk = step.skill_display or humanize_skill_name(step.skill_name)
    phase = step.phase_label
    return (
        f"[bold magenta]Step {step.step_number + 1}[/]   [yellow]{phase}[/]\n"
        f"  [dim]Reason[/]     {reason}\n"
        f"  [dim]Skill[/]      {sk}\n"
        f"  [dim]Target[/]     {tgt}\n"
        f"  [dim]Expected[/]   {exp}\n"
        f"  [dim]Result[/]     {res}\n"
        f"  [dim]Progress[/]   {prog}"
    )


def _right_panel(state: AgentConsoleState) -> Panel:
    obs = state.observation_summary or "—"
    obs = truncate_text(obs, 420)
    warns = "\n".join(f"• {truncate_text(w, 72)}" for w in state.observation_warnings[:6]) or "—"
    dec = state.last_decision_type or "—"
    rat = truncate_text(state.last_rationale or "—", 220)
    tbl = Table.grid(padding=(0, 1))
    tbl.add_row("[bold]Observation[/]", obs)
    tbl.add_row("[bold]Interactive[/]", str(state.interactive_element_count))
    tbl.add_row("[bold]Warnings[/]", warns)
    tbl.add_row("[bold]Last decision[/]", f"{dec}\n{rat}")
    return Panel(tbl, title="Current state", border_style="yellow", box=box.ROUNDED)


def _bottom_panel(state: AgentConsoleState) -> Panel:
    if state.bottom_mode == "confirm":
        cons = "\n".join(f"  • {truncate_text(c, 76)}" for c in state.confirm_consequences) or "  —"
        body = (
            f"[bold red]CONFIRMATION REQUIRED[/]\n\n"
            f"[bold]Action:[/] {state.confirm_action}\n"
            f"[bold]Reason:[/] {truncate_text(state.confirm_reason, 200)}\n"
            f"[bold]Context:[/]\n{cons}\n\n"
            f"[green][Y][/] Yes    [red][N][/] No"
        )
        return Panel(Text.from_markup(body), title="Input", border_style="red", box=box.ROUNDED)
    if state.bottom_mode == "input":
        body = (
            f"[bold cyan]AGENT NEEDS INPUT[/]\n\n"
            f"[bold]Question:[/]\n{truncate_text(state.input_question, 400)}\n\n"
            f"[dim]Answer when prompted below…[/]"
        )
        return Panel(Text.from_markup(body), title="Input", border_style="cyan", box=box.ROUNDED)
    return Panel(
        Text.from_markup("[dim]Idle — running or waiting for the next event…[/]"),
        title="Input",
        border_style="dim",
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


def build_layout(state: AgentConsoleState) -> Layout:
    """Main operator layout: top, middle (3 cols), bottom."""
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
