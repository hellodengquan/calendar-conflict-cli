from datetime import datetime, timedelta, timezone

import pytest
from dateutil import tz

from calconflict.models import Event
from calconflict.parser import (
    ParseError,
    _parse_ics_line,
    _unfold_ics_lines,
    load_events,
)


class TestIcsLineParsing:
    def test_simple_line(self):
        key, params, value = _parse_ics_line("SUMMARY:Hello World")
        assert key == "SUMMARY"
        assert params == {}
        assert value == "Hello World"

    def test_line_with_params(self):
        key, params, value = _parse_ics_line(
            "DTSTART;TZID=America/New_York:20260615T093000"
        )
        assert key == "DTSTART"
        assert params == {"TZID": "America/New_York"}
        assert value == "20260615T093000"

    def test_line_with_multiple_params(self):
        key, params, value = _parse_ics_line(
            "ATTENDEE;CN=John Doe;ROLE=REQ-PARTICIPANT:mailto:john@example.com"
        )
        assert key == "ATTENDEE"
        assert params["CN"] == "John Doe"
        assert params["ROLE"] == "REQ-PARTICIPANT"
        assert value == "mailto:john@example.com"

    def test_value_contains_colon(self):
        key, params, value = _parse_ics_line("DESCRIPTION:Meet at 3:00 pm")
        assert key == "DESCRIPTION"
        assert value == "Meet at 3:00 pm"


class TestIcsUnfolding:
    def test_no_folding(self):
        text = "BEGIN:VEVENT\nSUMMARY:Test\nEND:VEVENT"
        lines = _unfold_ics_lines(text)
        assert len(lines) == 3
        assert lines[1] == "SUMMARY:Test"

    def test_single_space_fold(self):
        text = "SUMMARY:This is a very long\n description that spans\n two lines"
        lines = _unfold_ics_lines(text)
        assert len(lines) == 1
        assert lines[0] == "SUMMARY:This is a very longdescription that spanstwo lines"

    def test_tab_fold(self):
        text = "DESCRIPTION:Line1\n\tLine2\n\tLine3"
        lines = _unfold_ics_lines(text)
        assert len(lines) == 1
        assert lines[0] == "DESCRIPTION:Line1Line2Line3"

    def test_rfc5545_75col_example(self):
        summary = "A" * 70
        fold1 = "B" * 20
        fold2 = "C" * 10
        text = f"SUMMARY:{summary}\n {fold1}\n {fold2}"
        lines = _unfold_ics_lines(text)
        assert len(lines) == 1
        assert lines[0] == f"SUMMARY:{summary}{fold1}{fold2}"


class TestIcsTimezone:
    def test_utc_z_suffix(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:UTC Event\n"
            "DTSTART:20260615T120000Z\n"
            "DTEND:20260615T130000Z\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        ev = events[0]
        assert ev.start.tzinfo is not None
        assert ev.start.utcoffset() == timedelta(0)
        assert ev.start.hour == 12

    def test_tzid_param(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:NYC Event\n"
            "DTSTART;TZID=America/New_York:20260615T090000\n"
            "DTEND;TZID=America/New_York:20260615T100000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        ev = events[0]
        assert ev.start.tzinfo is not None
        nyc = tz.gettz("America/New_York")
        expected = datetime(2026, 6, 15, 9, 0, 0, tzinfo=nyc)
        assert ev.start == expected

    def test_x_wr_timezone_default(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:Shanghai Event\n"
            "DTSTART:20260615T090000\n"
            "DTEND:20260615T100000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        ev = events[0]
        assert ev.start.tzinfo is not None
        shanghai = tz.gettz("Asia/Shanghai")
        expected = datetime(2026, 6, 15, 9, 0, 0, tzinfo=shanghai)
        assert ev.start == expected

    def test_tzid_overrides_calendar_default(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "X-WR-TIMEZONE:Asia/Shanghai\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:LA Event\n"
            "DTSTART;TZID=America/Los_Angeles:20260615T090000\n"
            "DTEND;TZID=America/Los_Angeles:20260615T100000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        ev = events[0]
        la = tz.gettz("America/Los_Angeles")
        expected = datetime(2026, 6, 15, 9, 0, 0, tzinfo=la)
        assert ev.start == expected

    def test_cross_timezone_conflict_correct(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:UTC Noon\n"
            "DTSTART:20260615T120000Z\n"
            "DTEND:20260615T130000Z\n"
            "END:VEVENT\n"
            "BEGIN:VEVENT\n"
            "UID:2\n"
            "SUMMARY:Shanghai 8pm\n"
            "DTSTART;TZID=Asia/Shanghai:20260615T200000\n"
            "DTEND;TZID=Asia/Shanghai:20260615T210000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 2
        assert events[0].start == events[1].start


class TestIcsAllDayEvent:
    def test_simple_all_day(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:Holiday\n"
            "DTSTART;VALUE=DATE:20260615\n"
            "DTEND;VALUE=DATE:20260616\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        ev = events[0]
        assert ev.start == datetime(2026, 6, 15, 0, 0)
        assert ev.end == datetime(2026, 6, 16, 0, 0)
        assert ev.duration == timedelta(days=1)

    def test_single_day_all_day_same_date(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:Birthday\n"
            "DTSTART;VALUE=DATE:20260615\n"
            "DTEND;VALUE=DATE:20260615\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        ev = events[0]
        assert ev.duration == timedelta(days=1)
        assert ev.start == datetime(2026, 6, 15, 0, 0)
        assert ev.end == datetime(2026, 6, 16, 0, 0)

    def test_multi_day_all_day(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:Conference\n"
            "DTSTART;VALUE=DATE:20260615\n"
            "DTEND;VALUE=DATE:20260618\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        ev = events[0]
        assert ev.duration == timedelta(days=3)


class TestIcsAttendees:
    def test_multiple_attendees(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:Meeting\n"
            "DTSTART:20260615T090000Z\n"
            "DTEND:20260615T100000Z\n"
            "ATTENDEE:mailto:alice@example.com\n"
            "ATTENDEE:mailto:bob@example.com\n"
            "ATTENDEE:mailto:carol@example.com\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        assert len(events[0].attendees) == 3
        assert "alice@example.com" in events[0].attendees
        assert "bob@example.com" in events[0].attendees
        assert "carol@example.com" in events[0].attendees

    def test_attendee_with_params(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:Meeting\n"
            "DTSTART:20260615T090000Z\n"
            "DTEND:20260615T100000Z\n"
            "ATTENDEE;CN=Alice;ROLE=CHAIR:mailto:alice@example.com\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert "alice@example.com" in events[0].attendees


class TestIcsFoldedContent:
    def test_folded_summary(self, tmp_path):
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:This is a very long\n"
            "  meeting title that has been\n"
            "  folded across multiple lines\n"
            "DTSTART:20260615T090000Z\n"
            "DTEND:20260615T100000Z\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
        assert (
            events[0].title
            == "This is a very long meeting title that has been folded across multiple lines"
        )

    def test_folded_description_with_75cols(self, tmp_path):
        long_text = "A" * 60 + "B" * 30
        folded = "DESCRIPTION:" + "A" * 60 + "\n " + "B" * 30
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:1\n"
            "SUMMARY:Test\n"
            f"{folded}\n"
            "DTSTART:20260615T090000Z\n"
            "DTEND:20260615T100000Z\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        f = tmp_path / "test.ics"
        f.write_text(ics)
        events = load_events(f)
        assert len(events) == 1
