"""Saved list mappings must not bring deleted lists back (issue #19)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from icloudbridge.api.routes import reminders as reminders_routes
from icloudbridge.core.config import AppConfig
from icloudbridge.core.reminders_sync import RemindersSyncEngine


class FakeReminders:
    """Reminders.app stand-in holding list names only."""

    def __init__(self, lists: list[str]) -> None:
        self.lists = list(lists)
        self.created: list[str] = []

    async def list_calendars(self):
        return [SimpleNamespace(title=name, uuid=name) for name in self.lists]

    async def create_calendar(self, name: str):
        self.lists.append(name)
        self.created.append(name)
        return SimpleNamespace(title=name, uuid=name)

    async def get_reminders(self, calendar_name: str):
        return []


class FakeCalDAV:
    """CalDAV stand-in whose calendars all hold tasks."""

    def __init__(self, calendars: list[str]) -> None:
        self.names = list(calendars)
        self.created: list[str] = []

    @property
    def calendars(self):
        return [SimpleNamespace(name=name, get_supported_components=lambda: ["VTODO"]) for name in self.names]

    async def list_calendars(self):
        return [{"name": name} for name in self.names]

    async def create_calendar(self, name: str) -> bool:
        self.names.append(name)
        self.created.append(name)
        return True

    async def get_todos(self, calendar_name: str):
        return []


async def make_engine(tmp_path, apple_lists, caldav_calendars):
    engine = RemindersSyncEngine("https://dav.example.com", "user", "secret", tmp_path / "reminders.db")
    await engine.db.initialize()
    engine.reminders_adapter = FakeReminders(apple_lists)
    engine.caldav_adapter = FakeCalDAV(caldav_calendars)
    return engine, engine.reminders_adapter, engine.caldav_adapter


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
