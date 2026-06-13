from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dateutil import parser as date_parser
from dateutil import tz

from .models import Event


class ParseError(Exception):
    pass


def _parse_datetime(value: str) -> datetime:
    try:
        return date_parser.parse(value)
    except (ValueError, TypeError) as exc:
        raise ParseError(f"无法解析时间: {value}") from exc


def load_events(path: str | Path) -> List[Event]:
    p = Path(path)
    if not p.exists():
        raise ParseError(f"文件不存在: {p}")
    suffix = p.suffix.lower()
    if suffix == ".json":
        return _load_json(p)
    elif suffix == ".csv":
        return _load_csv(p)
    elif suffix in (".ics", ".ical"):
        return _load_ics(p)
    raise ParseError(f"不支持的文件格式: {suffix}（支持 .json/.csv/.ics）")


def _load_json(path: Path) -> List[Event]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, list):
        raise ParseError("JSON 顶层必须是数组")
    events: List[Event] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ParseError(f"第 {idx} 项不是对象")
        try:
            events.append(
                Event(
                    title=str(item["title"]),
                    start=_parse_datetime(str(item["start"])),
                    end=_parse_datetime(str(item["end"])),
                    location=item.get("location"),
                    attendees=list(item.get("attendees", []) or []),
                    id=str(item.get("id", idx)),
                )
            )
        except KeyError as exc:
            raise ParseError(f"第 {idx} 项缺少字段: {exc}") from exc
    return events


def _load_csv(path: Path) -> List[Event]:
    events: List[Event] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                try:
                    events.append(
                        Event(
                            title=row["title"].strip(),
                            start=_parse_datetime(row["start"].strip()),
                            end=_parse_datetime(row["end"].strip()),
                            location=row.get("location", "").strip() or None,
                            attendees=[
                                a.strip()
                                for a in (row.get("attendees", "") or "").split(";")
                                if a.strip()
                            ],
                            id=str(idx),
                        )
                    )
                except KeyError as exc:
                    raise ParseError(f"第 {idx} 行缺少字段: {exc}") from exc
    except csv.Error as exc:
        raise ParseError(f"CSV 解析失败: {exc}") from exc
    return events


_MULTI_VALUE_KEYS = {"ATTENDEE"}


