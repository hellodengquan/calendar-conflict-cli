from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

from .models import Conflict, Event, Gap


def detect_conflicts(events: List[Event]) -> List[Conflict]:
    if len(events) < 2:
        return []

    points: List[Tuple[datetime, int, Event]] = []
    for ev in events:
        points.append((ev.start, 1, ev))
        points.append((ev.end, 0, ev))

    points.sort(key=lambda p: (p[0], p[1]))

    active: List[Event] = []
    conflicts: List[Conflict] = []
    seen_pairs: set = set()

    for time, typ, event in points:
        if typ == 1:
            for other in active:
                pair_id = tuple(sorted([id(other), id(event)]))
                if pair_id in seen_pairs:
                    continue
                seen_pairs.add(pair_id)
                overlap_start = max(other.start, event.start)
                overlap_end = min(other.end, event.end)
                if overlap_start < overlap_end:
                    conflicts.append(
                        Conflict(
                            event_a=other,
                            event_b=event,
                            overlap_start=overlap_start,
                            overlap_end=overlap_end,
                        )
                    )
            active.append(event)
        else:
            if event in active:
                active.remove(event)

    conflicts.sort(key=lambda c: (c.overlap_start, c.overlap_end))
    return conflicts


def find_gaps(
    events: List[Event],
    min_duration: timedelta = timedelta(minutes=30),
    work_start_hour: int = 9,
    work_end_hour: int = 18,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> List[Gap]:
    if not events:
        return []
    sorted_events = sorted(events, key=lambda e: (e.start, e.end))

    if from_date is None:
        first = sorted_events[0].start
        from_date = datetime(first.year, first.month, first.day, tzinfo=first.tzinfo)
    if to_date is None:
        last = sorted_events[-1].end
        to_date = datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=last.tzinfo)

    events_in_range = [
        e for e in sorted_events if e.end > from_date and e.start < to_date
    ]
    if not events_in_range:
        return []

    busy_intervals: List[Tuple[datetime, datetime, Event]] = []
    for ev in events_in_range:
        s = max(ev.start, from_date)
        e = min(ev.end, to_date)
        if s < e:
            busy_intervals.append((s, e, ev))

    busy_intervals.sort(key=lambda x: (x[0], x[1]))

    merged: List[Tuple[datetime, datetime, Optional[Event]]] = []
    for s, e, ev in busy_intervals:
        if not merged:
            merged.append((s, e, ev))
            continue
        last_s, last_e, last_ev = merged[-1]
        if s <= last_e:
            merged[-1] = (last_s, max(last_e, e), last_ev)
        else:
            merged.append((s, e, ev))

    gaps: List[Gap] = []
    cursor = from_date
    last_event: Optional[Event] = None

    for busy_start, busy_end, busy_ev in merged:
        if busy_start > cursor:
            day_gaps = _split_gap_by_work_hours(
                cursor, busy_start, work_start_hour, work_end_hour
            )
            for g in day_gaps:
                if g.duration >= min_duration:
                    g.before_event = last_event
                    g.after_event = busy_ev
                    gaps.append(g)
        cursor = max(cursor, busy_end)
        last_event = busy_ev

    if cursor < to_date:
        day_gaps = _split_gap_by_work_hours(
            cursor, to_date, work_start_hour, work_end_hour
        )
        for g in day_gaps:
            if g.duration >= min_duration:
                g.before_event = last_event
                g.after_event = None
                gaps.append(g)

    return gaps


def _split_gap_by_work_hours(
    start: datetime, end: datetime, work_start_hour: int, work_end_hour: int
) -> List[Gap]:
    if start >= end:
        return []

    gaps: List[Gap] = []
    tzinfo = start.tzinfo

    current_day = datetime(start.year, start.month, start.day, tzinfo=tzinfo)
    end_day = datetime(end.year, end.month, end.day, tzinfo=tzinfo)

    while current_day <= end_day:
        day_work_start = current_day.replace(
            hour=work_start_hour, minute=0, second=0, microsecond=0
        )
        day_work_end = current_day.replace(
            hour=work_end_hour, minute=0, second=0, microsecond=0
        )

        effective_start = max(start, day_work_start)
        effective_end = min(end, day_work_end)

        if effective_start < effective_end:
            gaps.append(Gap(start=effective_start, end=effective_end))

        current_day = current_day + timedelta(days=1)

    return gaps


def summarize(events: List[Event]) -> dict:
    if not events:
        return {"total": 0, "duration": timedelta(0)}
    total_duration = sum((e.duration for e in events), timedelta(0))
    start_min = min(e.start for e in events)
    end_max = max(e.end for e in events)
    return {
        "total": len(events),
        "duration": total_duration,
        "start": start_min,
        "end": end_max,
    }


def filter_events(
    events: List[Event],
    predicate: Callable[[Event], bool],
) -> List[Event]:
    return [e for e in events if predicate(e)]
