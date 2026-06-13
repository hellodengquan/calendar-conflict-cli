from datetime import datetime, timedelta, timezone

import pytest
from dateutil import tz

from calconflict.analyzer import find_gaps
from calconflict.models import Event


def make_event(start: datetime, end: datetime, title: str = "Test") -> Event:
    return Event(title=title, start=start, end=end)


class TestFindGapsEdgeCases:
    def test_empty_events(self):
        gaps = find_gaps([])
        assert gaps == []

    def test_single_event_gaps_before_and_after(self):
        ev = make_event(
            datetime(2026, 6, 15, 10, 0),
            datetime(2026, 6, 15, 11, 0),
        )
        gaps = find_gaps([ev], min_duration=timedelta(minutes=30))
        assert len(gaps) == 2
        assert gaps[0].end == ev.start
        assert gaps[1].start == ev.end

    def test_single_event_fills_entire_work_day(self):
        ev = make_event(
            datetime(2026, 6, 15, 9, 0),
            datetime(2026, 6, 15, 18, 0),
        )
        gaps = find_gaps([ev])
        assert len(gaps) == 0

    def test_gaps_smaller_than_min_are_filtered(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0),
            datetime(2026, 6, 15, 10, 0),
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 10, 15),
            datetime(2026, 6, 15, 11, 0),
        )
        gaps = find_gaps([ev1, ev2], min_duration=timedelta(minutes=30))
        gap_starts = [g.start for g in gaps]
        assert not any(
            datetime(2026, 6, 15, 10, 0) < g.start < datetime(2026, 6, 15, 10, 30)
            for g in gaps
        )


class TestFindGapsWorkHours:
    def test_default_work_hours_9_to_18(self):
        ev = make_event(
            datetime(2026, 6, 15, 12, 0),
            datetime(2026, 6, 15, 13, 0),
        )
        gaps = find_gaps([ev], min_duration=timedelta(minutes=30))
        assert len(gaps) == 2
        assert gaps[0].start.hour == 9
        assert gaps[0].end.hour == 12
        assert gaps[1].start.hour == 13
        assert gaps[1].end.hour == 18

    def test_custom_work_hours(self):
        ev = make_event(
            datetime(2026, 6, 15, 10, 0),
            datetime(2026, 6, 15, 11, 0),
        )
        gaps = find_gaps(
            [ev],
            min_duration=timedelta(minutes=30),
            work_start_hour=8,
            work_end_hour=17,
        )
        assert len(gaps) == 2
        assert gaps[0].start.hour == 8
        assert gaps[-1].end.hour == 17

    def test_event_completely_before_work_hours(self):
        ev = make_event(
            datetime(2026, 6, 15, 6, 0),
            datetime(2026, 6, 15, 8, 0),
        )
        gaps = find_gaps([ev], min_duration=timedelta(minutes=30))
        assert len(gaps) == 1
        assert gaps[0].start.hour == 9
        assert gaps[0].end.hour == 18

    def test_event_completely_after_work_hours(self):
        ev = make_event(
            datetime(2026, 6, 15, 19, 0),
            datetime(2026, 6, 15, 20, 0),
        )
        gaps = find_gaps([ev], min_duration=timedelta(minutes=30))
        assert len(gaps) == 1
        assert gaps[0].start.hour == 9
        assert gaps[0].end.hour == 18