def _unfold_ics_lines(text: str) -> List[str]:
    lines = text.splitlines()
    unfolded: List[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith(" ") or line.startswith("\t"):
            if unfolded:
                unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _parse_ics_line(line: str) -> Tuple[str, Dict[str, str], str]:
    colon_pos = -1
    i = 0
    while i < len(line):
        c = line[i]
        if c == ":" and not (i > 0 and line[i - 1] == "\\"):
            colon_pos = i
            break
        i += 1
    if colon_pos < 0:
        return line, {}, ""
    key_part = line[:colon_pos]
    value = line[colon_pos + 1 :]
    key = key_part
    params: Dict[str, str] = {}
    if ";" in key_part:
        parts = key_part.split(";")
        key = parts[0]
        for p in parts[1:]:
            if "=" in p:
                pk, pv = p.split("=", 1)
                params[pk] = pv
            else:
                params[p] = ""
    return key, params, value


def _load_ics(path: Path) -> List[Event]:
    text = path.read_text(encoding="utf-8")
    lines = _unfold_ics_lines(text)

    tz_cache: Dict[str, timezone] = {}
    calendar_tz: Optional[timezone] = None

    events_raw: List[dict] = []
    current: Optional[dict] = None

    for line in lines:
        key, params, value = _parse_ics_line(line)

        if key == "BEGIN" and value == "VEVENT":
            current = {}
            continue
        if key == "END" and value == "VEVENT":
            if current is not None:
                events_raw.append(current)
            current = None
            continue
        if current is None:
            if key == "X-WR-TIMEZONE":
                calendar_tz = _resolve_tz(value, tz_cache)
            continue

        if key in _MULTI_VALUE_KEYS:
            current.setdefault(key, []).append((params, value))
        else:
            current[key] = (params, value)

    events: List[Event] = []
    for idx, raw in enumerate(events_raw):
        dtstart_item = raw.get("DTSTART")
        dtend_item = raw.get("DTEND")
        if not dtstart_item or not dtend_item:
            continue

        start_params, start_val = dtstart_item
        end_params, end_val = dtend_item

        start_is_date = start_params.get("VALUE") == "DATE"
        end_is_date = end_params.get("VALUE") == "DATE"

        start_tzid = start_params.get("TZID")
        end_tzid = end_params.get("TZID")

        if start_is_date and end_is_date:
            start_dt = _parse_ics_date(start_val)
            end_dt = _parse_ics_date(end_val)
            if end_dt == start_dt:
                end_dt = start_dt + timedelta(days=1)
            events.append(
                Event(
                    title=raw.get("SUMMARY", ("", f"Event {idx + 1}"))[1],
                    start=start_dt,
                    end=end_dt,
                    location=raw.get("LOCATION", (None, None))[1] or None,
                    attendees=_parse_ics_attendees(raw),
                    id=raw.get("UID", ("", str(idx)))[1],
                )
            )
            continue

        start_dt = _parse_ics_datetime_tz(
            start_val, start_tzid, calendar_tz, tz_cache
        )
        end_dt = _parse_ics_datetime_tz(
            end_val, end_tzid, calendar_tz, tz_cache
        )

        summary_val = raw.get("SUMMARY")
        title = summary_val[1] if isinstance(summary_val, tuple) else (
            summary_val if summary_val else f"Event {idx + 1}"
        )
        loc_val = raw.get("LOCATION")
        location = None
        if isinstance(loc_val, tuple):
            location = loc_val[1] or None
        elif loc_val:
            location = loc_val
        uid_val = raw.get("UID")
        eid = uid_val[1] if isinstance(uid_val, tuple) else (
            uid_val if uid_val else str(idx)
        )

        events.append(
            Event(
                title=title,
                start=start_dt,
                end=end_dt,
                location=location,
                attendees=_parse_ics_attendees(raw),
                id=eid,
            )
        )
    return events


def _resolve_tz(tz_name: str, cache: Dict[str, timezone]) -> Optional[timezone]:
    if tz_name in cache:
        return cache[tz_name]
    try:
        tzinfo = tz.gettz(tz_name)
        if tzinfo is not None:
            cache[tz_name] = tzinfo
            return tzinfo
    except Exception:
        pass
    return None


def _parse_ics_date(value: str) -> datetime:
    value = value.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", value)
    if m:
        y, mo, d = m.groups()
        return datetime(int(y), int(mo), int(d))
    raise ParseError(f"无法解析日期: {value}")


def _parse_ics_datetime_tz(
    value: str,
    tzid: Optional[str],
    default_tz: Optional[timezone],
    tz_cache: Dict[str, timezone],
) -> datetime:
    value = value.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)$", value)
    if not m:
        return _parse_datetime(value)

    y, mo, d, h, mi, s, z_flag = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))

    if z_flag == "Z":
        return dt.replace(tzinfo=timezone.utc)

    if tzid:
        tzinfo = _resolve_tz(tzid, tz_cache)
        if tzinfo is not None:
            return dt.replace(tzinfo=tzinfo)

    if default_tz is not None:
        return dt.replace(tzinfo=default_tz)

    return dt


def _parse_ics_attendees(raw: dict) -> List[str]:
    result: List[str] = []
    for k, v in raw.items():
        if not k.startswith("ATTENDEE"):
            continue
        if isinstance(v, list):
            items = [item[1] if isinstance(item, tuple) else item for item in v]
        elif isinstance(v, tuple):
            items = [v[1]]
        else:
            items = [v]
        for item in items:
            if item.startswith("mailto:"):
                result.append(item[7:])
            else:
                result.append(item)
    return result
