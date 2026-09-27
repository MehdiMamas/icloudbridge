"""Repeat rules must survive syncing between CalDAV and Apple Reminders (issues #23, #27)."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from icalendar import Todo

from icloudbridge.sources.reminders.caldav_adapter import (
    CalDAVAdapter,
    CalDAVRecurrence,
    _rrule,
)
from icloudbridge.sources.reminders.eventkit import (
    RECURRENCE_FREQUENCIES,
    ReminderRecurrence,
    recurrence_from_eventkit,
    recurrence_to_eventkit,
)
from tests.reminders_fakes import make_engine

WEEKDAYS = [(day, 0) for day in range(2, 7)]  # Monday to Friday
SECOND_TUESDAY = [(3, 2)]


@pytest.mark.parametrize("frequency", list(RECURRENCE_FREQUENCIES))
async def test_caldav_frequency_reaches_eventkit(tmp_path, frequency):
    engine, _, _ = await make_engine(tmp_path, [], [])
    rule = CalDAVRecurrence(
        frequency=frequency, interval=2, count=None, until=None, by_day=None, by_month_day=None
    )

    [converted] = engine._convert_recurrence_to_eventkit([rule])

    # create_reminder and update_reminder look the frequency up in this map
    assert RECURRENCE_FREQUENCIES.get(converted.frequency) == RECURRENCE_FREQUENCIES[frequency]
    assert converted.interval == 2


@pytest.mark.parametrize("frequency", list(RECURRENCE_FREQUENCIES))
async def test_apple_frequency_survives_round_trip(tmp_path, frequency):
    engine, _, _ = await make_engine(tmp_path, [], [])
    rule = ReminderRecurrence(frequency=frequency, interval=2)

    [back] = engine._convert_recurrence_to_eventkit(engine._convert_recurrence_to_caldav([rule]))

    assert (back.frequency, back.interval) == (frequency, 2)


def through_caldav(rule: CalDAVRecurrence) -> tuple[str, list[CalDAVRecurrence]]:
    """Write a rule to a task the way iCloudBridge does, and read the task back."""
    vtodo = Todo()
    vtodo.add("uid", "pay-rent")
    vtodo.add("summary", "Pay rent")
    vtodo.add("rrule", _rrule(rule))
    ical = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{vtodo.to_ical().decode()}END:VCALENDAR\r\n"
    adapter = CalDAVAdapter("https://dav.example.com", "user", "secret")
    todo = adapter._parse_todo(SimpleNamespace(data=ical, url="https://dav.example.com/x.ics"))
    return re.search(r"RRULE:[^\r\n]*", ical).group(), todo.recurrence_rules


@pytest.mark.parametrize(
    ("rule", "rrule"),
    [
        (
            ReminderRecurrence("WEEKLY", days_of_week=WEEKDAYS),
            "RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,TU,WE,TH,FR",
        ),
        (
            ReminderRecurrence("MONTHLY", days_of_month=[1, 15]),
            "RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=1,15",
        ),
        (
            ReminderRecurrence("MONTHLY", days_of_month=[-1]),
            "RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=-1",
        ),
        (
            ReminderRecurrence("MONTHLY", days_of_week=SECOND_TUESDAY),
            "RRULE:FREQ=MONTHLY;INTERVAL=1;BYDAY=2TU",
        ),
        (
            ReminderRecurrence("MONTHLY", days_of_week=[(3, 0)], set_positions=[2]),
            "RRULE:FREQ=MONTHLY;INTERVAL=1;BYDAY=TU;BYSETPOS=2",
        ),
        (
            ReminderRecurrence("MONTHLY", days_of_week=WEEKDAYS, set_positions=[-1]),
            "RRULE:FREQ=MONTHLY;INTERVAL=1;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        ),
        (
            ReminderRecurrence("YEARLY", months_of_year=[6, 12], days_of_month=[1]),
            "RRULE:FREQ=YEARLY;INTERVAL=1;BYMONTHDAY=1;BYMONTH=6,12",
        ),
        (
            ReminderRecurrence("YEARLY", weeks_of_year=[20], days_of_week=[(2, 0)]),
            "RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=MO;BYWEEKNO=20",
        ),
        (
            ReminderRecurrence("YEARLY", days_of_year=[100]),
            "RRULE:FREQ=YEARLY;INTERVAL=1;BYYEARDAY=100",
        ),
    ],
)
async def test_repeat_rule_survives_round_trip_through_caldav(tmp_path, rule, rrule):
    """Apple → CalDAV → Apple, through real EventKit rules and iCalendar text."""
    engine, _, _ = await make_engine(tmp_path, [], [])
    apple = recurrence_from_eventkit(recurrence_to_eventkit(rule))

    written, on_server = through_caldav(*engine._convert_recurrence_to_caldav([apple]))
    [back] = engine._convert_recurrence_to_eventkit(on_server)

    assert written == rrule
    assert recurrence_from_eventkit(recurrence_to_eventkit(back)) == apple


async def test_caldav_position_with_a_plus_sign(tmp_path):
    engine, _, _ = await make_engine(tmp_path, [], [])
    rule = CalDAVRecurrence("MONTHLY", 1, None, None, ["+1MO"], None)

    _, on_server = through_caldav(rule)
    [back] = engine._convert_recurrence_to_eventkit(on_server)

    assert back.days_of_week == [(2, 1)]
