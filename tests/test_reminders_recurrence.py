"""Repeat rules must keep their frequency between CalDAV and Apple Reminders (issue #23)."""
from __future__ import annotations

import pytest

from icloudbridge.sources.reminders.caldav_adapter import CalDAVRecurrence
from icloudbridge.sources.reminders.eventkit import RECURRENCE_FREQUENCIES, ReminderRecurrence
from tests.reminders_fakes import make_engine


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
