from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.status import Status

from .analyzer import detect_conflicts, find_gaps
from .parser import ParseError, load_events
from .report import (
    export_text_report,
    render_conflicts,
    render_events_table,
    render_full_report,
    render_gaps,
)
from .rrule import RRuleHorizonError

app = typer.Typer(
    name="calconflict",
    help="日程冲突排查：冲突分析 · 空档建议 · 文本报告",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


def _load(file: Path, rrule_horizon_days: int = 730) -> list:
    try:
        with Status(f"正在加载 {file.name} ...", spinner="dots"):
            horizon = timedelta(days=rrule_horizon_days)
            events = load_events(file, rrule_horizon=horizon)
        if not events:
            console.print("[yellow]文件中没有解析到任何日程[/yellow]")
            raise typer.Exit(1)
        console.print(f"[green]✓[/green] 已加载 {len(events)} 条日程")
        return events
    except ParseError as exc:
        console.print(f"[bold red]解析失败:[/bold red] {exc}")
        raise typer.Exit(1)
    except RRuleHorizonError as exc:
        console.print(f"[bold red]重复事件展开超限:[/bold red] {exc}")
        console.print(
            "提示：可使用 [cyan]--rrule-horizon[/cyan] 增加展开窗口（天），"
            "或为 RRULE 添加 COUNT/UNTIL 限制。"
        )
        raise typer.Exit(1)


@app.command("list")
def cmd_list(
    file: Path = typer.Argument(..., exists=True, readable=True, help="日程文件（.json/.csv/.ics）"),
    rrule_horizon: int = typer.Option(
        730, "--rrule-horizon", min=1, help="RRULE 重复事件展开窗口（天），默认 2 年"
    ),
):
    """列出所有日程"""
    events = _load(file, rrule_horizon_days=rrule_horizon)
    render_events_table(events, console)


@app.command("check")
def cmd_check(
    file: Path = typer.Argument(..., exists=True, readable=True, help="日程文件"),
    strict_exit: bool = typer.Option(
        False, "--strict", "-s", help="发现冲突时以非零状态退出"
    ),
    rrule_horizon: int = typer.Option(
        730, "--rrule-horizon", min=1, help="RRULE 重复事件展开窗口（天），默认 2 年"
    ),
):
    """检查日程冲突"""
    events = _load(file, rrule_horizon_days=rrule_horizon)
    conflicts = detect_conflicts(events)
    render_conflicts(conflicts, console)
    if strict_exit and conflicts:
        raise typer.Exit(code=len(conflicts))


@app.command("gaps")
def cmd_gaps(
    file: Path = typer.Argument(..., exists=True, readable=True, help="日程文件"),
    min_minutes: int = typer.Option(
        30, "--min", "-m", min=1, help="空档最短时长（分钟）"
    ),
    work_start: int = typer.Option(
        9, "--work-start", min=0, max=23, help="工作开始小时"
    ),
    work_end: int = typer.Option(
        18, "--work-end", min=1, max=23, help="工作结束小时"
    ),
    from_date: Optional[str] = typer.Option(
        None, "--from", help="起始日期 YYYY-MM-DD"
    ),
    to_date: Optional[str] = typer.Option(None, "--to", help="结束日期 YYYY-MM-DD"),
    rrule_horizon: int = typer.Option(
        730, "--rrule-horizon", min=1, help="RRULE 重复事件展开窗口（天），默认 2 年"
    ),
):
    """查找空档时间段"""
    events = _load(file, rrule_horizon_days=rrule_horizon)
    from_dt = datetime.strptime(from_date, "%Y-%m-%d") if from_date else None
    to_dt = datetime.strptime(to_date + " 23:59:59", "%Y-%m-%d %H:%M:%S") if to_date else None
    gaps = find_gaps(
        events,
        min_duration=timedelta(minutes=min_minutes),
        work_start_hour=work_start,
        work_end_hour=work_end,
        from_date=from_dt,
        to_date=to_dt,
    )
    render_gaps(gaps, console)


@app.command("report")
def cmd_report(
    file: Path = typer.Argument(..., exists=True, readable=True, help="日程文件"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="导出文本报告到文件（不指定则仅打印到终端）"
    ),
    min_minutes: int = typer.Option(
        30, "--min", "-m", min=1, help="空档最短时长（分钟）"
    ),
    work_start: int = typer.Option(
        9, "--work-start", min=0, max=23, help="工作开始小时"
    ),
    work_end: int = typer.Option(
        18, "--work-end", min=1, max=23, help="工作结束小时"
    ),
    rrule_horizon: int = typer.Option(
        730, "--rrule-horizon", min=1, help="RRULE 重复事件展开窗口（天），默认 2 年"
    ),
):
    """生成完整报告（冲突 + 空档 + 汇总）"""
    events = _load(file, rrule_horizon_days=rrule_horizon)
    conflicts = detect_conflicts(events)
    gaps = find_gaps(
        events,
        min_duration=timedelta(minutes=min_minutes),
        work_start_hour=work_start,
        work_end_hour=work_end,
    )
    render_full_report(events, conflicts, gaps, console)
    if output:
        text = export_text_report(events, conflicts, gaps)
        output.write_text(text, encoding="utf-8")
        console.print(f"\n[green]✓ 文本报告已保存至:[/green] {output.resolve()}")


def main() -> None:
    try:
        app()
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n[yellow]已取消[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
