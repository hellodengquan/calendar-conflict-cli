from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import Conflict, Event, Gap


def format_timedelta(td) -> str:
    total_seconds = int(td.total_seconds())
    hours, rem = divmod(total_seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分"


def render_events_table(events: List[Event], console: Optional[Console] = None) -> None:
    console = console or Console()
    if not events:
        console.print("[yellow]没有日程数据[/yellow]")
        return
    table = Table(title=f"日程一览（共 {len(events)} 项）", show_lines=False)
    table.add_column("#", style="dim", justify="right")
    table.add_column("时间", style="cyan")
    table.add_column("时长", justify="right")
    table.add_column("标题", style="bold")
    table.add_column("地点", style="magenta")
    table.add_column("参会人", style="green")
    for idx, e in enumerate(sorted(events, key=lambda x: (x.start, x.end)), start=1):
        start_str = e.start.strftime("%m-%d %H:%M")
        end_str = e.end.strftime("%H:%M")
        attendees = ", ".join(e.attendees[:3])
        if len(e.attendees) > 3:
            attendees += f" 等{len(e.attendees)}人"
        table.add_row(
            str(idx),
            f"{start_str}–{end_str}",
            format_timedelta(e.duration),
            e.title,
            e.location or "—",
            attendees or "—",
        )
    console.print(table)


def render_conflicts(conflicts: List[Conflict], console: Optional[Console] = None) -> None:
    console = console or Console()
    if not conflicts:
        console.print("[green]✅ 未发现日程冲突[/green]")
        return
    console.print(f"[bold red]⚠️  发现 {len(conflicts)} 处日程冲突：[/bold red]")
    for idx, c in enumerate(conflicts, start=1):
        overlap_start = c.overlap_start.strftime("%m-%d %H:%M")
        overlap_end = c.overlap_end.strftime("%H:%M")
        console.print(
            Text.assemble(
                (f"\n[{idx}] 冲突 ", "bold red"),
                (f"{overlap_start}–{overlap_end}", "cyan"),
                (f" （{format_timedelta(c.duration)}）", "yellow"),
            )
        )
        for label, ev in [("A", c.event_a), ("B", c.event_b)]:
            console.print(
                Text.assemble(
                    (f"  {label}. ", "bold"),
                    (f"{ev.start.strftime('%H:%M')}–{ev.end.strftime('%H:%M')} ", "dim"),
                    (ev.title, "white"),
                    (f"  {ev.location}" if ev.location else "", "magenta"),
                )
            )
            if ev.attendees:
                console.print(f"      参会人: {', '.join(ev.attendees)}", style="green")


def render_gaps(gaps: List[Gap], console: Optional[Console] = None) -> None:
    console = console or Console()
    if not gaps:
        console.print("[yellow]未找到满足条件的空档[/yellow]")
        return
    table = Table(title=f"可用空档（共 {len(gaps)} 段）")
    table.add_column("#", style="dim", justify="right")
    table.add_column("开始", style="cyan")
    table.add_column("结束", style="cyan")
    table.add_column("时长", justify="right", style="yellow")
    table.add_column("前序日程", style="dim")
    table.add_column("后续日程", style="dim")
    for idx, g in enumerate(gaps, start=1):
        before = g.before_event.title if g.before_event else "—"
        after = g.after_event.title if g.after_event else "—"
        if len(before) > 20:
            before = before[:17] + "..."
        if len(after) > 20:
            after = after[:17] + "..."
        table.add_row(
            str(idx),
            g.start.strftime("%m-%d %H:%M"),
            g.end.strftime("%H:%M"),
            format_timedelta(g.duration),
            before,
            after,
        )
    console.print(table)


def render_full_report(
    events: List[Event],
    conflicts: List[Conflict],
    gaps: List[Gap],
    console: Optional[Console] = None,
) -> None:
    console = console or Console()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.rule(f"[bold]📅 日程分析报告  生成于 {now}[/bold]")
    console.print()
    render_events_table(events, console)
    console.print()
    render_conflicts(conflicts, console)
    console.print()
    render_gaps(gaps, console)
    console.print()
    console.rule("[dim]报告结束[/dim]")


def export_text_report(
    events: List[Event],
    conflicts: List[Conflict],
    gaps: List[Gap],
) -> str:
    lines: List[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("=" * 60)
    lines.append(f"日程分析报告  生成于 {now}")
    lines.append("=" * 60)
    lines.append("")

    lines.append(f"【日程一览】共 {len(events)} 项")
    lines.append("-" * 40)
    for idx, e in enumerate(sorted(events, key=lambda x: (x.start, x.end)), start=1):
        start_str = e.start.strftime("%Y-%m-%d %H:%M")
        end_str = e.end.strftime("%H:%M")
        loc = f" @ {e.location}" if e.location else ""
        att = f" | 参会: {', '.join(e.attendees)}" if e.attendees else ""
        lines.append(f"  {idx:>3}. [{start_str}–{end_str}] {e.title}{loc}{att}")
    lines.append("")

    lines.append(f"【冲突检查】发现 {len(conflicts)} 处")
    lines.append("-" * 40)
    if not conflicts:
        lines.append("  ✓ 未发现冲突")
    else:
        for idx, c in enumerate(conflicts, start=1):
            overlap_start = c.overlap_start.strftime("%Y-%m-%d %H:%M")
            overlap_end = c.overlap_end.strftime("%H:%M")
            lines.append(
                f"  [{idx}] {overlap_start}–{overlap_end} （{format_timedelta(c.duration)}）"
            )
            for label, ev in [("A", c.event_a), ("B", c.event_b)]:
                es = ev.start.strftime("%H:%M")
                ee = ev.end.strftime("%H:%M")
                loc = f" @ {ev.location}" if ev.location else ""
                lines.append(f"      {label}. [{es}–{ee}] {ev.title}{loc}")
                if ev.attendees:
                    lines.append(f"         参会: {', '.join(ev.attendees)}")
    lines.append("")

    lines.append(f"【空档建议】共 {len(gaps)} 段")
    lines.append("-" * 40)
    if not gaps:
        lines.append("  （未找到符合条件的空档）")
    else:
        for idx, g in enumerate(gaps, start=1):
            gs = g.start.strftime("%Y-%m-%d %H:%M")
            ge = g.end.strftime("%H:%M")
            before = g.before_event.title if g.before_event else "—"
            after = g.after_event.title if g.after_event else "—"
            lines.append(
                f"  {idx:>3}. [{gs}–{ge}] 时长 {format_timedelta(g.duration)}  |  前: {before}  →  后: {after}"
            )
    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
