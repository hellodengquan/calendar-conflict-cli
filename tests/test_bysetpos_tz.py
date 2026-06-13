from datetime import datetime, timedelta, timezone

import pytest
from dateutil import tz

from calconflict.analyzer import detect_conflicts
from calconflict.models import Event
from calconflict.parser import load_events
from calconflict.rrule import RRule, expand_rrule


def _tue(y: int, m: int, n: int) -> int:
    count = 0
    for d in range(1, 32):
        try:
            if datetime(y, m, d).weekday() == 1:
                count += 1
                if count == n:
                    return d
        except ValueError:
            break
    return -1


def _fri(y: int, m: int, n: int) -> int:
    count = 0
    for d in range(1, 32):
        try:
            if datetime(y, m, d).weekday() == 4:
                count += 1
                if count == n:
                    return d
        except ValueError:
            break
    return -1


def _last_fri(y: int, m: int) -> int:
    import calendar
    last = calendar.monthrange(y, m)[1]
    for d in range(last, 0, -1):
        if datetime(y, m, d).weekday() == 4:
            return d
    return -1


class TestBysetposParsing:
    def test_parse_bysetpos_positive(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=6")
        assert r.bysetpos == [2]

    def test_parse_bysetpos_negative(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1;COUNT=6")
        assert r.bysetpos == [-1]

    def test_parse_bysetpos_multiple(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=TU;BYSETPOS=1,3;COUNT=6")
        assert r.bysetpos == [1, 3]


class TestBysetposSecondTuesday:
    def test_second_tuesday_each_month(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=6")
        dates = r.iter_dates(datetime(2026, 6, 1, 14, 0))
        assert len(dates) == 6
        for d in dates:
            assert d.weekday() == 1
            tue_count_before = sum(
                1 for day in range(1, d.day)
                if datetime(d.year, d.month, day).weekday() == 1
            )
            assert tue_count_before == 1

    def test_second_tuesday_specific_dates(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=4")
        dates = r.iter_dates(datetime(2026, 6, 1, 14, 0))
        expected = [
            datetime(2026, 6, _tue(2026, 6, 2), 14, 0),
            datetime(2026, 7, _tue(2026, 7, 2), 14, 0),
            datetime(2026, 8, _tue(2026, 8, 2), 14, 0),
            datetime(2026, 9, _tue(2026, 9, 2), 14, 0),
        ]
        assert dates == expected

    def test_start_on_second_tuesday(self):
        start = datetime(2026, 6, _tue(2026, 6, 2), 14, 0)
        r = RRule.parse("FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=3")
        dates = r.iter_dates(start)
        assert len(dates) == 3
        assert dates[0] == start


class TestBysetposLastFriday:
    def test_last_friday_each_month(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1;COUNT=6")
        dates = r.iter_dates(datetime(2026, 6, 1, 15, 0))
        assert len(dates) == 6
        for d in dates:
            assert d.weekday() == 4
            assert d.day == _last_fri(d.year, d.month)

    def test_last_friday_specific_dates(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1;COUNT=4")
        dates = r.iter_dates(datetime(2026, 6, 1, 15, 0))
        expected = [
            datetime(2026, 6, _last_fri(2026, 6), 15, 0),
            datetime(2026, 7, _last_fri(2026, 7), 15, 0),
            datetime(2026, 8, _last_fri(2026, 8), 15, 0),
            datetime(2026, 9, _last_fri(2026, 9), 15, 0),
        ]
        assert dates == expected

    def test_start_on_last_friday(self):
        start = datetime(2026, 6, _last_fri(2026, 6), 15, 0)
        r = RRule.parse("FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1;COUNT=3")
        dates = r.iter_dates(start)
        assert len(dates) == 3
        assert dates[0] == start


class TestBysetposMultiple:
    def test_first_and_third_tuesday(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=TU;BYSETPOS=1,3;COUNT=6")
        dates = r.iter_dates(datetime(2026, 6, 1, 10, 0))
        assert len(dates) == 6
        pairs = []
        for d in dates:
            tue_index = sum(
                1 for day in range(1, d.day)
                if datetime(d.year, d.month, day).weekday() == 1
            ) + 1
            pairs.append((d.month, tue_index))
        months_seen = set()
        for month, idx in pairs:
            assert idx in (1, 3)
            months_seen.add(month)
        assert len(months_seen) == 3


class TestBysetposIcsIntegration:
    def test_second_tuesday_in_ics(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:biweekly-tue\n"
            "SUMMARY:双月例会（每月第二个周二）\n"
            "DTSTART;TZID=Asia/Shanghai:20260609T140000\n"
            "DTEND;TZID=Asia/Shanghai:20260609T150000\n"
            "RRULE:FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=6\n"
            "LOCATION:会议室C\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 6
        for e in events:
            assert e.start.weekday() == 1
            assert e.duration == timedelta(hours=1)
            assert e.start.hour == 14

    def test_last_friday_in_ics(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:fin-review\n"
            "SUMMARY:月度财报评审（每月最后一个周五）\n"
            "DTSTART;TZID=Asia/Shanghai:20260626T150000\n"
            "DTEND;TZID=Asia/Shanghai:20260626T170000\n"
            "RRULE:FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1;COUNT=6\n"
            "LOCATION:董事会议室\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 6
        for e in events:
            assert e.start.weekday() == 4
            assert e.start.day == _last_fri(e.start.year, e.start.month)
            assert e.duration == timedelta(hours=2)

    def test_bysetpos_with_exdate(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:ex-bysetpos\n"
            "SUMMARY:月度会议\n"
            "DTSTART;TZID=Asia/Shanghai:20260609T140000\n"
            "DTEND;TZID=Asia/Shanghai:20260609T150000\n"
            "RRULE:FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=6\n"
            "EXDATE;TZID=Asia/Shanghai:20260811T140000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 5
        months = {e.start.month for e in events}
        assert 8 not in months

    def test_bysetpos_creates_conflict(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:r1\n"
            "SUMMARY:双月例会\n"
            "DTSTART;TZID=Asia/Shanghai:20260609T140000\n"
            "DTEND;TZID=Asia/Shanghai:20260609T150000\n"
            "RRULE:FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=1\n"
            "END:VEVENT\n"
            "BEGIN:VEVENT\n"
            "UID:r2\n"
            "SUMMARY:6月冲突会议\n"
            "DTSTART;TZID=Asia/Shanghai:20260609T143000\n"
            "DTEND;TZID=Asia/Shanghai:20260609T153000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        conflicts = detect_conflicts(events)
        assert len(conflicts) == 1
        assert conflicts[0].duration == timedelta(minutes=30)


class TestBysetposWithInterval:
    def test_bysetpos_interval_2(self):
        r = RRule.parse("FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;INTERVAL=2;COUNT=4")
        dates = r.iter_dates(datetime(2026, 6, 1, 9, 0))
        assert len(dates) == 4
        month_diffs = []
        for i in range(1, len(dates)):
            diff = (dates[i].year - dates[i - 1].year) * 12 + (
                dates[i].month - dates[i - 1].month
            )
            month_diffs.append(diff)
        assert all(d == 2 for d in month_diffs)


class TestCrossTimezoneRRule:
    def test_shanghai_tz_preserved_in_expansion(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:tz1\n"
            "SUMMARY:上海周会\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T090000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T100000\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        sh = tz.gettz("Asia/Shanghai")
        for e in events:
            assert e.start.tzinfo is not None
            assert e.start.hour == 9
            expected = datetime(e.start.year, e.start.month, e.start.day, 9, 0, tzinfo=sh)
            assert e.start == expected

    def test_ny_tz_preserved_in_expansion(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:tz2\n"
            "SUMMARY:纽约周会\n"
            "DTSTART;TZID=America/New_York:20260615T090000\n"
            "DTEND;TZID=America/New_York:20260615T100000\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        ny = tz.gettz("America/New_York")
        for e in events:
            assert e.start.tzinfo is not None
            expected = datetime(e.start.year, e.start.month, e.start.day, 9, 0, tzinfo=ny)
            assert e.start == expected
            assert e.start.hour == 9

    def test_monthly_bymonthday_with_tz_preserved(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:tz3\n"
            "SUMMARY:月度评审\n"
            "DTSTART;TZID=Asia/Shanghai:20260605T160000\n"
            "DTEND;TZID=Asia/Shanghai:20260605T170000\n"
            "RRULE:FREQ=MONTHLY;BYMONTHDAY=5;COUNT=6\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        sh = tz.gettz("Asia/Shanghai")
        for e in events:
            assert e.start.tzinfo is not None
            expected = datetime(e.start.year, e.start.month, 5, 16, 0, tzinfo=sh)
            assert e.start == expected
            assert e.start.hour == 16

    def test_bysetpos_with_tz_preserved(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:tz4\n"
            "SUMMARY:双月例会\n"
            "DTSTART;TZID=Asia/Shanghai:20260609T140000\n"
            "DTEND;TZID=Asia/Shanghai:20260609T150000\n"
            "RRULE:FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2;COUNT=6\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        sh = tz.gettz("Asia/Shanghai")
        for e in events:
            assert e.start.tzinfo is not None
            expected = datetime(e.start.year, e.start.month, e.start.day, 14, 0, tzinfo=sh)
            assert e.start == expected
            assert e.start.hour == 14

    def test_rrule_exdate_with_tz_preserved(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:tz5\n"
            "SUMMARY:每日站会\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T100000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T101500\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=10\n"
            "EXDATE;TZID=Asia/Shanghai:20260616T100000,20260618T100000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        sh = tz.gettz("Asia/Shanghai")
        for e in events:
            assert e.start.tzinfo is not None
            assert e.start.hour == 10
            expected = datetime(e.start.year, e.start.month, e.start.day, 10, 0, tzinfo=sh)
            assert e.start == expected
        days = {e.start.day for e in events}
        assert 16 not in days
        assert 18 not in days

    def test_cross_tz_conflict_detection(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:c1\n"
            "SUMMARY:UTC Meeting\n"
            "DTSTART:20260615T090000Z\n"
            "DTEND:20260615T100000Z\n"
            "RRULE:FREQ=WEEKLY;COUNT=3\n"
            "END:VEVENT\n"
            "BEGIN:VEVENT\n"
            "UID:c2\n"
            "SUMMARY:Shanghai Overlap\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T170000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T180000\n"
            "RRULE:FREQ=WEEKLY;COUNT=3\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        conflicts = detect_conflicts(events)
        assert len(conflicts) == 3
        for c in conflicts:
            assert c.duration == timedelta(hours=1)

    def test_expand_rrule_preserves_tz_on_event(self):
        sh = tz.gettz("Asia/Shanghai")
        base = Event(
            title="TZ Test",
            start=datetime(2026, 6, 15, 9, 0, tzinfo=sh),
            end=datetime(2026, 6, 15, 10, 0, tzinfo=sh),
            id="tz-test",
        )
        rule = RRule.parse("FREQ=WEEKLY;BYDAY=MO;COUNT=3")
        expanded = expand_rrule(base, rule)
        for e in expanded:
            assert e.start.tzinfo is not None
            assert e.start.hour == 9
            expected = datetime(e.start.year, e.start.month, e.start.day, 9, 0, tzinfo=sh)
            assert e.start == expected

    def test_bysetpos_last_fri_with_tz(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:tz6\n"
            "SUMMARY:月底财报\n"
            "DTSTART;TZID=Asia/Shanghai:20260626T150000\n"
            "DTEND;TZID=Asia/Shanghai:20260626T170000\n"
            "RRULE:FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1;COUNT=4\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        sh = tz.gettz("Asia/Shanghai")
        for e in events:
            assert e.start.tzinfo is not None
            assert e.start.hour == 15
            assert e.start.weekday() == 4
            expected = datetime(e.start.year, e.start.month, e.start.day, 15, 0, tzinfo=sh)
            assert e.start == expected
