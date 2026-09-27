"""Due times keep their local time between Apple Reminders and CalDAV (issue #30)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from Foundation import NSDateComponents, NSTimeZone

from icloudbridge.sources.reminders import caldav_adapter, eventkit
from icloudbridge.sources.reminders.caldav_adapter import CalDAVAdapter
from icloudbridge.sources.reminders.eventkit import (
    NS_DATE_COMPONENT_UNDEFINED_THRESHOLD,
    due_date_components,
    due_date_from_components,
)


@pytest.fixture
def mac_in(monkeypatch):
    """Set the Mac's time zone, as the conversions see it."""

    def set_zone(name: str) -> None:
        zone = ZoneInfo(name)
        monkeypatch.setattr(eventkit, "local_timezone", lambda: zone)
        monkeypatch.setattr(caldav_adapter, "local_timezone", lambda: zone)

    return set_zone


def components(year, month, day, hour=None, zone=None) -> NSDateComponents:
    """Due date components as Reminders.app sets them."""
    dc = NSDateComponents.alloc().init()
    dc.setYear_(year)
    dc.setMonth_(month)
    dc.setDay_(day)
    if hour is not None:
        dc.setHour_(hour)
        dc.setMinute_(0)
    if zone:
        dc.setTimeZone_(NSTimeZone.timeZoneWithName_(zone))
    return dc


def parse_due(due_line: str) -> datetime:
    ical = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VTODO",
            "UID:pay-rent",
            "SUMMARY:Pay rent",
            "DTSTAMP:20260901T120000Z",
            due_line,
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )
    adapter = CalDAVAdapter("https://dav.example.com", "user", "secret")
    todo = SimpleNamespace(data=ical, url="https://dav.example.com/pay-rent.ics")
    return adapter._parse_todo(todo).due_date


def utc(month, day, hour) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("month", "zone", "expected"),
    [
        (7, "Europe/London", utc(7, 1, 9)),
        # GMT on the due date, even when read during BST
        (12, "Europe/London", utc(12, 1, 10)),
        (7, "America/New_York", utc(7, 1, 14)),
        (12, "America/New_York", utc(12, 1, 15)),
    ],
)
def test_due_time_is_read_at_its_offset_on_the_due_date(month, zone, expected):
    assert due_date_from_components(components(2026, month, 1, 10, zone)) == (expected, False)


def test_floating_due_time_is_read_as_local(mac_in):
    mac_in("Europe/Malta")

    assert due_date_from_components(components(2026, 7, 1, 10)) == (utc(7, 1, 8), False)


def test_all_day_due_date_is_read_as_its_date():
    assert due_date_from_components(components(2026, 12, 1)) == (utc(12, 1, 0), True)


@pytest.mark.parametrize(
    ("due_date", "expected_day", "expected_hour"),
    [
        # 10:00 BST, as iCloudBridge writes it to the server
        (utc(9, 28, 9), 28, 10),
        (utc(12, 1, 10), 1, 10),
        (datetime(2026, 9, 28, 10, tzinfo=ZoneInfo("America/New_York")), 28, 15),
        (utc(9, 28, 23), 29, 0),
        # Floating: local already
        (datetime(2026, 9, 28, 10), 28, 10),
    ],
)
def test_due_time_is_written_in_local_time(mac_in, due_date, expected_day, expected_hour):
    mac_in("Europe/London")

    dc = due_date_components(due_date, is_all_day=False)

    assert (dc.day(), dc.hour(), dc.minute()) == (expected_day, expected_hour, 0)
    assert dc.timeZone().name() == "Europe/London"


def test_all_day_due_date_is_written_without_a_time_or_zone(mac_in):
    mac_in("America/Los_Angeles")

    dc = due_date_components(utc(12, 1, 0), is_all_day=True)

    assert (dc.year(), dc.month(), dc.day()) == (2026, 12, 1)
    assert dc.hour() >= NS_DATE_COMPONENT_UNDEFINED_THRESHOLD
    assert dc.timeZone() is None


@pytest.mark.parametrize("zone", ["Europe/London", "America/New_York", "Australia/Sydney"])
@pytest.mark.parametrize("month", [3, 7, 12])
def test_due_time_survives_round_trip_through_caldav(mac_in, zone, month):
    """Apple → CalDAV (written in UTC) → Apple, as an edit on the server does."""
    mac_in(zone)
    due_date, _ = due_date_from_components(components(2026, month, 10, 10, zone))

    on_server = parse_due(f"DUE:{due_date:%Y%m%dT%H%M%SZ}")
    dc = due_date_components(on_server, is_all_day=False)

    assert (dc.month(), dc.day(), dc.hour(), dc.minute()) == (month, 10, 10, 0)


@pytest.mark.parametrize(
    ("due_line", "expected"),
    [
        ("DUE:20260928T090000Z", utc(9, 28, 9)),
        ("DUE;TZID=America/New_York:20260928T100000", utc(9, 28, 14)),
        # Floating: the Mac's local time, BST here
        ("DUE:20260928T100000", utc(9, 28, 9)),
    ],
)
def test_caldav_due_time_is_read_as_an_instant(mac_in, due_line, expected):
    mac_in("Europe/London")

    assert parse_due(due_line) == expected
