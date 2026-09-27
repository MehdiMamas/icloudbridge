"""EventKit adapter for interfacing with Apple Reminders.app."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import EventKit
from EventKit import (
    EKAlarm,
    EKAlarmProximityNone,
    EKEntityTypeReminder,
    EKEventStore,
    EKRecurrenceDayOfWeek,
    EKRecurrenceEnd,
    EKRecurrenceFrequency,
    EKRecurrenceFrequencyDaily,
    EKRecurrenceFrequencyWeekly,
    EKRecurrenceFrequencyMonthly,
    EKRecurrenceFrequencyYearly,
    EKRecurrenceRule,
    EKReminder,
)
from Foundation import NSCalendar, NSDateComponents, NSTimeZone

from icloudbridge.utils.datetime_utils import local_timezone, safe_fromtimestamp
from icloudbridge.utils.exceptions import SourceUnavailableError
from icloudbridge.utils.runtime_health import log_interpreter_status

logger = logging.getLogger(__name__)


def normalize_date(dt: Any) -> datetime | None:
    """
    Convert various date types to Python datetime with UTC timezone.

    Handles:
    - Python datetime objects (ensures UTC timezone)
    - Apple NSDate objects (uses timeIntervalSince1970())
    - Any object with timestamp() method
    - Any object with isoformat() method
    - None values

    Args:
        dt: Date object to normalize (datetime, NSDate, or other date-like object)

    Returns:
        Normalized datetime with UTC timezone, or None if conversion fails
    """
    if dt is None:
        return None

    # Already a Python datetime - just ensure UTC timezone
    if isinstance(dt, datetime):
        tz = getattr(dt, "tzinfo", None)
        if tz is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # Try to get Unix timestamp
    timestamp = None

    # Try Python's timestamp() method first
    timestamp_getter = getattr(dt, "timestamp", None)
    if callable(timestamp_getter):
        try:
            timestamp = float(timestamp_getter())
        except Exception:
            timestamp = None

    # Try Apple's NSDate method timeIntervalSince1970()
    if timestamp is None:
        alt_getter = getattr(dt, "timeIntervalSince1970", None)
        if callable(alt_getter):
            try:
                timestamp = float(alt_getter())
            except Exception:
                timestamp = None

    # Convert timestamp to datetime
    if timestamp is not None:
        return safe_fromtimestamp(timestamp, tz=timezone.utc)

    # Try isoformat parsing as last resort
    iso_getter = getattr(dt, "isoformat", None)
    if callable(iso_getter):
        try:
            parsed = datetime.fromisoformat(iso_getter())
            tz = getattr(parsed, "tzinfo", None)
            if tz is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass

    # Could not convert
    logger.warning(f"Could not normalize date of type {type(dt)}: {dt}")
    return None


@dataclass
class ReminderAlarm:
    """Represents an alarm/notification for a reminder."""

    trigger_date: datetime | None = None
    relative_offset: int | None = None  # Seconds before/after due date


@dataclass
class ReminderRecurrence:
    """Represents a recurrence rule for a reminder."""

    frequency: str  # DAILY, WEEKLY, MONTHLY, YEARLY
    interval: int = 1  # Every X days/weeks/months/years
    end_date: datetime | None = None
    occurrence_count: int | None = None
    days_of_week: list[int] = field(default_factory=list)  # 0=Sunday, 1=Monday, etc.
    days_of_month: list[int] | None = None  # Days of month (1-31) for monthly recurrence


# ReminderRecurrence.frequency values (the RRULE FREQ names) and their EventKit frequencies
RECURRENCE_FREQUENCIES = {
    "DAILY": EKRecurrenceFrequencyDaily,
    "WEEKLY": EKRecurrenceFrequencyWeekly,
    "MONTHLY": EKRecurrenceFrequencyMonthly,
    "YEARLY": EKRecurrenceFrequencyYearly,
}


def is_location_alarm(alarm: EKAlarm) -> bool:
    """Whether an alarm fires on arriving at or leaving a place, rather than at a time."""
    return alarm.structuredLocation() is not None or alarm.proximity() != EKAlarmProximityNone


def alarm_from_eventkit(alarm: EKAlarm) -> ReminderAlarm:
    """Read an EKAlarm. A location alarm has neither a trigger date nor an offset."""
    if alarm.absoluteDate():
        return ReminderAlarm(trigger_date=normalize_date(alarm.absoluteDate()))
    if is_location_alarm(alarm):
        return ReminderAlarm()
    # An offset of 0 is an alarm at the due time, not a missing offset
    return ReminderAlarm(relative_offset=int(alarm.relativeOffset()))


def alarm_to_eventkit(alarm_data: ReminderAlarm) -> EKAlarm:
    """Create the EKAlarm for a time-based alarm."""
    alarm = EKAlarm.alloc().init()
    if alarm_data.trigger_date is not None:
        alarm.setAbsoluteDate_(alarm_data.trigger_date)
    else:
        alarm.setRelativeOffset_(alarm_data.relative_offset or 0)
    return alarm


# NSDateComponentUndefined is a large value indicating component not set
# On 64-bit systems it's typically Int.max (9223372036854775807)
# On 32-bit systems it's 2147483647
# We use a threshold to detect undefined values safely
NS_DATE_COMPONENT_UNDEFINED_THRESHOLD = 2147483640


def due_date_from_components(dc: NSDateComponents) -> tuple[datetime | None, bool]:
    """
    Read a reminder's due date components as (due date in UTC, whether it is all-day).

    An all-day date is stored as midnight UTC on that date. A time is read in its own
    time zone, at that zone's offset on the due date rather than today's. A time with
    no time zone (floating) is taken as the Mac's local time.
    """
    try:
        year = dc.year() if dc.year() else 1
        # Clamp year to valid range to avoid overflow
        if year < 1 or year > 9999:
            logger.warning(f"Invalid year in due date: {year}")
            return None, False
        month = dc.month() if dc.month() else 1
        day = dc.day() if dc.day() else 1

        # Check if time components are set (not NSDateComponentUndefined)
        # When undefined, hour()/minute()/second() return very large values
        raw_hour = dc.hour()
        raw_minute = dc.minute()
        raw_second = dc.second()
        hour_undefined = raw_hour is None or raw_hour >= NS_DATE_COMPONENT_UNDEFINED_THRESHOLD
        minute_undefined = raw_minute is None or raw_minute >= NS_DATE_COMPONENT_UNDEFINED_THRESHOLD
        second_undefined = raw_second is None or raw_second >= NS_DATE_COMPONENT_UNDEFINED_THRESHOLD

        # Per Apple docs: "Setting a date component without hour, minute and second
        # component will set the reminder to be an all-day reminder"
        if hour_undefined and minute_undefined and second_undefined:
            due_date = datetime(year, month, day, tzinfo=timezone.utc)
            logger.debug(f"Detected all-day reminder with due date: {due_date.date()}")
            return due_date, True

        hour = raw_hour if raw_hour and not hour_undefined else 0
        minute = raw_minute if raw_minute and not minute_undefined else 0
        second = raw_second if raw_second and not second_undefined else 0

        tz_info = local_timezone()
        dc_timezone = dc.timeZone()
        if dc_timezone:
            try:
                tz_info = ZoneInfo(dc_timezone.name())
            except (ZoneInfoNotFoundError, ValueError):
                # Not an IANA name, e.g. "GMT+0200", so a fixed offset
                tz_info = timezone(timedelta(seconds=dc_timezone.secondsFromGMT()))

        due_date = datetime(year, month, day, hour, minute, second, tzinfo=tz_info)
        # Convert to UTC for consistent storage
        return due_date.astimezone(timezone.utc), False

    except (ValueError, AttributeError, OverflowError) as e:
        logger.warning(f"Could not parse due date: {e}")
        return None, False


def due_date_components(due_date: datetime, is_all_day: bool) -> NSDateComponents:
    """
    Build a reminder's due date components.

    An all-day reminder gets its calendar date and nothing else. A time is set in the
    Mac's time zone: due dates from CalDAV are usually in UTC, so their hour can't be
    reused as a local one. A time with no time zone is taken as local already.
    """
    components = NSDateComponents.alloc().init()
    # Per Apple docs: dueDateComponents must use Gregorian calendar
    # "If this property is set, the calendar must be set to NSGregorianCalendar"
    gregorian = NSCalendar.alloc().initWithCalendarIdentifier_("gregorian")
    components.setCalendar_(gregorian or NSCalendar.currentCalendar())

    if is_all_day:
        # Per Apple docs: "Setting a date component without an hour, minute and second
        # component will set the reminder to be an all-day reminder", and "A nil time
        # zone represents a floating date"
        components.setYear_(due_date.year)
        components.setMonth_(due_date.month)
        components.setDay_(due_date.day)
        return components

    zone = local_timezone()
    local = due_date.astimezone(zone) if due_date.tzinfo else due_date
    components.setYear_(local.year)
    components.setMonth_(local.month)
    components.setDay_(local.day)
    components.setHour_(local.hour)
    components.setMinute_(local.minute)
    components.setSecond_(local.second)
    zone_name = getattr(zone, "key", None)
    ns_zone = NSTimeZone.timeZoneWithName_(zone_name) if zone_name else None
    components.setTimeZone_(ns_zone or NSTimeZone.localTimeZone())
    return components


@dataclass
class EventKitReminder:
    """Represents a reminder from Apple Reminders.app via EventKit."""

    uuid: str
    title: str
    notes: str | None
    completed: bool
    priority: int  # 0=none, 1-4=high, 5-9=medium/low
    due_date: datetime | None
    creation_date: datetime
    modification_date: datetime
    completion_date: datetime | None
    calendar_id: str  # Calendar/List UUID
    calendar_name: str
    alarms: list[ReminderAlarm] = field(default_factory=list)
    recurrence_rules: list[ReminderRecurrence] = field(default_factory=list)
    url: str | None = None
    is_all_day: bool = False  # True if due date has no time component (floating date)


@dataclass
class ReminderCalendar:
    """Represents a calendar/list in Apple Reminders.app."""

    uuid: str
    title: str
    reminder_count: int = 0
    source_id: str = ""  # The account the list belongs to


class RemindersAdapter:
    """Adapter for interfacing with Apple Reminders via EventKit."""

    # Class-level shared EventKit store to avoid hitting Apple's instance limit
    _shared_store: EKEventStore | None = None
    _access_granted: bool = False
    _store_lock = asyncio.Lock()

    def __init__(self):
        """Initialize the EventKit store (reuses shared instance)."""
        # Use the shared store instance to avoid creating too many EKEventStore instances
        # Apple limits the number of EKEventStore instances per process
        if RemindersAdapter._shared_store is None:
            RemindersAdapter._shared_store = EKEventStore.alloc().init()
            logger.debug("Created shared EKEventStore instance")

    @property
    def store(self) -> EKEventStore:
        """
        The shared EventKit store.

        Read from the class on every access rather than cached per-instance, so
        that a store rebuilt by _refresh_store() is picked up by adapters that
        were constructed before the rebuild.
        """
        if RemindersAdapter._shared_store is None:
            RemindersAdapter._shared_store = EKEventStore.alloc().init()
            logger.debug("Created shared EKEventStore instance")
        return RemindersAdapter._shared_store

    @classmethod
    def reset_shared_store(cls) -> None:
        """Reset the shared EventKit store. Useful for cleanup or testing."""
        cls._shared_store = None
        cls._access_granted = False
        logger.debug("Reset shared EKEventStore instance")

    async def _refresh_store(self) -> None:
        """
        Rebuild the shared EventKit store and re-request access.

        A long-lived EKEventStore can stop returning data without raising:
        macOS drops TCC privileges for a running process whose executable has
        been replaced underneath it (a Homebrew Python upgrade will do this),
        and the store then reports an empty database rather than an error.
        Rebuilding is the only way to find out whether access is really gone.
        """
        async with RemindersAdapter._store_lock:
            store = RemindersAdapter._shared_store
            if store is not None:
                try:
                    store.reset()
                except Exception as e:  # pragma: no cover - defensive
                    logger.debug(f"EKEventStore.reset() failed: {e}")

            RemindersAdapter._shared_store = EKEventStore.alloc().init()
            RemindersAdapter._access_granted = False
            logger.info("Rebuilt shared EKEventStore instance")

        await self.request_access()

    async def request_access(self) -> bool:
        """Request access to Reminders. Returns True if granted."""
        if RemindersAdapter._access_granted:
            return True

        # Create a future to wait for the callback
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        def callback(granted: bool, error: Any) -> None:
            if not future.done():
                # Call from ObjC thread - must use call_soon_threadsafe
                def set_result():
                    if granted:
                        logger.info("EventKit access to Reminders granted")
                        future.set_result(True)
                    else:
                        logger.error(f"EventKit access denied: {error}")
                        future.set_result(False)

                loop.call_soon_threadsafe(set_result)

        self.store.requestFullAccessToRemindersWithCompletion_(callback)

        # Wait for callback to complete
        RemindersAdapter._access_granted = await future
        return RemindersAdapter._access_granted

    def _read_calendars(self) -> list[ReminderCalendar]:
        """Read reminder calendars straight from the store, without recovery."""
        calendars = self.store.calendarsForEntityType_(EKEntityTypeReminder) or []
        return [
            ReminderCalendar(
                uuid=cal.calendarIdentifier(),
                title=cal.title(),
                source_id=cal.source().sourceIdentifier() if cal.source() else "",
            )
            for cal in calendars
        ]

    async def list_source_ids(self) -> set[str]:
        """IDs of the accounts (iCloud, On My Mac, ...) Reminders can see.

        When an account is signed out or turned off, all its lists vanish at
        once. Checking the account tells that apart from a deleted list.
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()
        return {source.sourceIdentifier() for source in (self.store.sources() or [])}

    async def list_calendars(self) -> list[ReminderCalendar]:
        """
        List all reminder calendars/lists.

        An empty result is treated as a fault rather than a valid answer: macOS
        always keeps at least one Reminders list, so zero lists means the store
        is dead or access has been revoked. We rebuild the store and retry once
        before giving up.
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        result = self._read_calendars()

        if not result:
            logger.warning(
                "EventKit returned no reminder lists - rebuilding the store and retrying"
            )
            await self._refresh_store()
            result = self._read_calendars()

            if not result:
                # Rebuilding did not help, so the problem is the process rather
                # than the store. Record why, since this is otherwise invisible.
                log_interpreter_status("Reminders unreadable after store rebuild")

        logger.info(f"Found {len(result)} reminder calendars")
        return result

    async def create_calendar(self, calendar_name: str) -> ReminderCalendar | None:
        """
        Create a new reminder calendar/list.

        Args:
            calendar_name: Name of the calendar to create

        Returns:
            ReminderCalendar object if created successfully, None otherwise
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        try:
            logger.info(f"Creating Apple Reminders calendar: {calendar_name}")

            # Get the default source for reminders (usually iCloud)
            sources = self.store.sources() or []

            # No sources at all means the store is dead rather than empty - the
            # same failure that makes list_calendars() come back empty. Rebuild
            # and retry before concluding anything.
            if not sources:
                logger.warning("EventKit reported no sources - rebuilding the store and retrying")
                await self._refresh_store()
                sources = self.store.sources() or []

            default_source = None
            for source in sources:
                if source.sourceType() == 1:  # EKSourceTypeCalDAV (iCloud)
                    default_source = source
                    break

            # Fallback to local source if no CalDAV source found
            if not default_source and sources:
                default_source = sources[0]

            if not default_source:
                raise SourceUnavailableError(
                    "Apple Reminders reported no accounts, so no list can be created. "
                    "The backend has most likely lost Reminders access. "
                    "Restart iCloudBridge and re-grant access if prompted."
                )

            # Create new calendar
            new_calendar = EventKit.EKCalendar.calendarForEntityType_eventStore_(
                EKEntityTypeReminder, self.store
            )
            new_calendar.setTitle_(calendar_name)
            new_calendar.setSource_(default_source)

            # Save to store
            error = None
            success = self.store.saveCalendar_commit_error_(new_calendar, True, None)

            if success:
                logger.info(f"Successfully created calendar: {calendar_name}")
                return ReminderCalendar(
                    uuid=new_calendar.calendarIdentifier(),
                    title=new_calendar.title(),
                    source_id=default_source.sourceIdentifier(),
                )
            else:
                logger.error(f"Failed to create calendar: {calendar_name}")
                return None

        except SourceUnavailableError:
            # Never downgrade "source is unreachable" to "creation failed" - the
            # caller has to be able to tell those apart.
            raise

        except Exception as e:
            logger.error(f"Failed to create calendar '{calendar_name}': {e}", exc_info=True)
            return None

    async def delete_calendar(self, calendar_id: str) -> bool:
        """
        Delete a reminder list, and every reminder in it.

        Args:
            calendar_id: Identifier of the list to delete

        Returns:
            True if deleted, False if the list was not found or could not be deleted
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        calendar = self.store.calendarWithIdentifier_(calendar_id)
        if calendar is None:
            logger.warning(f"Reminder list not found for deletion: {calendar_id}")
            return False

        title = calendar.title()
        ok, error = self.store.removeCalendar_commit_error_(calendar, True, None)
        if not ok:
            logger.error(f"Failed to delete reminder list '{title}': {error}")
            return False

        logger.info(f"Deleted reminder list: {title}")
        return True

    async def get_reminders(
        self, calendar_id: str | None = None, calendar_name: str | None = None
    ) -> list[EventKitReminder]:
        """
        Get all reminders from a specific calendar.

        Args:
            calendar_id: Calendar UUID to fetch from
            calendar_name: Calendar name to fetch from (alternative to calendar_id)

        Returns:
            List of EventKitReminder objects
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        # Find the calendar
        calendars = self.store.calendarsForEntityType_(EKEntityTypeReminder)

        target_calendar = None
        if calendar_id:
            for cal in calendars:
                if cal.calendarIdentifier() == calendar_id:
                    target_calendar = cal
                    break
        elif calendar_name:
            for cal in calendars:
                if cal.title() == calendar_name:
                    target_calendar = cal
                    break

        if not target_calendar:
            logger.warning(f"Calendar not found: {calendar_id or calendar_name}")
            return []

        ek_reminders = await self._fetch_reminders(
            self.store.predicateForRemindersInCalendars_([target_calendar])
        )

        # Convert to our dataclass format
        result = []
        for r in ek_reminders:
            result.append(self._convert_from_eventkit(r))

        logger.info(
            f"Fetched {len(result)} reminders from calendar '{target_calendar.title()}'"
        )
        return result

    async def count_open_reminders(self, calendar_id: str) -> int:
        """
        Count the reminders in a list that are not completed.

        This is the number Reminders.app shows beside a list. Completed
        reminders are hidden there, and a list can hold hundreds of them.
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        calendar = self.store.calendarWithIdentifier_(calendar_id)
        if calendar is None:
            return 0

        reminders = await self._fetch_reminders(
            self.store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
                None, None, [calendar]
            )
        )
        return len(reminders)

    async def _fetch_reminders(self, predicate: Any) -> list:
        """Run an EventKit reminder query and wait for its result."""
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        def fetch_callback(reminders: list) -> None:
            if not future.done():
                # Call from ObjC thread - must use call_soon_threadsafe
                loop.call_soon_threadsafe(future.set_result, reminders or [])

        self.store.fetchRemindersMatchingPredicate_completion_(predicate, fetch_callback)
        return await future

    def _convert_from_eventkit(self, ek_reminder: EKReminder) -> EventKitReminder:
        """Convert an EKReminder to our EventKitReminder dataclass."""
        # Extract due date from NSDateComponents
        due_date = None
        is_all_day = False
        if ek_reminder.dueDateComponents():
            due_date, is_all_day = due_date_from_components(ek_reminder.dueDateComponents())

        # Extract alarms
        alarms = []
        if ek_reminder.hasAlarms():
            alarms = [alarm_from_eventkit(alarm) for alarm in ek_reminder.alarms() or []]

        # Extract recurrence rules
        recurrence_rules = []
        if ek_reminder.hasRecurrenceRules():
            for rule in ek_reminder.recurrenceRules() or []:
                freq_map = {
                    EKRecurrenceFrequencyDaily: "DAILY",
                    EKRecurrenceFrequencyWeekly: "WEEKLY",
                    EKRecurrenceFrequencyMonthly: "MONTHLY",
                    EKRecurrenceFrequencyYearly: "YEARLY",
                }
                frequency = freq_map.get(rule.frequency(), "DAILY")

                rec_obj = ReminderRecurrence(
                    frequency=frequency,
                    interval=rule.interval(),
                )

                # Extract end date or occurrence count
                if rule.recurrenceEnd():
                    end = rule.recurrenceEnd()
                    if end.endDate():
                        rec_obj.end_date = normalize_date(end.endDate())
                    elif end.occurrenceCount():
                        rec_obj.occurrence_count = end.occurrenceCount()

                # Extract days of week
                if rule.daysOfTheWeek():
                    rec_obj.days_of_week = [day.dayOfTheWeek() for day in rule.daysOfTheWeek()]

                recurrence_rules.append(rec_obj)

        return EventKitReminder(
            uuid=ek_reminder.calendarItemIdentifier(),
            title=ek_reminder.title() or "",
            notes=ek_reminder.notes(),
            completed=ek_reminder.isCompleted(),
            priority=ek_reminder.priority(),
            due_date=due_date,
            creation_date=normalize_date(ek_reminder.creationDate()),
            modification_date=normalize_date(ek_reminder.lastModifiedDate()),
            completion_date=normalize_date(ek_reminder.completionDate()),
            calendar_id=ek_reminder.calendar().calendarIdentifier(),
            calendar_name=ek_reminder.calendar().title(),
            alarms=alarms,
            recurrence_rules=recurrence_rules,
            url=str(ek_reminder.URL()) if ek_reminder.URL() else None,
            is_all_day=is_all_day,
        )

    async def create_reminder(
        self,
        calendar_id: str,
        title: str,
        notes: str | None = None,
        completed: bool = False,
        priority: int = 0,
        due_date: datetime | None = None,
        is_all_day: bool = False,
        alarms: list[ReminderAlarm] | None = None,
        recurrence_rules: list[ReminderRecurrence] | None = None,
        url: str | None = None,
    ) -> EventKitReminder:
        """
        Create a new reminder in the specified calendar.

        Returns:
            The created EventKitReminder object
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        # Find the calendar
        calendars = self.store.calendarsForEntityType_(EKEntityTypeReminder)
        target_calendar = None
        for cal in calendars:
            if cal.calendarIdentifier() == calendar_id:
                target_calendar = cal
                break

        if not target_calendar:
            raise ValueError(f"Calendar not found: {calendar_id}")

        # Create the reminder
        reminder = EKReminder.reminderWithEventStore_(self.store)
        reminder.setTitle_(title)
        reminder.setCalendar_(target_calendar)

        if notes:
            reminder.setNotes_(notes)

        reminder.setCompleted_(completed)
        reminder.setPriority_(priority)

        # Set due date
        if due_date:
            reminder.setDueDateComponents_(due_date_components(due_date, is_all_day))

        # Add alarms
        if alarms:
            for alarm_data in alarms:
                reminder.addAlarm_(alarm_to_eventkit(alarm_data))

        # Add recurrence rules
        if recurrence_rules:
            for rec_data in recurrence_rules:
                frequency = RECURRENCE_FREQUENCIES.get(
                    rec_data.frequency, EKRecurrenceFrequencyDaily
                )

                # Create recurrence end
                rec_end = None
                if rec_data.end_date:
                    rec_end = EKRecurrenceEnd.recurrenceEndWithEndDate_(rec_data.end_date)
                elif rec_data.occurrence_count:
                    rec_end = EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(
                        rec_data.occurrence_count
                    )

                # Create days of week
                days_of_week = None
                if rec_data.days_of_week:
                    days_of_week = [
                        EKRecurrenceDayOfWeek.dayOfWeek_(day) for day in rec_data.days_of_week
                    ]

                rule = EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_(
                    frequency,
                    rec_data.interval,
                    days_of_week,
                    None,  # daysOfTheMonth
                    None,  # monthsOfTheYear
                    None,  # weeksOfTheYear
                    None,  # daysOfTheYear
                    None,  # setPositions
                    rec_end,
                )
                reminder.addRecurrenceRule_(rule)

        # Set URL
        if url:
            from Foundation import NSURL

            reminder.setURL_(NSURL.URLWithString_(url))

        # Save to store
        error = self.store.saveReminder_commit_error_(reminder, True, None)
        if error[0] is False:
            raise RuntimeError(f"Failed to create reminder: {error[2]}")

        logger.info(f"Created reminder: {title}")
        return self._convert_from_eventkit(reminder)

    async def update_reminder(
        self,
        uuid: str,
        title: str | None = None,
        notes: str | None = None,
        completed: bool | None = None,
        priority: int | None = None,
        due_date: datetime | None = None,
        is_all_day: bool | None = None,
        alarms: list[ReminderAlarm] | None = None,
        recurrence_rules: list[ReminderRecurrence] | None = None,
        url: str | None = None,
    ) -> EventKitReminder:
        """
        Update an existing reminder by UUID.

        Fields left as None are not changed. alarms, when given, are the time-based
        alarms the reminder should have; its location alarms are always kept.

        Returns:
            The updated EventKitReminder object
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        # Fetch the reminder by UUID
        reminder = self.store.calendarItemWithIdentifier_(uuid)
        if not reminder:
            raise ValueError(f"Reminder not found: {uuid}")

        # Update fields
        if title is not None:
            reminder.setTitle_(title)
        if notes is not None:
            reminder.setNotes_(notes)
        if completed is not None:
            reminder.setCompleted_(completed)
        if priority is not None:
            reminder.setPriority_(priority)

        # Update due date
        if due_date is not None:
            # Determine if all-day: use provided value, or default to False if not specified
            use_all_day = is_all_day if is_all_day is not None else False
            reminder.setDueDateComponents_(due_date_components(due_date, use_all_day))

        # Update alarms: keep the ones that match, remove the rest and add what's missing.
        # Location alarms aren't synced, so they are never in the list and never removed.
        if alarms is not None:
            missing = list(alarms)
            # alarms() can return None
            for alarm in reminder.alarms() or []:
                if is_location_alarm(alarm):
                    continue
                existing = alarm_from_eventkit(alarm)
                if existing in missing:
                    missing.remove(existing)
                else:
                    reminder.removeAlarm_(alarm)
            for alarm_data in missing:
                reminder.addAlarm_(alarm_to_eventkit(alarm_data))

        # Update recurrence rules (replace all)
        if recurrence_rules is not None:
            # Remove existing rules (recurrenceRules() can return None)
            for rule in reminder.recurrenceRules() or []:
                reminder.removeRecurrenceRule_(rule)
            # Add new rules
            for rec_data in recurrence_rules:
                frequency = RECURRENCE_FREQUENCIES.get(
                    rec_data.frequency, EKRecurrenceFrequencyDaily
                )

                rec_end = None
                if rec_data.end_date:
                    rec_end = EKRecurrenceEnd.recurrenceEndWithEndDate_(rec_data.end_date)
                elif rec_data.occurrence_count:
                    rec_end = EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(
                        rec_data.occurrence_count
                    )

                days_of_week = None
                if rec_data.days_of_week:
                    days_of_week = [
                        EKRecurrenceDayOfWeek.dayOfWeek_(day) for day in rec_data.days_of_week
                    ]

                rule = EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_(
                    frequency,
                    rec_data.interval,
                    days_of_week,
                    None,
                    None,
                    None,
                    None,
                    None,
                    rec_end,
                )
                reminder.addRecurrenceRule_(rule)

        # Update URL
        if url is not None:
            from Foundation import NSURL

            reminder.setURL_(NSURL.URLWithString_(url))

        # Save changes
        error = self.store.saveReminder_commit_error_(reminder, True, None)
        if error[0] is False:
            raise RuntimeError(f"Failed to update reminder: {error[2]}")

        logger.info(f"Updated reminder: {uuid}")
        return self._convert_from_eventkit(reminder)

    async def delete_reminder(self, uuid: str) -> bool:
        """
        Delete a reminder by UUID.

        Returns:
            True if deleted successfully, False otherwise
        """
        if not RemindersAdapter._access_granted:
            await self.request_access()

        # Fetch the reminder by UUID
        reminder = self.store.calendarItemWithIdentifier_(uuid)
        if not reminder:
            logger.warning(f"Reminder not found for deletion: {uuid}")
            return False

        # Delete the reminder
        error = self.store.removeReminder_commit_error_(reminder, True, None)
        if error[0] is False:
            logger.error(f"Failed to delete reminder: {error[2]}")
            return False

        logger.info(f"Deleted reminder: {uuid}")
        return True
