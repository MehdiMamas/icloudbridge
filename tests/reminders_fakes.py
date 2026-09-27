"""Stand-ins for Apple Reminders and a CalDAV server, holding lists and their items."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from itertools import count
from types import SimpleNamespace

from icloudbridge.core.reminders_sync import RemindersSyncEngine
from icloudbridge.sources.reminders.eventkit import ReminderCalendar


class FakeReminders:
    """Reminders.app: lists keyed by identifier, each in an account."""

    def __init__(self, lists: list[str], source: str = "icloud") -> None:
        self.lists: dict[str, ReminderCalendar] = {}
        self.sources: set[str] = set()
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.reminders: dict[str, list] = {}  # EventKitReminders by list title
        self.updates: list[tuple[str, dict]] = []
        self._ids = count(1)
        for title in lists:
            self.add(title, source)

    def add(self, title: str, source: str = "icloud") -> ReminderCalendar:
        """A list appearing in Reminders, with a new identifier each time."""
        calendar = ReminderCalendar(uuid=f"apple-{next(self._ids)}", title=title, source_id=source)
        self.lists[calendar.uuid] = calendar
        self.sources.add(source)
        return calendar

    def get(self, title: str) -> ReminderCalendar:
        return next(cal for cal in self.lists.values() if cal.title == title)

    def remove(self, title: str) -> None:
        """The user deleting a list in Reminders."""
        del self.lists[self.get(title).uuid]

    async def list_calendars(self) -> list[ReminderCalendar]:
        return list(self.lists.values())

    async def list_source_ids(self) -> set[str]:
        return set(self.sources)

    async def create_calendar(self, name: str) -> ReminderCalendar:
        self.created.append(name)
        return self.add(name)

    async def delete_calendar(self, calendar_id: str) -> bool:
        calendar = self.lists.pop(calendar_id, None)
        if calendar:
            self.deleted.append(calendar.title)
        return calendar is not None

    async def get_reminders(self, calendar_name: str | None = None):
        return list(self.reminders.get(calendar_name, []))

    async def update_reminder(self, uuid: str, **fields):
        """Record the update and apply the fields it sets."""
        self.updates.append((uuid, fields))
        changes = {name: value for name, value in fields.items() if value is not None}
        for reminders in self.reminders.values():
            for i, reminder in enumerate(reminders):
                if reminder.uuid == uuid:
                    reminders[i] = replace(
                        reminder, **changes, modification_date=datetime.now(timezone.utc)
                    )
                    return reminders[i]
        raise ValueError(f"Reminder not found: {uuid}")


class FakeCalDAV:
    """CalDAV server whose calendars all hold tasks, keyed by URL."""

    def __init__(self, calendars: list[str]) -> None:
        self.names: dict[str, str] = {}
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.todos: dict[str, list] = {}  # CalDAVReminders by calendar name
        self.updates: list[tuple[str, dict]] = []
        for name in calendars:
            self._add(name)

    def _add(self, name: str) -> str:
        url = f"https://dav.example.com/calendars/me/{name.lower()}/"
        self.names[url] = name
        return url

    def url_of(self, name: str) -> str:
        return next(url for url, calendar in self.names.items() if calendar == name)

    def remove(self, name: str) -> None:
        """The user deleting a calendar on the server."""
        del self.names[self.url_of(name)]

    @property
    def calendars(self):
        return [
            SimpleNamespace(name=name, url=url, get_supported_components=lambda: ["VTODO"])
            for url, name in self.names.items()
        ]

    async def list_calendars(self) -> list[dict[str, str]]:
        return [{"name": name, "url": url} for url, name in self.names.items()]

    async def list_calendar_urls(self) -> list[dict[str, str]]:
        return await self.list_calendars()

    async def create_calendar(self, name: str) -> bool:
        self.created.append(name)
        self._add(name)
        return True

    async def delete_calendar(self, calendar_url: str) -> bool:
        name = self.names.pop(calendar_url, None)
        if name:
            self.deleted.append(name)
        return name is not None

    async def get_todos(self, calendar_name: str | None = None):
        return list(self.todos.get(calendar_name, []))

    async def update_todo(self, caldav_url: str, modification_date=None, **fields):
        """Record the update and apply the fields it sets."""
        self.updates.append((caldav_url, fields))
        changes = {name: value for name, value in fields.items() if value is not None}
        for todos in self.todos.values():
            for i, todo in enumerate(todos):
                if todo.caldav_url == caldav_url:
                    modified = modification_date or datetime.now(timezone.utc)
                    todos[i] = replace(todo, **changes, last_modified=modified)
                    return todos[i]
        return None


async def make_engine(tmp_path, apple_lists, caldav_calendars, **engine_options):
    engine = RemindersSyncEngine(
        "https://dav.example.com", "user", "secret", tmp_path / "reminders.db", **engine_options
    )
    await engine.db.initialize()
    engine.reminders_adapter = FakeReminders(apple_lists)
    engine.caldav_adapter = FakeCalDAV(caldav_calendars)
    return engine, engine.reminders_adapter, engine.caldav_adapter
