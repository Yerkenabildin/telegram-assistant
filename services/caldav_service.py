"""
CalDAV calendar integration service.

Checks for active calendar events and manages meeting status accordingly.
Settings are stored in database and configured via bot interface.
Supports multiple calendars with event type classification (meeting/absence).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from config import config
from logging_config import logger

# CalDAV import with graceful fallback
try:
    import caldav
    CALDAV_AVAILABLE = True
except ImportError:
    CALDAV_AVAILABLE = False
    caldav = None


class CalendarEventType(Enum):
    """Type of calendar event based on calendar configuration."""
    MEETING = "meeting"
    ABSENCE = "absence"


@dataclass
class CalendarInfo:
    """Information about a calendar."""
    name: str
    url: str
    event_type: Optional[str] = None  # 'meeting', 'absence', or None


@dataclass
class CalendarEvent:
    """Represents an active calendar event."""
    uid: str
    summary: str
    start: datetime
    end: datetime
    calendar_name: str
    event_type: CalendarEventType = CalendarEventType.MEETING
    description: Optional[str] = None


class CalDAVService:
    """Service for interacting with CalDAV calendars.

    Configuration is stored in Settings database and can be
    updated at runtime via bot interface.
    Supports multiple calendars.
    """

    def __init__(self):
        self._client: Optional[caldav.DAVClient] = None
        self._all_calendars: list[caldav.Calendar] = []
        self._last_event_uid: Optional[str] = None
        self._tz = ZoneInfo(config.timezone)
        # Cache connection params to detect changes
        self._connected_url: Optional[str] = None
        self._connected_user: Optional[str] = None

    def is_configured(self) -> bool:
        """Check if CalDAV is properly configured (in Settings)."""
        if not CALDAV_AVAILABLE:
            return False
        from models import Settings
        return Settings.is_caldav_configured()

    def _needs_reconnect(self) -> bool:
        """Check if connection params changed and we need to reconnect."""
        from models import Settings
        current_url = Settings.get_caldav_url()
        current_user = Settings.get_caldav_username()
        return (
            current_url != self._connected_url or
            current_user != self._connected_user
        )

    async def connect(self) -> bool:
        """Connect to CalDAV server and fetch all calendars.

        Returns True if connection successful.
        """
        if not self.is_configured():
            return False

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._connect_sync)
        except Exception as e:
            logger.error(f"Failed to connect to CalDAV server: {e}")
            return False

    def _connect_sync(self) -> bool:
        """Synchronous connection to CalDAV server."""
        from models import Settings

        url = Settings.get_caldav_url()
        username = Settings.get_caldav_username()
        password = Settings.get_caldav_password()

        if not url or not username or not password:
            return False

        try:
            self._client = caldav.DAVClient(
                url=url,
                username=username,
                password=password
            )

            principal = self._client.principal()
            self._all_calendars = principal.calendars()

            if not self._all_calendars:
                logger.error("No calendars found on CalDAV server")
                return False

            # Cache connection params
            self._connected_url = url
            self._connected_user = username

            cal_names = [c.name for c in self._all_calendars]
            logger.info(f"Connected to CalDAV. Available calendars: {cal_names}")
            return True

        except Exception as e:
            logger.error(f"CalDAV connection error: {e}")
            self._client = None
            self._all_calendars = []
            self._connected_url = None
            self._connected_user = None
            return False

    def disconnect(self):
        """Disconnect from CalDAV server."""
        self._client = None
        self._all_calendars = []
        self._connected_url = None
        self._connected_user = None
        self._last_event_uid = None

    async def get_available_calendars(self) -> list[CalendarInfo]:
        """Get list of all available calendars on the server with their configured types."""
        from models import Settings

        if self._needs_reconnect():
            self.disconnect()

        if not self._all_calendars:
            if not await self.connect():
                return []

        return [
            CalendarInfo(
                name=cal.name,
                url=str(cal.url),
                event_type=Settings.get_calendar_type(cal.name)
            )
            for cal in self._all_calendars
        ]

    def _get_active_calendars(self) -> list[caldav.Calendar]:
        """Get calendars to check based on Settings (all configured calendars)."""
        from models import Settings

        meeting_cals = Settings.get_caldav_meeting_calendars()
        absence_cals = Settings.get_caldav_absence_calendars()
        selected = set(meeting_cals + absence_cals)

        if not selected:
            # No selection = use all calendars (legacy behavior)
            return self._all_calendars

        # Filter by selected names (strip whitespace for consistent matching)
        return [c for c in self._all_calendars if c.name.strip() in selected]

    def _get_calendars_by_type(self, event_type: CalendarEventType) -> list[caldav.Calendar]:
        """Get calendars configured for a specific event type.

        Args:
            event_type: MEETING or ABSENCE

        Returns:
            List of caldav.Calendar objects matching the type
        """
        from models import Settings

        if event_type == CalendarEventType.MEETING:
            selected = Settings.get_caldav_meeting_calendars()
        else:
            selected = Settings.get_caldav_absence_calendars()

        if not selected:
            return []

        return [c for c in self._all_calendars if c.name.strip() in selected]

    async def get_current_event(self) -> Optional[CalendarEvent]:
        """Get currently active calendar event from any active calendar.

        Returns the first active event found, or None.
        """
        if self._needs_reconnect():
            logger.info("CalDAV settings changed, reconnecting...")
            self.disconnect()

        if not self._all_calendars:
            if not await self.connect():
                return None

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._get_current_event_sync)
        except Exception as e:
            logger.error(f"Error fetching calendar events: {e}")
            self._all_calendars = []
            return None

    def _get_current_event_sync(self) -> Optional[CalendarEvent]:
        """Synchronously get current calendar event from active calendars."""
        now = datetime.now(self._tz)
        # Widen search window to catch events that might have started
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        active_calendars = self._get_active_calendars()
        logger.debug(f"Checking {len(active_calendars)} calendars for active events at {now}")

        for calendar in active_calendars:
            try:
                events = calendar.search(
                    start=start,
                    end=end,
                    event=True,
                    expand=True
                )

                for event in events:
                    try:
                        cal_event = self._parse_event(event, calendar.name)
                        if cal_event:
                            is_active = self._is_event_active(cal_event, now)
                            logger.debug(
                                f"Event '{cal_event.summary}' ({cal_event.start} - {cal_event.end}): "
                                f"active={is_active}, type={cal_event.event_type.value}"
                            )
                            if is_active:
                                return cal_event
                    except Exception as e:
                        logger.warning(f"Error parsing event: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Error searching calendar {calendar.name}: {e}")
                continue

        return None

    def _get_current_event_by_type_sync(self, event_type: CalendarEventType) -> Optional[CalendarEvent]:
        """Synchronously get current calendar event of a specific type."""
        now = datetime.now(self._tz)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        calendars = self._get_calendars_by_type(event_type)
        logger.debug(f"Checking {len(calendars)} {event_type.value} calendars for active events")

        for calendar in calendars:
            try:
                events = calendar.search(
                    start=start,
                    end=end,
                    event=True,
                    expand=True
                )

                for event in events:
                    try:
                        cal_event = self._parse_event(event, calendar.name, event_type)
                        if cal_event and self._is_event_active(cal_event, now):
                            return cal_event
                    except Exception as e:
                        logger.warning(f"Error parsing event: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Error searching calendar {calendar.name}: {e}")
                continue

        return None

    async def get_current_event_by_type(self, event_type: CalendarEventType) -> Optional[CalendarEvent]:
        """Get currently active calendar event of a specific type.

        Args:
            event_type: MEETING or ABSENCE

        Returns:
            Active CalendarEvent or None
        """
        if self._needs_reconnect():
            logger.info("CalDAV settings changed, reconnecting...")
            self.disconnect()

        if not self._all_calendars:
            if not await self.connect():
                return None

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self._get_current_event_by_type_sync(event_type)
            )
        except Exception as e:
            logger.error(f"Error fetching {event_type.value} events: {e}")
            return None

    def _get_upcoming_events_sync(self, hours: int = 24) -> list[CalendarEvent]:
        """Synchronously get upcoming calendar events from active calendars."""
        now = datetime.now(self._tz)
        end = now + timedelta(hours=hours)

        active_calendars = self._get_active_calendars()
        all_events = []

        for calendar in active_calendars:
            try:
                events = calendar.search(
                    start=now,
                    end=end,
                    event=True,
                    expand=True
                )

                for event in events:
                    try:
                        cal_event = self._parse_event(event, calendar.name)
                        if cal_event:
                            all_events.append(cal_event)
                    except Exception as e:
                        logger.warning(f"Error parsing event: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Error searching calendar {calendar.name}: {e}")
                continue

        # Sort by start time
        all_events.sort(key=lambda e: e.start)
        return all_events

    async def get_upcoming_events(self, hours: int = 24) -> list[CalendarEvent]:
        """Get upcoming calendar events from active calendars.

        Args:
            hours: Number of hours ahead to look for events

        Returns:
            List of upcoming events sorted by start time
        """
        if self._needs_reconnect():
            logger.info("CalDAV settings changed, reconnecting...")
            self.disconnect()

        if not self._all_calendars:
            if not await self.connect():
                return []

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._get_upcoming_events_sync(hours))
        except Exception as e:
            logger.error(f"Error fetching upcoming events: {e}")
            return []

    async def get_calendar_status(self) -> dict:
        """Get calendar status info for display in bot menu.

        Returns:
            Dict with status info: connected, calendar_count, current_event, upcoming_events
        """
        result = {
            'connected': False,
            'calendar_count': 0,
            'active_calendar_count': 0,
            'current_event': None,
            'upcoming_events': [],
            'error': None
        }

        if not self.is_configured():
            result['error'] = "CalDAV не настроен"
            return result

        try:
            if not self._all_calendars:
                if not await self.connect():
                    result['error'] = "Не удалось подключиться"
                    return result

            result['connected'] = True
            result['calendar_count'] = len(self._all_calendars)
            result['active_calendar_count'] = len(self._get_active_calendars())

            # Get current event
            current = await self.get_current_event()
            if current:
                result['current_event'] = current

            # Get upcoming events (next 8 hours, max 5)
            upcoming = await self.get_upcoming_events(hours=8)
            # Filter out current event if it's in the list
            if current:
                upcoming = [e for e in upcoming if e.uid != current.uid]
            result['upcoming_events'] = upcoming[:5]

        except Exception as e:
            result['error'] = str(e)

        return result

    def _parse_event(
        self,
        event,
        calendar_name: str,
        event_type: Optional[CalendarEventType] = None
    ) -> Optional[CalendarEvent]:
        """Parse caldav event into CalendarEvent dataclass.

        Args:
            event: caldav event object
            calendar_name: Name of the source calendar
            event_type: Explicit event type, or None to determine from calendar settings
        """
        try:
            vevent = event.vobject_instance.vevent

            dtstart = vevent.dtstart.value
            dtend = vevent.dtend.value if hasattr(vevent, 'dtend') else None

            # Handle all-day events
            if not isinstance(dtstart, datetime):
                dtstart = datetime.combine(dtstart, datetime.min.time())
                dtstart = dtstart.replace(tzinfo=self._tz)
            elif dtstart.tzinfo is None:
                dtstart = dtstart.replace(tzinfo=self._tz)

            if dtend:
                if not isinstance(dtend, datetime):
                    dtend = datetime.combine(dtend, datetime.max.time())
                    dtend = dtend.replace(tzinfo=self._tz)
                elif dtend.tzinfo is None:
                    dtend = dtend.replace(tzinfo=self._tz)
            else:
                dtend = dtstart + timedelta(hours=1)

            summary = str(vevent.summary.value) if hasattr(vevent, 'summary') else "Untitled"
            description = str(vevent.description.value) if hasattr(vevent, 'description') else None
            uid = str(vevent.uid.value) if hasattr(vevent, 'uid') else str(id(event))

            # Determine event type from calendar settings if not provided
            if event_type is None:
                from models import Settings
                cal_type = Settings.get_calendar_type(calendar_name)
                if cal_type == 'absence':
                    event_type = CalendarEventType.ABSENCE
                else:
                    event_type = CalendarEventType.MEETING

            return CalendarEvent(
                uid=uid,
                summary=summary,
                start=dtstart,
                end=dtend,
                calendar_name=calendar_name,
                event_type=event_type,
                description=description
            )
        except Exception as e:
            logger.warning(f"Failed to parse event: {e}")
            return None

    def _is_event_active(self, event: CalendarEvent, now: datetime) -> bool:
        """Check if event is currently active."""
        # Ensure consistent timezone comparison
        event_start = event.start
        event_end = event.end

        # Convert to same timezone if needed
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=self._tz)
        if event_end.tzinfo is None:
            event_end = event_end.replace(tzinfo=self._tz)

        return event_start <= now <= event_end

    async def check_meeting_status(self) -> tuple[bool, Optional[CalendarEvent]]:
        """Check if there's an active meeting in any active calendar."""
        event = await self.get_current_event()

        if event:
            if event.uid != self._last_event_uid:
                logger.info(f"Calendar meeting started: {event.summary} ({event.calendar_name})")
                self._last_event_uid = event.uid
            return True, event
        else:
            if self._last_event_uid:
                logger.info("Calendar meeting ended")
                self._last_event_uid = None
            return False, None

    async def check_calendar_status_with_priority(
        self
    ) -> Tuple[Optional[CalendarEventType], Optional[CalendarEvent]]:
        """Check calendar status with priority: absence > meeting.

        Returns:
            Tuple of (event_type, event) where:
            - event_type is ABSENCE if there's an active absence event
            - event_type is MEETING if there's an active meeting event (no absence)
            - (None, None) if no active events

        Absence events have higher priority than meeting events.
        """
        if self._needs_reconnect():
            logger.info("CalDAV settings changed, reconnecting...")
            self.disconnect()

        if not self._all_calendars:
            if not await self.connect():
                return None, None

        # Check absence first (higher priority)
        absence_event = await self.get_current_event_by_type(CalendarEventType.ABSENCE)
        if absence_event:
            if absence_event.uid != self._last_event_uid:
                logger.info(
                    f"Calendar absence started: {absence_event.summary} ({absence_event.calendar_name})"
                )
                self._last_event_uid = absence_event.uid
            return CalendarEventType.ABSENCE, absence_event

        # Check meeting if no absence
        meeting_event = await self.get_current_event_by_type(CalendarEventType.MEETING)
        if meeting_event:
            if meeting_event.uid != self._last_event_uid:
                logger.info(
                    f"Calendar meeting started: {meeting_event.summary} ({meeting_event.calendar_name})"
                )
                self._last_event_uid = meeting_event.uid
            return CalendarEventType.MEETING, meeting_event

        # No active events
        if self._last_event_uid:
            logger.info("Calendar event ended")
            self._last_event_uid = None

        return None, None

    def get_last_event_uid(self) -> Optional[str]:
        """Get UID of the last tracked event."""
        return self._last_event_uid

    def clear_state(self):
        """Clear internal state."""
        self._last_event_uid = None

    async def test_connection(self) -> tuple[bool, str]:
        """Test CalDAV connection."""
        if not CALDAV_AVAILABLE:
            return False, "Библиотека caldav не установлена"

        if not self.is_configured():
            return False, "CalDAV не настроен"

        self.disconnect()

        try:
            if await self.connect():
                count = len(self._all_calendars)
                return True, f"Подключено. Найдено календарей: {count}"
            else:
                return False, "Не удалось подключиться"
        except Exception as e:
            return False, f"Ошибка: {e}"


# Global service instance
caldav_service = CalDAVService()
