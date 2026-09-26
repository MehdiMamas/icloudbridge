"""A list deleted on one side must not be recreated by the next sync (issue #21)."""
from __future__ import annotations

from datetime import datetime

import pytest

from icloudbridge.api.routes import reminders as reminders_routes
from icloudbridge.core.config import AppConfig
from icloudbridge.utils.exceptions import SourceUnavailableError
from tests.reminders_fakes import make_engine


async def synced_engine(tmp_path, lists=("Work", "Home"), **engine_options):
    """An engine whose lists, the same on both sides, have each synced once."""
    engine, apple, caldav = await make_engine(tmp_path, list(lists), list(lists), **engine_options)
    for name in lists:
        await engine.sync_calendar(name, name)
    return engine, apple, caldav


async def pair_for(engine, title):
    return next(pair for pair in await engine.db.get_list_pairs() if pair["apple_title"] == title)


def delete_list(apple, caldav, side, name):
    (apple if side == "apple" else caldav).remove(name)


async def test_lists_that_sync_are_remembered(tmp_path):
    engine, apple, caldav = await synced_engine(tmp_path)

    pair = await pair_for(engine, "Work")

    assert pair["apple_uuid"] == apple.get("Work").uuid
    assert pair["caldav_url"] == caldav.url_of("Work")
    assert pair["deleted_side"] is None


@pytest.mark.parametrize("side", ["apple", "caldav"])
async def test_deleted_list_waits_for_confirmation(tmp_path, side):
    engine, apple, caldav = await synced_engine(tmp_path)
    delete_list(apple, caldav, side, "Work")

    stats = await engine.sync_calendar("Work", "Work")

    assert apple.created == caldav.created == []
    assert apple.deleted == caldav.deleted == []
    assert stats["lists_pending"] == 1
    assert (await pair_for(engine, "Work"))["deleted_side"] == side