class TestFindGapsMultiDay:
    def test_two_separate_days(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 10, 0),
            datetime(2026, 6, 15, 11, 0),
        )
        ev2 = make_event(
            datetime(2026, 6, 16, 14, 0),
            datetime(2026, 6, 16, 15, 0),
        )
        gaps = find_gaps([ev1, ev2], min_duration=timedelta(hours=1))
        day1 = [g for g in gaps if g.start.day == 15]
        day2 = [g for g in gaps if g.start.day == 16]
        assert len(day1) == 2
        assert len(day2) == 2

    def test_cross_day_event_produces_gaps_both_days(self):
        ev = make_event(
            datetime(2026, 6, 15, 16, 0),
            datetime(2026, 6, 16, 10, 0),
            "Cross-day",
        )
        gaps = find_gaps([ev], min_duration=timedelta(minutes=30))
        day1 = [g for g in gaps if g.start.day == 15]
        day2 = [g for g in gaps if g.start.day == 16]
        assert len(day1) == 1
        assert day1[0].start.hour == 9
        assert day1[0].end.hour == 16
        assert len(day2) == 1
        assert day2[0].start.hour == 10
        assert day2[0].end.hour == 18

    def test_single_all_day_event_no_gaps_in_event_day(self):
        ev = make_event(
            datetime(2026, 6, 15, 0, 0),
            datetime(2026, 6, 16, 0, 0),
            "All Day",
        )
        gaps = find_gaps(
            [ev],
            min_duration=timedelta(minutes=30),
            from_date=datetime(2026, 6, 15, 0, 0),
            to_date=datetime(2026, 6, 15, 23, 59, 59),
        )
        assert len(gaps) == 0

    def test_three_day_all_day_event_no_gaps_in_range(self):
        ev = make_event(
            datetime(2026, 6, 15, 0, 0),
            datetime(2026, 6, 18, 0, 0),
            "Conference",
        )
        gaps = find_gaps(
            [ev],
            min_duration=timedelta(minutes=30),
            from_date=datetime(2026, 6, 15, 0, 0),
            to_date=datetime(2026, 6, 17, 23, 59, 59),
        )
        assert len(gaps) == 0


class TestFindGapsWithDateRange:
    def test_from_date_excludes_prior_days(self):
        ev1 = make_event(
            datetime(2026, 6, 14, 10, 0),
            datetime(2026, 6, 14, 11, 0),
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 10, 0),
            datetime(2026, 6, 15, 11, 0),
        )
        gaps = find_gaps(
            [ev1, ev2],
            min_duration=timedelta(minutes=30),
            from_date=datetime(2026, 6, 15, 0, 0),
        )
        days = {g.start.day for g in gaps}
        assert 14 not in days
        assert 15 in days

    def test_to_date_excludes_later_days(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 10, 0),
            datetime(2026, 6, 15, 11, 0),
        )
        ev2 = make_event(
            datetime(2026, 6, 16, 10, 0),
            datetime(2026, 6, 16, 11, 0),
        )
        gaps = find_gaps(
            [ev1, ev2],
            min_duration=timedelta(minutes=30),
            to_date=datetime(2026, 6, 15, 23, 59, 59),
        )
        days = {g.start.day for g in gaps}
        assert 15 in days
        assert 16 not in days

    def test_from_and_to_date_range(self):
        evs = [
            make_event(
                datetime(2026, 6, d, 10, 0),
                datetime(2026, 6, d, 11, 0),
            )
            for d in range(14, 18)
        ]
        gaps = find_gaps(
            evs,
            min_duration=timedelta(minutes=30),
            from_date=datetime(2026, 6, 15, 0, 0),
            to_date=datetime(2026, 6, 16, 23, 59, 59),
        )
        days = {g.start.day for g in gaps}
        assert days == {15, 16}


class TestFindGapsWithTimezones:
    def test_aware_datetimes_preserve_tz(self):
        sh = tz.gettz("Asia/Shanghai")
        ev = make_event(
            datetime(2026, 6, 15, 12, 0, tzinfo=sh),
            datetime(2026, 6, 15, 13, 0, tzinfo=sh),
        )
        gaps = find_gaps([ev], min_duration=timedelta(minutes=30))
        assert len(gaps) == 2
        assert gaps[0].start.tzinfo is not None
        assert gaps[0].start.hour == 9
        assert gaps[-1].end.hour == 18


class TestFindGapsMerging:
    def test_overlapping_events_merge_before_gap(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0),
            datetime(2026, 6, 15, 11, 0),
            "A",
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 10, 0),
            datetime(2026, 6, 15, 12, 0),
            "B",
        )
        gaps = find_gaps([ev1, ev2], min_duration=timedelta(minutes=30))
        afternoon = [g for g in gaps if g.start.hour >= 12]
        assert len(afternoon) == 1
        assert afternoon[0].start.hour == 12
        assert afternoon[0].end.hour == 18
