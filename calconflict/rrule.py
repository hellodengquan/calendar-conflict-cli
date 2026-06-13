from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .models import Event


_DAY_ABBR = {
    "MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6,
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
}

_MONTH_RANGES = {
    1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}


@dataclass
class RRule:
    freq: str
    until: Optional[datetime] = None
    count: Optional[int] = None
    interval: int = 1
    byday: List[int] = field(default_factory=list)
    bymonthday: List[int] = field(default_factory=list)
    wkst: int = 0

    @classmethod
    def parse(cls, rrule_str: str) -> "RRule":
        params: Dict[str, str] = {}
        for part in rrule_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip().upper()] = v.strip()

        if "FREQ" not in params:
            raise ValueError("RRULE 缺少 FREQ")

        freq = params["FREQ"].upper()
        if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            raise ValueError(f"不支持的 FREQ: {freq}")

        rrule = cls(freq=freq)

        if "UNTIL" in params:
            rrule.until = _parse_rrule_datetime(params["UNTIL"])
        if "COUNT" in params:
            rrule.count = int(params["COUNT"])
        if "INTERVAL" in params:
            rrule.interval = int(params["INTERVAL"])
        if "BYDAY" in params:
            for d in params["BYDAY"].split(","):
                d = d.strip().upper()
                if d in _DAY_ABBR:
                    rrule.byday.append(_DAY_ABBR[d])
        if "BYMONTHDAY" in params:
            for md in params["BYMONTHDAY"].split(","):
                md = md.strip()
                if re.match(r"^-?\d+$", md):
                    rrule.bymonthday.append(int(md))
        if "WKST" in params:
            w = params["WKST"].strip().upper()
            if w in _DAY_ABBR:
                rrule.wkst = _DAY_ABBR[w]

        return rrule

    def iter_dates(self, start: datetime, limit: int = 1000) -> List[datetime]:
        results: List[datetime] = []
        current = start
        added = 0
        iterations = 0
        max_iterations = max(limit * 50, 10000)

        while iterations < max_iterations:
            iterations += 1

            if self.until is not None and current > self.until:
                break
            if self.count is not None and added >= self.count:
                break
            if added >= limit:
                break

            if self._matches(current, start):
                results.append(current)
                added += 1

            current = self._advance(current, start)

        return results

    def _matches(self, dt: datetime, start: datetime) -> bool:
        if self.freq == "DAILY":
            return True
        if self.freq == "WEEKLY":
            if self.byday:
                return dt.weekday() in self.byday
            return dt.weekday() == start.weekday()
        if self.freq == "MONTHLY":
            if self.bymonthday:
                for md in self.bymonthday:
                    target = self._resolve_monthday(dt.year, dt.month, md)
                    if target is not None and dt.day == target:
                        return True
                return False
            if self.byday:
                return self._matches_byday_in_month(dt)
            target_day = min(start.day, calendar.monthrange(dt.year, dt.month)[1])
            return dt.day == target_day
        if self.freq == "YEARLY":
            last_day = calendar.monthrange(dt.year, start.month)[1]
            target_day = min(start.day, last_day)
            return (dt.month == start.month) and (dt.day == target_day)
        return False

    def _matches_byday_in_month(self, dt: datetime) -> bool:
        if dt.weekday() not in self.byday:
            return False
        week_index = (dt.day - 1) // 7
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        is_last_week = dt.day + 7 > last_day
        if self.count and self.count > 0:
            return week_index == (self.count - 1)
        if self.count and self.count < 0:
            if self.count == -1:
                return is_last_week
            last_week_index = (last_day - 1) // 7
            return week_index == (last_week_index + self.count + 1)
        return True

    def _resolve_monthday(
        self, year: int, month: int, md: int
    ) -> Optional[int]:
        last_day = calendar.monthrange(year, month)[1]
        if md > 0:
            if 1 <= md <= last_day:
                return md
            return None
        else:
            target = last_day + md + 1
            if 1 <= target <= last_day:
                return target
            return None

    def _advance(self, current: datetime, start: datetime) -> datetime:
        if self.freq == "DAILY":
            return current + timedelta(days=self.interval)
        if self.freq == "WEEKLY":
            if self.byday:
                return self._advance_weekly_with_byday(current)
            return current + timedelta(weeks=self.interval)
        if self.freq == "MONTHLY":
            if self.byday or self.bymonthday:
                return _add_months(current, self.interval)
            return _add_months_preserve_day(current, self.interval, start.day)
        if self.freq == "YEARLY":
            if self.byday or self.bymonthday:
                return _add_years(current, self.interval)
            return _add_years_preserve_day(current, self.interval, start.day)
        return current + timedelta(days=1)

    def _advance_weekly_with_byday(self, current: datetime) -> datetime:
        if not self.byday:
            return current + timedelta(weeks=self.interval)

        sorted_days = sorted(self.byday)
        current_wd = current.weekday()
        for wd in sorted_days:
            if wd > current_wd:
                return current + timedelta(days=(wd - current_wd))

        first_wd = sorted_days[0]
        days_ahead = (7 - current_wd) + first_wd + (self.interval - 1) * 7
        return current + timedelta(days=days_ahead)


