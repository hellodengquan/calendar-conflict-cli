from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    attendees: List[str] = field(default_factory=list)
    id: Optional[str] = None

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def overlaps_with(self, other: "Event") -> bool:
        if self.start == other.end or self.end == other.start:
            return False
        return self.start < other.end and other.start < self.end

    def overlap_duration(self, other: "Event") -> timedelta:
        if not self.overlaps_with(other):
            return timedelta(0)
        overlap_start = max(self.start, other.start)
        overlap_end = min(self.end, other.end)
        return overlap_end - overlap_start

    def __str__(self) -> str:
        start_str = self.start.strftime("%Y-%m-%d %H:%M")
        end_str = self.end.strftime("%H:%M")
        loc = f" @ {self.location}" if self.location else ""
        return f"[{start_str}-{end_str}] {self.title}{loc}"


@dataclass
class Conflict:
    event_a: Event
    event_b: Event
    overlap_start: datetime
    overlap_end: datetime

    @property
    def duration(self) -> timedelta:
        return self.overlap_end - self.overlap_start

    def __str__(self) -> str:
        overlap_start = self.overlap_start.strftime("%Y-%m-%d %H:%M")
        overlap_end = self.overlap_end.strftime("%H:%M")
        return (
            f"冲突 [{overlap_start}-{overlap_end}] ({self.duration}):\n"
            f"  - {self.event_a}\n"
            f"  - {self.event_b}"
        )


@dataclass
class Gap:
    start: datetime
    end: datetime
    before_event: Optional[Event] = None
    after_event: Optional[Event] = None

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def __str__(self) -> str:
        start_str = self.start.strftime("%Y-%m-%d %H:%M")
        end_str = self.end.strftime("%H:%M")
        hours = self.duration.total_seconds() / 3600
        return f"空档 [{start_str}-{end_str}] ({hours:.1f} 小时)"
