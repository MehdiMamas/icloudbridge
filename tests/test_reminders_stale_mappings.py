"""Saved list mappings must not bring deleted lists back (issue #19)."""
from __future__ import annotations

import pytest

from icloudbridge.api.routes import reminders as reminders_routes
from icloudbridge.core.config import AppConfig
from tests.reminders_fakes import make_engine


@pytest.mark.parametrize("dry_run", [False, True])
async def test_pair_missing_on_both_sides_is_not_created(tmp_path, dry_run):
    engine, apple, caldav = await make_engine(tmp_path, ["Reminders"], ["tasks"])

    stats = await engine.sync_calendar("Misspeled", "Misspeled", dry_run=dry_run)

    assert apple.created == [] and caldav.created == []
    assert stats["errors"] == 0


async def test_missing_apple_list_is_still_created_from_caldav(tmp_path):
    """Mapping a CalDAV calendar to a new Apple list must keep working."""
    engine, apple, caldav = await make_engine(tmp_path, ["Reminders"], ["Work"])

    await engine.sync_calendar("Job", "Work")

    assert apple.created == ["Job"] and caldav.created == []


async def test_auto_sync_ignores_stale_saved_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    engine, apple, caldav = await make_engine(tmp_path, ["Reminders"], [])

    results = await engine.discover_and_sync_all(base_mappings={"Reminders": "tasks", "Misspeled": "Misspeled"})

    assert apple.created == [] and caldav.created == ["tasks"]
    assert all(stats["errors"] == 0 for stats in results.values())


async def test_reset_restores_default_list_settings(tmp_path):
    config = AppConfig(
        general={"data_dir": tmp_path},
        reminders={"sync_mode": "manual", "calendar_mappings": {"Misspeled": "Misspeled"}},
    )
    engine, _, _ = await make_engine(tmp_path, [], [])

    await reminders_routes.reset_database(engine, config)

    saved = AppConfig.load_from_file(tmp_path / "config.toml")
    assert saved.reminders.calendar_mappings == {"Reminders": "tasks"}
    assert saved.reminders.sync_mode == "auto"
