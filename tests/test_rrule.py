from datetime import datetime, timedelta, timezone

import pytest
from dateutil import tz

from calconflict.models import Event
from calconflict.parser import load_events
from calconflict.rrule import RRule, expand_rrule


class TestRRuleParsing:
    def test_parse_daily_simple(self):
        r = RRule.parse("FREQ=DAILY;COUNT=5")
        assert r.freq == "DAILY"
        assert r.count == 5
        assert r.interval == 1

    def test_parse_weekly_byday(self):
        r = RRule.parse("FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert r.freq == "WEEKLY"
        assert sorted(r.byday) == [0, 2, 4]

    def test_parse_monthly_with_until(self):
        until = "20261231T235959Z"
        r = RRule.parse(f"FREQ=MONTHLY;UNTIL={until}")
        assert r.freq == "MONTHLY"
        assert r.until is not None
        assert r.until.year == 2026
        assert r.until.month == 12
        assert r.until.day == 31

    def test_parse_interval(self):
        r = RRule.parse("FREQ=DAILY;INTERVAL=2;COUNT=10")
        assert r.interval == 2
        assert r.count == 10

    def test_parse_uppercase_days(self):
        r = RRule.parse("FREQ=WEEKLY;BYDAY=MO,WE")
        assert sorted(r.byday) == [0, 2]

    def test_parse_bymonthday(self):
        r = RRule.parse("FREQ=MONTHLY;BYMONTHDAY=1,15,-1")
        assert sorted(r.bymonthday) == [-1, 1, 15]

    def test_parse_invalid_missing_freq(self):
        with pytest.raises(ValueError, match="缺少 FREQ"):
            RRule.parse("COUNT=10")


class TestRRuleIterDaily:
    def test_daily_count(self):
        start = datetime(2026, 6, 15, 9, 0)
        r = RRule.parse("FREQ=DAILY;COUNT=5")
        dates = r.iter_dates(start)
        assert len(dates) == 5
        assert dates[0] == datetime(2026, 6, 15, 9, 0)
        assert dates[-1] == datetime(2026, 6, 19, 9, 0)

    def test_daily_interval(self):
        start = datetime(2026, 6, 15, 9, 0)
        r = RRule.parse("FREQ=DAILY;INTERVAL=3;COUNT=4")
        dates = r.iter_dates(start)
        assert len(dates) == 4
        assert dates == [
            datetime(2026, 6, 15, 9, 0),
            datetime(2026, 6, 18, 9, 0),
            datetime(2026, 6, 21, 9, 0),
            datetime(2026, 6, 24, 9, 0),
        ]

    def test_daily_until(self):
        start = datetime(2026, 6, 15, 9, 0)
        until = datetime(2026, 6, 18, 0, 0)
        r = RRule.parse("FREQ=DAILY;UNTIL=20260618T000000")
        dates = r.iter_dates(start)
        assert len(dates) == 3
        assert dates[-1] == datetime(2026, 6, 17, 9, 0)


class TestRRuleIterWeekly:
    def test_weekly_single_day(self):
        start = datetime(2026, 6, 15, 9, 0)
        r = RRule.parse("FREQ=WEEKLY;COUNT=4")
        dates = r.iter_dates(start)
        assert len(dates) == 4
        for d in dates:
            assert d.weekday() == 0
        assert dates[-1] == datetime(2026, 7, 6, 9, 0)

    def test_weekly_byday_mwf(self):
        start = datetime(2026, 6, 15, 9, 0)
        r = RRule.parse("FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=6")
        dates = r.iter_dates(start)
        assert len(dates) == 6
        assert dates[0].weekday() == 0
        assert dates[1].weekday() == 2
        assert dates[2].weekday() == 4
        assert dates[3].weekday() == 0

    def test_weekly_byday_with_interval(self):
        start = datetime(2026, 6, 15, 9, 0)
        r = RRule.parse("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;COUNT=3")
        dates = r.iter_dates(start)
        assert len(dates) == 3
        assert dates == [
            datetime(2026, 6, 15, 9, 0),
            datetime(2026, 6, 29, 9, 0),
            datetime(2026, 7, 13, 9, 0),
        ]


class TestRRuleIterMonthly:
    def test_monthly_by_day_of_month(self):
        start = datetime(2026, 6, 5, 16, 0)
        r = RRule.parse("FREQ=MONTHLY;COUNT=4")
        dates = r.iter_dates(start)
        assert len(dates) == 4
        assert dates[0] == datetime(2026, 6, 5, 16, 0)
        assert dates[1] == datetime(2026, 7, 5, 16, 0)
        assert dates[3] == datetime(2026, 9, 5, 16, 0)

    def test_monthly_bymonthday_15(self):
        start = datetime(2026, 6, 15, 10, 0)
        r = RRule.parse("FREQ=MONTHLY;BYMONTHDAY=15;COUNT=3")
        dates = r.iter_dates(start)
        assert len(dates) == 3
        for d in dates:
            assert d.day == 15

    def test_monthly_leap_month_end(self):
        start = datetime(2026, 1, 31, 9, 0)
        r = RRule.parse("FREQ=MONTHLY;COUNT=3")
        dates = r.iter_dates(start)
        assert len(dates) == 3
        assert dates[0].day == 31
        assert dates[1].day == 28
        assert dates[2].day == 31

    def test_monthly_until(self):
        start = datetime(2026, 6, 1, 9, 0)
        r = RRule.parse("FREQ=MONTHLY;UNTIL=20260930T235959")
        dates = r.iter_dates(start)
        assert len(dates) == 4
        assert dates[-1].month == 9


class TestExpandRRuleEvent:
    def test_expand_daily_preserves_fields(self):
        base = Event(
            title="Daily Standup",
            start=datetime(2026, 6, 15, 10, 0),
            end=datetime(2026, 6, 15, 10, 15),
            location="线上",
            attendees=["a@x.com", "b@x.com"],
            id="evt-1",
        )
        rule = RRule.parse("FREQ=DAILY;COUNT=3")
        expanded = expand_rrule(base, rule)
        assert len(expanded) == 3
        for i, e in enumerate(expanded):
            assert e.title == "Daily Standup"
            assert e.location == "线上"
            assert e.attendees == ["a@x.com", "b@x.com"]
            assert e.duration == timedelta(minutes=15)
            assert e.id == f"evt-1-{i}"

    def test_expand_with_exdates(self):
        base = Event(
            title="Standup",
            start=datetime(2026, 6, 15, 10, 0),
            end=datetime(2026, 6, 15, 10, 15),
        )
        rule = RRule.parse("FREQ=DAILY;COUNT=5")
        exdates = [
            datetime(2026, 6, 16, 10, 0),
            datetime(2026, 6, 18, 10, 0),
        ]
        expanded = expand_rrule(base, rule, exdates)
        days = {e.start.day for e in expanded}
        assert 16 not in days
        assert 18 not in days
        assert len(expanded) == 3

    def test_expand_with_timezone_aware(self):
        sh = tz.gettz("Asia/Shanghai")
        base = Event(
            title="Weekly",
            start=datetime(2026, 6, 15, 9, 0, tzinfo=sh),
            end=datetime(2026, 6, 15, 10, 0, tzinfo=sh),
        )
        rule = RRule.parse("FREQ=WEEKLY;COUNT=3")
        expanded = expand_rrule(base, rule)
        assert len(expanded) == 3
        for e in expanded:
            assert e.start.tzinfo is not None
            assert e.start.hour == 9
        assert expanded[-1].start.day == 29


class TestIcsWithRRule:
    def test_weekly_rrule_expands_in_ics(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:w1\n"
            "SUMMARY:周例会\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T090000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T100000\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 4
        for e in events:
            assert e.start.weekday() == 0
        assert events[0].start.month == 6 and events[0].start.day == 15
        assert events[-1].start.day == 6

    def test_daily_weekdays_rrule(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:d1\n"
            "SUMMARY:Daily\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T100000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T101500\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=10\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 10
        for e in events:
            assert e.start.weekday() < 5

    def test_monthly_rrule_with_exdates(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:m1\n"
            "SUMMARY:月度评审\n"
            "DTSTART;TZID=Asia/Shanghai:20260605T160000\n"
            "DTEND;TZID=Asia/Shanghai:20260605T170000\n"
            "RRULE:FREQ=MONTHLY;BYMONTHDAY=5;COUNT=6\n"
            "EXDATE;TZID=Asia/Shanghai:20260705T160000,20260905T160000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        months = {e.start.month for e in events}
        assert 7 not in months
        assert 9 not in months
        assert len(events) == 4

    def test_recurring_creates_conflicts(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:r1\n"
            "SUMMARY:每周一例会\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T090000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T100000\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4\n"
            "END:VEVENT\n"
            "BEGIN:VEVENT\n"
            "UID:r2\n"
            "SUMMARY:6月15日培训\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T093000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T103000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        from calconflict.analyzer import detect_conflicts
        conflicts = detect_conflicts(events)
        assert len(conflicts) == 1
        assert conflicts[0].duration == timedelta(minutes=30)
