from datetime import datetime, timedelta, timezone

import pytest
from dateutil import tz

from calconflict.analyzer import detect_conflicts
from calconflict.models import Event


def make_event(start: datetime, end: datetime, title: str = "Test") -> Event:
    return Event(title=title, start=start, end=end)


class TestDetectConflictsBasic:
    def test_no_events(self):
        assert detect_conflicts([]) == []

    def test_single_event(self):
        ev = make_event(
            datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 10, 0)
        )
        assert detect_conflicts([ev]) == []

    def test_no_overlap_back_to_back(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 10, 0)
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 10, 0), datetime(2026, 6, 15, 11, 0)
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 0

    def test_full_overlap(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 11, 0), "A"
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 9, 30), datetime(2026, 6, 15, 10, 30), "B"
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.duration == timedelta(hours=1)
        assert c.overlap_start == datetime(2026, 6, 15, 9, 30)
        assert c.overlap_end == datetime(2026, 6, 15, 10, 30)

    def test_partial_overlap(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 10, 0), "A"
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 9, 30), datetime(2026, 6, 15, 11, 0), "B"
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 1
        assert conflicts[0].duration == timedelta(minutes=30)

    def test_identical_events(self):
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 10, 0), "A"
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 10, 0), "B"
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 1
        assert conflicts[0].duration == timedelta(hours=1)

    def test_multiple_conflicts(self):
        evs = [
            make_event(datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 11, 0), "A"),
            make_event(datetime(2026, 6, 15, 10, 0), datetime(2026, 6, 15, 12, 0), "B"),
            make_event(datetime(2026, 6, 15, 10, 30), datetime(2026, 6, 15, 11, 30), "C"),
        ]
        conflicts = detect_conflicts(evs)
        assert len(conflicts) == 3

    def test_three_way_overlap(self):
        evs = [
            make_event(datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 12, 0), "A"),
            make_event(datetime(2026, 6, 15, 10, 0), datetime(2026, 6, 15, 13, 0), "B"),
            make_event(datetime(2026, 6, 15, 11, 0), datetime(2026, 6, 15, 14, 0), "C"),
        ]
        conflicts = detect_conflicts(evs)
        assert len(conflicts) == 3

    def test_sorted_output(self):
        evs = [
            make_event(datetime(2026, 6, 15, 14, 0), datetime(2026, 6, 15, 15, 0), "Late1"),
            make_event(datetime(2026, 6, 15, 14, 30), datetime(2026, 6, 15, 15, 30), "Late2"),
            make_event(datetime(2026, 6, 15, 9, 0), datetime(2026, 6, 15, 10, 0), "Early1"),
            make_event(datetime(2026, 6, 15, 9, 30), datetime(2026, 6, 15, 10, 30), "Early2"),
        ]
        conflicts = detect_conflicts(evs)
        assert len(conflicts) == 2
        assert conflicts[0].overlap_start < conflicts[1].overlap_start


class TestDetectConflictsWithTimezones:
    def test_same_timezone_events(self):
        sh = tz.gettz("Asia/Shanghai")
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0, tzinfo=sh),
            datetime(2026, 6, 15, 10, 0, tzinfo=sh),
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 9, 30, tzinfo=sh),
            datetime(2026, 6, 15, 10, 30, tzinfo=sh),
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 1

    def test_different_timezones_overlap(self):
        sh = tz.gettz("Asia/Shanghai")
        utc = timezone.utc
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0, tzinfo=sh),
            datetime(2026, 6, 15, 10, 0, tzinfo=sh),
            "Shanghai",
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 1, 0, tzinfo=utc),
            datetime(2026, 6, 15, 2, 0, tzinfo=utc),
            "UTC",
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 1
        assert conflicts[0].duration == timedelta(hours=1)

    def test_different_timezones_no_overlap(self):
        sh = tz.gettz("Asia/Shanghai")
        ny = tz.gettz("America/New_York")
        ev1 = make_event(
            datetime(2026, 6, 15, 9, 0, tzinfo=sh),
            datetime(2026, 6, 15, 10, 0, tzinfo=sh),
            "Shanghai AM",
        )
        ev2 = make_event(
            datetime(2026, 6, 15, 9, 0, tzinfo=ny),
            datetime(2026, 6, 15, 10, 0, tzinfo=ny),
            "NY AM",
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 0

    def test_naive_and_aware_mixed_behavior(self):
        ev_naive = make_event(
            datetime(2026, 6, 15, 9, 0),
            datetime(2026, 6, 15, 10, 0),
            "Naive",
        )
        sh = tz.gettz("Asia/Shanghai")
        ev_aware = make_event(
            datetime(2026, 6, 15, 9, 0, tzinfo=sh),
            datetime(2026, 6, 15, 10, 0, tzinfo=sh),
            "Aware",
        )
        with pytest.raises(TypeError):
            detect_conflicts([ev_naive, ev_aware])


class TestDstTransition:
    def test_before_dst_spring_forward(self):
        ny = tz.gettz("America/New_York")
        ev_before = make_event(
            datetime(2026, 3, 8, 1, 30, tzinfo=ny),
            datetime(2026, 3, 8, 2, 30, tzinfo=ny),
            "Before",
        )
        ev_after = make_event(
            datetime(2026, 3, 8, 3, 0, tzinfo=ny),
            datetime(2026, 3, 8, 4, 0, tzinfo=ny),
            "After",
        )
        conflicts = detect_conflicts([ev_before, ev_after])
        assert len(conflicts) == 0

    def test_dst_fall_back_no_double_count(self):
        ny = tz.gettz("America/New_York")
        ev1 = make_event(
            datetime(2026, 11, 1, 1, 0, tzinfo=ny),
            datetime(2026, 11, 1, 1, 30, tzinfo=ny),
            "First 1AM",
        )
        ev2 = make_event(
            datetime(2026, 11, 1, 1, 30, tzinfo=ny),
            datetime(2026, 11, 1, 2, 0, tzinfo=ny),
            "Second 1AM",
        )
        conflicts = detect_conflicts([ev1, ev2])
        assert len(conflicts) == 0


class TestPerformance:
    def test_large_number_of_events(self):
        import time

        events = []
        base = datetime(2026, 1, 1, 9, 0)
        for i in range(1000):
            start = base + timedelta(days=i // 50, minutes=(i % 50) * 15)
            end = start + timedelta(minutes=30)
            events.append(make_event(start, end, f"Event {i}"))

        start_time = time.time()
        conflicts = detect_conflicts(events)
        elapsed = time.time() - start_time

        assert elapsed < 2.0
        assert len(conflicts) > 0