async def test_auto_sync_does_not_bring_a_deleted_list_back(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    engine, apple, caldav = await synced_engine(tmp_path)
    apple.remove("Work")

    results = await engine.discover_and_sync_all(base_mappings={})

    assert apple.created == [] and caldav.deleted == []
    assert all(stats["errors"] == 0 for stats in results.values())


@pytest.mark.parametrize(("side", "other_side"), [("apple", "caldav"), ("caldav", "apple")])
async def test_auto_delete_removes_the_other_copy_and_its_reminders(tmp_path, side, other_side):
    engine, apple, caldav = await synced_engine(tmp_path, auto_delete_lists=True)
    for name in ("Work", "Home"):
        await engine.db.add_mapping(
            f"local-{name}", f"uid-{name}", name, f"{caldav.url_of(name)}{name}.ics", datetime.now()
        )
    delete_list(apple, caldav, side, "Work")

    stats = await engine.sync_calendar("Work", "Work")

    assert (apple if other_side == "apple" else caldav).deleted == ["Work"]
    assert stats["lists_deleted"] == 1
    assert [pair["apple_title"] for pair in await engine.db.get_list_pairs()] == ["Home"]
    assert [mapping["local_title"] for mapping in await engine.db.get_all_mappings()] == ["Home"]


async def test_auto_delete_asks_when_every_list_vanishes_at_once(tmp_path):
    engine, apple, caldav = await synced_engine(tmp_path, auto_delete_lists=True)
    apple.add("Groceries")  # never synced; Reminders is readable, just missing both lists
    apple.remove("Work")
    apple.remove("Home")

    for name in ("Work", "Home"):
        await engine.sync_calendar(name, name)

    assert caldav.deleted == []
    assert {pair["deleted_side"] for pair in await engine.db.get_list_pairs()} == {"apple"}


@pytest.mark.parametrize("auto_delete_lists", [False, True])
async def test_list_in_a_signed_out_account_is_not_treated_as_deleted(tmp_path, auto_delete_lists):
    engine, apple, caldav = await synced_engine(tmp_path, ["Work"], auto_delete_lists=auto_delete_lists)
    apple.add("Local list", source="on-my-mac")
    apple.remove("Work")
    apple.sources.discard("icloud")

    with pytest.raises(SourceUnavailableError):
        await engine.sync_calendar("Work", "Work")

    assert caldav.deleted == [] and apple.created == []
    assert (await pair_for(engine, "Work"))["deleted_side"] is None


async def test_server_listing_no_calendars_is_not_treated_as_deleted(tmp_path):
    engine, apple, caldav = await synced_engine(tmp_path, ["Work"], auto_delete_lists=True)
    caldav.names.clear()

    with pytest.raises(SourceUnavailableError):
        await engine.sync_calendar("Work", "Work")

    assert apple.deleted == []
    assert (await pair_for(engine, "Work"))["deleted_side"] is None


async def test_renamed_list_is_not_treated_as_deleted(tmp_path):
    engine, apple, caldav = await synced_engine(tmp_path, auto_delete_lists=True)
    apple.get("Work").title = "Job"

    # What auto sync asks for, pairing the server's "Work" by name
    await engine.sync_calendar("Work", "Work")

    assert apple.deleted == caldav.deleted == []
    assert all(pair["deleted_side"] is None for pair in await engine.db.get_list_pairs())


async def test_list_that_comes_back_syncs_again(tmp_path):
    engine, apple, _ = await synced_engine(tmp_path)
    work = apple.get("Work")
    apple.remove("Work")
    await engine.sync_calendar("Work", "Work")
    apple.lists[work.uuid] = work

    stats = await engine.sync_calendar("Work", "Work")

    assert "lists_pending" not in stats
    assert (await pair_for(engine, "Work"))["deleted_side"] is None


async def test_dry_run_changes_nothing(tmp_path):
    engine, apple, caldav = await synced_engine(tmp_path, auto_delete_lists=True)
    apple.remove("Work")

    stats = await engine.sync_calendar("Work", "Work", dry_run=True)

    assert stats["lists_deleted"] == 1
    assert caldav.deleted == []
    assert (await pair_for(engine, "Work"))["deleted_side"] is None


async def test_skipping_deletions_asks_instead_of_deleting(tmp_path):
    engine, apple, caldav = await synced_engine(tmp_path, auto_delete_lists=True)
    apple.remove("Work")

    await engine.sync_calendar("Work", "Work", skip_deletions=True)

    assert caldav.deleted == []
    assert (await pair_for(engine, "Work"))["deleted_side"] == "apple"


async def waiting_engine(tmp_path):
    """An engine where "Work" was deleted in Reminders and waits for the user."""
    engine, apple, caldav = await synced_engine(tmp_path)
    apple.remove("Work")
    await engine.sync_calendar("Work", "Work")
    return engine, apple, caldav, await pair_for(engine, "Work")


async def test_waiting_lists_are_listed(tmp_path):
    engine, _, _, pair = await waiting_engine(tmp_path)

    response = await reminders_routes.list_deleted_lists(engine.db)

    assert response == {
        "lists": [{"id": pair["id"], "apple_title": "Work", "caldav_name": "Work", "deleted_side": "apple"}]
    }


async def test_confirming_deletes_the_copy_and_its_saved_mapping(tmp_path):
    engine, _, caldav, pair = await waiting_engine(tmp_path)
    config = AppConfig(
        general={"data_dir": tmp_path},
        reminders={"calendar_mappings": {"Reminders": "tasks", "Work": "Work"}},
    )

    await reminders_routes.confirm_list_deletion(pair["id"], engine, config)

    assert caldav.deleted == ["Work"]
    assert await engine.db.get_list_pair(pair["id"]) is None
    assert AppConfig.load_from_file(tmp_path / "config.toml").reminders.calendar_mappings == {"Reminders": "tasks"}


async def test_confirming_refuses_once_the_list_is_back(tmp_path):
    engine, apple, caldav, pair = await waiting_engine(tmp_path)
    apple.add("Work")

    with pytest.raises(ValueError):
        await engine.confirm_list_deletion(pair["id"])

    assert caldav.deleted == []
    assert (await engine.db.get_list_pair(pair["id"]))["deleted_side"] is None


async def test_restoring_lets_the_next_sync_recreate_the_list(tmp_path):
    engine, apple, caldav, pair = await waiting_engine(tmp_path)

    await reminders_routes.restore_deleted_list(pair["id"], engine.db)
    await engine.sync_calendar("Work", "Work")

    assert apple.created == ["Work"] and caldav.deleted == []


async def test_reset_forgets_which_lists_synced(tmp_path):
    engine, _, _ = await synced_engine(tmp_path)

    await engine.reset_database()

    assert await engine.db.get_list_pairs() == []
