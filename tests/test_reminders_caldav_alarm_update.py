"""Updating a task's alarms keeps the VALARMs that didn't change (issue #28)."""
from __future__ import annotations

from datetime import datetime, timezone

from icalendar import Calendar

from icloudbridge.sources.reminders import caldav_adapter
from icloudbridge.sources.reminders.caldav_adapter import (
    CalDAVAdapter,
    CalDAVAlarm,
    _update_valarms,
)
from tests.test_reminders_alarm_conversion import DUE, parse_alarms, valarm

FIFTEEN_MINUTES = [
    "BEGIN:VALARM",
    "ACTION:AUDIO",
    "TRIGGER;RELATED=END:-PT15M",
    "ACKNOWLEDGED:20260901T120000Z",
    "X-EXTRA:kept",
    "END:VALARM",
]
FIXED_TIME = valarm("TRIGGER;VALUE=DATE-TIME:20261001T090000Z")
# As an Apple device writes one to a CalDAV account
LOCATION = [
    "BEGIN:VALARM",
    "ACTION:DISPLAY",
    "TRIGGER;VALUE=DATE-TIME:19760401T005545Z",
    "X-APPLE-PROXIMITY:ARRIVE",
    "X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-TITLE=Home:geo:35.8989,14.5146",
    "END:VALARM",
]
DOES_NOTHING = [
    "BEGIN:VALARM",
    "ACTION:NONE",
    "TRIGGER;VALUE=DATE-TIME:19760401T005545Z",
    "END:VALARM",
]


def task(*lines: str):
    ical = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VTODO",
            "UID:pay-rent",
            "SUMMARY:Pay rent",
            "DTSTAMP:20260901T120000Z",
            DUE,
            *lines,
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )
    [vtodo] = Calendar.from_ical(ical).walk("VTODO")
    return vtodo


def valarms(vtodo) -> list[str]:
    return [alarm.to_ical().decode() for alarm in vtodo.walk("VALARM")]


def test_parser_skips_alarms_it_does_not_sync():
    assert parse_alarms(DUE, *LOCATION, *DOES_NOTHING) == []


def test_update_keeps_matching_valarms_and_ones_it_does_not_sync():
    vtodo = task(*FIFTEEN_MINUTES, *FIXED_TIME, *LOCATION, *DOES_NOTHING)
    fifteen_minutes, _, location, does_nothing = valarms(vtodo)

    # The fixed-time alarm was deleted in Apple Reminders, and one an hour before added
    _update_valarms(vtodo, [CalDAVAlarm(trigger_minutes=15), CalDAVAlarm(trigger_minutes=60)])

    *kept, added = valarms(vtodo)
    assert kept == [fifteen_minutes, location, does_nothing]
    assert "TRIGGER;RELATED=END:-PT1H" in added


def test_update_keeps_an_alarm_relative_to_the_start():
    vtodo = task("DTSTART:20261001T080000Z", *valarm("TRIGGER:-PT1H"))
    before = valarms(vtodo)

    seven = datetime(2026, 10, 1, 7, tzinfo=timezone.utc)
    _update_valarms(vtodo, [CalDAVAlarm(trigger_date=seven)])

    assert valarms(vtodo) == before


class FakeServer:
    """A CalDAV server holding one task, for update_todo to load and PUT."""

    def __init__(self, vtodo):
        self.data = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{vtodo.to_ical().decode()}END:VCALENDAR\r\n"

    def put(self, url, data, headers):
        self.data = data


class FakeTodo:
    def __init__(self, client, url):
        self.client = client
        self.url = url

    def load(self):
        self.data = self.client.data


async def test_update_todo_changes_only_the_alarms_that_changed(monkeypatch):
    server = FakeServer(task(*FIFTEEN_MINUTES, *FIXED_TIME, *LOCATION))
    adapter = CalDAVAdapter("https://dav.example.com", "user", "secret")
    adapter.client = server
    monkeypatch.setattr(caldav_adapter.caldav, "Todo", FakeTodo)
    fifteen_minutes, _, location = valarms(task(*FIFTEEN_MINUTES, *FIXED_TIME, *LOCATION))

    await adapter.update_todo(
        "https://dav.example.com/pay-rent.ics", alarms=[CalDAVAlarm(trigger_minutes=15)]
    )

    [vtodo] = Calendar.from_ical(server.data).walk("VTODO")
    assert valarms(vtodo) == [fifteen_minutes, location]
