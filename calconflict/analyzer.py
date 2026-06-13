from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, List, Optional

from .models import Conflict, Event, Gap


def detect_conflicts(events: List[Event]) -> List[Conflict]:
    if len(events) < 2:
        return []
    sorted_events = sorted(events, key=lambda e: (e.start, e.end))
    conflicts: List[Conflict] = []
    for i in range(len(sorted_events)):
        for j in range(i + 1, len(sorted_events)):
            a, b = sorted_events[i], sorted_events[j]
            if b.start >= a.end:
                break
            if a.overlaps_with(b):
                overlap_start = max(a.start, b.start)
                overlap_end = min(a.end, b.end)
                conflicts.append(
                    Conflict(
                        event_a=a,
                        event_b=b,
                        overlap_start=overlap_start,
                        overlap_end=overlap_end,
                    )
                )
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
        from_date = sorted_events[0].start.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if to_date is None:
        to_date = sorted_events[-1].end.replace(
            hour=23, minute=59, second=59, microsecond=0
        )

    events_in_range = [
        e for e in sorted_events if e.end > from_date and e.start < to_date
    ]
    if not events_in_range:
        events_in_range = sorted_events

    gaps: List[Gap] = []
    cursor = from_date
    last_event: Optional[Event] = None

    for event in events_in_range:
        if event.end <= cursor:
            continue
        if event.start > cursor:
            gap_candidate = _clip_to_work_hours(
                cursor, event.start, work_start_hour, work_end_hour
            )
            if gap_candidate and gap_candidate.duration >= min_duration:
                gap_candidate.before_event = last_event
                gap_candidate.after_event = event
                gaps.append(gap_candidate)
        cursor = max(cursor, event.end)
        last_event = event

    if cursor < to_date:
        gap_candidate = _clip_to_work_hours(
            cursor, to_date, work_start_hour, work_end_hour
        )
        if gap_candidate and gap_candidate.duration >= min_duration:
            gap_candidate.before_event = last_event
            gap_candidate.after_event = None
            gaps.append(gap_candidate)

    return gaps


def _clip_to_work_hours(
    start: datetime, end: datetime, work_start_hour: int, work_end_hour: int
) -> Optional[Gap]:
    if start >= end:
        return None
    day_start = start.replace(hour=work_start_hour, minute=0, second=0, microsecond=0)
    day_end = start.replace(hour=work_end_hour, minute=0, second=0, microsecond=0)
    if end.date() > start.date():
        return Gap(start=max(start, day_start), end=min(end, day_end))
    effective_start = max(start, day_start)
    effective_end = min(end, day_end)
    if effective_start >= effective_end:
        return None
    return Gap(start=effective_start, end=effective_end)


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