def _parse_rrule_datetime(value: str) -> datetime:
    value = value.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?$", value)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    m2 = re.match(r"^(\d{4})(\d{2})(\d{2})$", value)
    if m2:
        y, mo, d = m2.groups()
        return datetime(int(y), int(mo), int(d))
    from dateutil import parser as dp
    return dp.parse(value)


def _add_months(dt: datetime, months: int) -> datetime:
    total = dt.month - 1 + months
    new_year = dt.year + total // 12
    new_month = total % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    new_day = min(dt.day, last_day)
    try:
        return dt.replace(year=new_year, month=new_month, day=new_day)
    except (ValueError, OverflowError):
        return datetime(new_year, new_month, new_day)


def _add_years(dt: datetime, years: int) -> datetime:
    new_year = dt.year + years
    last_day = calendar.monthrange(new_year, dt.month)[1]
    new_day = min(dt.day, last_day)
    try:
        return dt.replace(year=new_year, day=new_day)
    except (ValueError, OverflowError):
        return datetime(new_year, dt.month, new_day)


def _add_months_preserve_day(dt: datetime, months: int, target_day: int) -> datetime:
    total = dt.month - 1 + months
    new_year = dt.year + total // 12
    new_month = total % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    new_day = min(target_day, last_day)
    try:
        return dt.replace(year=new_year, month=new_month, day=new_day)
    except (ValueError, OverflowError):
        return datetime(
            new_year, new_month, new_day,
            dt.hour, dt.minute, dt.second,
            tzinfo=dt.tzinfo,
        )


def _add_years_preserve_day(dt: datetime, years: int, target_day: int) -> datetime:
    new_year = dt.year + years
    last_day = calendar.monthrange(new_year, dt.month)[1]
    new_day = min(target_day, last_day)
    try:
        return dt.replace(year=new_year, day=new_day)
    except (ValueError, OverflowError):
        return datetime(
            new_year, dt.month, new_day,
            dt.hour, dt.minute, dt.second,
            tzinfo=dt.tzinfo,
        )


def expand_rrule(
    base_event: Event,
    rrule: RRule,
    exdates: List[datetime] = None,
    limit: int = 1000,
) -> List[Event]:
    start_dates = rrule.iter_dates(base_event.start, limit=limit)
    if exdates:
        exdates_normalized = [
            datetime(
                d.year, d.month, d.day, d.hour, d.minute, d.second,
                tzinfo=d.tzinfo,
            )
            for d in exdates
        ]
    else:
        exdates_normalized = []

    duration = base_event.duration
    expanded: List[Event] = []

    for idx, start in enumerate(start_dates):
        if exdates_normalized:
            s_norm = datetime(
                start.year, start.month, start.day,
                start.hour, start.minute, start.second,
                tzinfo=start.tzinfo,
            )
            if any(e.year == s_norm.year and e.month == s_norm.month
                   and e.day == s_norm.day and e.hour == s_norm.hour
                   and e.minute == s_norm.minute
                   for e in exdates_normalized):
                continue

        end = start + duration
        eid = base_event.id
        if eid:
            eid = f"{eid}-{idx}"
        expanded.append(
            Event(
                title=base_event.title,
                start=start,
                end=end,
                location=base_event.location,
                attendees=list(base_event.attendees),
                id=eid,
            )
        )

    return expanded
