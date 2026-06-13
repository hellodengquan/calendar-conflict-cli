from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .models import Event


class RRuleHorizonError(ValueError):
    """RRULE 展开超出安全时间窗口时抛出。"""

    pass


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
    bysetpos: List[int] = field(default_factory=list)
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
        if "BYSETPOS" in params:
            for sp in params["BYSETPOS"].split(","):
                sp = sp.strip()
                if re.match(r"^-?\d+$", sp):
                    rrule.bysetpos.append(int(sp))
        if "WKST" in params:
            w = params["WKST"].strip().upper()
            if w in _DAY_ABBR:
                rrule.wkst = _DAY_ABBR[w]

        return rrule

    def iter_dates(
        self,
        start: datetime,
        limit: int = 1000,
        horizon: Optional[datetime] = None,
    ) -> List[datetime]:
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
            if horizon is not None and current > horizon:
                if self.count is None and self.until is None:
                    raise RRuleHorizonError(
                        f"RRULE 展开超出安全时间窗口（{horizon.isoformat()}）。"
                        "请为 RRULE 添加 COUNT 或 UNTIL，或增大 rrule_horizon。"
                    )
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
            if self.bysetpos and self.byday:
                return self._matches_bysetpos_monthly(dt)
            if self.bymonthday:
                for md in self.bymonthday:
                    target = self._resolve_monthday(dt.year, dt.month, md)
                    if target is not None and dt.day == target:
                        return True
                return False
            if self.byday:
                return dt.weekday() in self.byday
            target_day = min(start.day, calendar.monthrange(dt.year, dt.month)[1])
            return dt.day == target_day
        if self.freq == "YEARLY":
            last_day = calendar.monthrange(dt.year, start.month)[1]
            target_day = min(start.day, last_day)
            return (dt.month == start.month) and (dt.day == target_day)
        return False

    def _matches_bysetpos_monthly(self, dt: datetime) -> bool:
        if dt.weekday() not in self.byday:
            return False
        target_days = self._collect_bysetpos_days(dt.year, dt.month)
        return dt.day in target_days

    def _collect_bysetpos_days(self, year: int, month: int) -> List[int]:
        last_day = calendar.monthrange(year, month)[1]
        all_matching: List[int] = []
        for day in range(1, last_day + 1):
            try:
                wd = datetime(year, month, day).weekday()
            except ValueError:
                continue
            if wd in self.byday:
                all_matching.append(day)

        selected: List[int] = []
        for pos in self.bysetpos:
            if pos > 0:
                idx = pos - 1
                if 0 <= idx < len(all_matching):
                    selected.append(all_matching[idx])
            elif pos < 0:
                idx = len(all_matching) + pos
                if 0 <= idx < len(all_matching):
                    selected.append(all_matching[idx])
        return selected

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
            if self.bysetpos and self.byday:
                return self._advance_monthly_bysetpos(current)
            if self.bymonthday:
                return self._advance_monthly_bymonthday(current)
            if self.byday:
                return self._advance_monthly_byday(current)
            return _add_months_preserve_day(current, self.interval, start.day)
        if self.freq == "YEARLY":
            if self.bymonthday:
                return self._advance_yearly_bymonthday(current, start)
            if self.byday:
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

    def _advance_monthly_bymonthday(self, current: datetime) -> datetime:
        if not self.bymonthday:
            return _add_months(current, self.interval)

        sorted_md = self._sorted_bymonthday(current.year, current.month)
        for md_day in sorted_md:
            if md_day > current.day:
                return current.replace(day=md_day)

        next_month = _add_months(
            datetime(current.year, current.month, 1,
                     current.hour, current.minute, current.second,
                     tzinfo=current.tzinfo),
            self.interval,
        )
        next_sorted = self._sorted_bymonthday(next_month.year, next_month.month)
        if next_sorted:
            return next_month.replace(day=next_sorted[0])
        return next_month

    def _advance_monthly_bysetpos(self, current: datetime) -> datetime:
        target_days = self._collect_bysetpos_days(current.year, current.month)
        for td in sorted(target_days):
            if td > current.day:
                return current.replace(day=td)

        next_base = _add_months(
            datetime(current.year, current.month, 1,
                     current.hour, current.minute, current.second,
                     tzinfo=current.tzinfo),
            self.interval,
        )
        next_days = self._collect_bysetpos_days(next_base.year, next_base.month)
        if next_days:
            return next_base.replace(day=next_days[0])
        return next_base

    def _advance_monthly_byday(self, current: datetime) -> datetime:
        return _add_months(current, self.interval)

    def _advance_yearly_bymonthday(self, current: datetime, start: datetime) -> datetime:
        if not self.bymonthday:
            return _add_years(current, self.interval)

        target_month = start.month
        if current.month < target_month or (
            current.month == target_month and current.day < max(self.bymonthday)
        ):
            sorted_md = self._sorted_bymonthday(current.year, target_month)
            for md_day in sorted_md:
                if md_day > current.day or current.month != target_month:
                    try:
                        return current.replace(month=target_month, day=md_day)
                    except ValueError:
                        continue

        next_year = current.year + self.interval
        sorted_md = self._sorted_bymonthday(next_year, target_month)
        if sorted_md:
            try:
                return current.replace(year=next_year, month=target_month, day=sorted_md[0])
            except ValueError:
                pass
        return _add_years(current, self.interval)

    def _sorted_bymonthday(self, year: int, month: int) -> List[int]:
        days: List[int] = []
        for md in self.bymonthday:
            target = self._resolve_monthday(year, month, md)
            if target is not None:
                days.append(target)
        days.sort()
        return days


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
    horizon: Optional[datetime] = None,
    event_title: Optional[str] = None,
) -> List[Event]:
    try:
        start_dates = rrule.iter_dates(base_event.start, limit=limit, horizon=horizon)
    except RRuleHorizonError as e:
        title = event_title or base_event.title or "(未命名事件)"
        raise RRuleHorizonError(
            f"重复事件「{title}」{e}"
        ) from e
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
