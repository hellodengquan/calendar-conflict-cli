from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dateutil import parser as date_parser

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


def _load_ics(path: Path) -> List[Event]:
    text = path.read_text(encoding="utf-8")
    events_raw: List[dict] = []
    current: Optional[dict] = None
    key = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("BEGIN:VEVENT"):
            current = {}
            key = None
            continue
        if line.startswith("END:VEVENT"):
            if current is not None:
                events_raw.append(current)
            current = None
            continue
        if current is None:
            continue
        if line.startswith(" ") or line.startswith("\t"):
            if key is not None:
                if key in _MULTI_VALUE_KEYS and isinstance(current.get(key), list):
                    current[key][-1] = current[key][-1] + line[1:]
                elif key in current:
                    current[key] = current[key] + line[1:]
            continue
        if ":" in line:
            raw_key, _, value = line.partition(":")
            key = raw_key
            if ";" in key:
                key = key.split(";", 1)[0]
            if key in _MULTI_VALUE_KEYS:
                current.setdefault(key, []).append(value)
            else:
                current[key] = value
    events: List[Event] = []
    for idx, raw in enumerate(events_raw):
        dtstart = raw.get("DTSTART", "")
        dtend = raw.get("DTEND", "")
        if not dtstart or not dtend:
            continue
        events.append(
            Event(
                title=raw.get("SUMMARY", f"Event {idx + 1}"),
                start=_parse_ics_datetime(dtstart),
                end=_parse_ics_datetime(dtend),
                location=raw.get("LOCATION") or None,
                attendees=_parse_ics_attendees(raw),
                id=raw.get("UID", str(idx)),
            )
        )
    return events


def _parse_ics_datetime(value: str) -> datetime:
    value = value.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?$", value)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    m2 = re.match(r"^(\d{4})(\d{2})(\d{2})$", value)
    if m2:
        y, mo, d = m2.groups()
        return datetime(int(y), int(mo), int(d))
    return _parse_datetime(value)


def _parse_ics_attendees(raw: dict) -> List[str]:
    result: List[str] = []
    for k, v in raw.items():
        if not k.startswith("ATTENDEE"):
            continue
        values = v if isinstance(v, list) else [v]
        for item in values:
            if item.startswith("mailto:"):
                result.append(item[7:])
            else:
                result.append(item)
    return result
