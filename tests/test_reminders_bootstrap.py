"""Reminders matched by title and due date are saved, so they aren't duplicated (issue #29)."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.reminders_fakes import make_engine
from tests.test_reminders_alarm_sync import APPLE, CALDAV, EDITED, SYNCED

# The same reminder on both sides, never synced by iCloudBridge
LOCAL = replace(APPLE, uuid="apple-uuid")
REMOTE = replace(
    CALDAV, uid="server-uid", caldav_url="https://dav.example.com/calendars/me/reminders/x.ics"
)
NOTHING_TO_DO = {
    "created_local": 0,
    "created_remote": 0,
    "updated_local": 0,
    "updated_remote": 0,
    "unchanged": 1,
}


async def unmapped_pair(tmp_path, local=LOCAL, remote=REMOTE):
    engine, reminders, server = await make_engine(tmp_path, ["Reminders"], ["Reminders"])
    reminders.reminders["Reminders"] = [local]
    server.todos["Reminders"] = [remote]
    return engine, reminders, server


async def another_list_synced(engine):
    """Another list's reminder has a mapping."""
    await engine.db.add_mapping(
        "elsewhere", "elsewhere", "Other", "https://dav.example.com/other.ics", SYNCED
    )


async def next_sync(engine) -> dict:
    """What the next sync would do, without doing it."""
    stats = await engine.sync_calendar("Reminders", "Reminders", dry_run=True)
    return {key: stats[key] for key in NOTHING_TO_DO}


@pytest.mark.parametrize(
    ("local", "remote"),
    [
        (LOCAL, REMOTE),
        (replace(LOCAL, modification_date=EDITED), REMOTE),
        (LOCAL, replace(REMOTE, last_modified=EDITED)),
        # CalDAV drops fractions of a second, so a second apart counts as the same
        (LOCAL, replace(REMOTE, last_modified=SYNCED + timedelta(seconds=1))),
    ],
    ids=["unchanged", "apple-newer", "server-newer", "a-second-apart"],
)
async def test_matched_pair_is_saved_and_not_created_again(tmp_path, local, remote):
    engine, _, _ = await unmapped_pair(tmp_path, local, remote)

    await engine.sync_calendar("Reminders", "Reminders")

    [mapping] = await engine.db.get_all_mappings()
    assert (mapping["local_uuid"], mapping["remote_uid"]) == ("apple-uuid", "server-uid")
    assert engine._stored_fingerprints(mapping) is not None
    await another_list_synced(engine)
    assert await next_sync(engine) == NOTHING_TO_DO


async def test_list_is_matched_when_other_lists_have_mappings(tmp_path):
    engine, _, _ = await unmapped_pair(tmp_path)
    await another_list_synced(engine)

    assert await next_sync(engine) == NOTHING_TO_DO


async def test_list_with_mapped_reminders_does_not_match_new_ones_by_title(tmp_path):
    """Matching by title only happens while none of a list's reminders are mapped."""
    engine, reminders, server = await unmapped_pair(tmp_path)
    await engine.sync_calendar("Reminders", "Reminders")
    reminders.reminders["Reminders"].append(replace(LOCAL, uuid="new-apple", title="Buy milk"))
    server.todos["Reminders"].append(replace(REMOTE, uid="new-server", summary="Buy milk"))

    counts = await next_sync(engine)

    assert (counts["created_local"], counts["created_remote"]) == (1, 1)


async def test_open_reminder_is_matched_among_completed_ones(tmp_path):
    """A shopping list keeps what was bought: one open "Pay rent" among completed ones."""
    bought = [
        replace(LOCAL, uuid=f"bought-{n}", completed=True, recurrence_rules=[]) for n in range(3)
    ]
    engine, reminders, _ = await unmapped_pair(tmp_path)
    reminders.reminders["Reminders"] += bought

    assert await next_sync(engine) == NOTHING_TO_DO


async def test_several_open_reminders_with_the_same_title_are_not_matched(tmp_path):
    engine, reminders, _ = await unmapped_pair(tmp_path)
    reminders.reminders["Reminders"].append(replace(LOCAL, uuid="another-apple-uuid"))

    counts = await next_sync(engine)

    assert (counts["created_local"], counts["created_remote"]) == (1, 2)
