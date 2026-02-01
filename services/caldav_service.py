"""
CalDAV calendar integration service.

Checks for active calendar events and manages meeting status accordingly.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
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


@dataclass
class CalendarEvent:
    """Represents an active calendar event."""
    uid: str
    summary: str
    start: datetime
    end: datetime
    description: Optional[str] = None

    def is_meeting(self, keywords: list[str]) -> bool:
        """Check if this event is a meeting based on keywords.

        If no keywords configured, all events are considered meetings.
        """
        if not keywords:
            return True

        text = f"{self.summary} {self.description or ''}".lower()
        return any(kw in text for kw in keywords)


class CalDAVService:
    """Service for interacting with CalDAV calendar."""

    def __init__(self):
        self._client: Optional[caldav.DAVClient] = None
        self._calendar: Optional[caldav.Calendar] = None
        self._last_event_uid: Optional[str] = None
        self._tz = ZoneInfo(config.timezone)

    def is_configured(self) -> bool:
        """Check if CalDAV is properly configured."""
        if not CALDAV_AVAILABLE:
            return False
        return bool(
            config.caldav_url and
            config.caldav_username and
            config.caldav_password
        )

    async def connect(self) -> bool:
        """Connect to CalDAV server and select calendar.

        Returns True if connection successful.
        """
        if not self.is_configured():
            return False

        try:
            # CalDAV operations are blocking, run in executor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._connect_sync)
        except Exception as e:
            logger.error(f"Failed to connect to CalDAV server: {e}")
            return False

    def _connect_sync(self) -> bool:
        """Synchronous connection to CalDAV server."""
        try:
            self._client = caldav.DAVClient(
                url=config.caldav_url,
                username=config.caldav_username,
                password=config.caldav_password
            )

            principal = self._client.principal()
            calendars = principal.calendars()

            if not calendars:
                logger.error("No calendars found on CalDAV server")
                return False

            # Find calendar by name or use first one
            if config.caldav_calendar_name:
                for cal in calendars:
                    if cal.name == config.caldav_calendar_name:
                        self._calendar = cal
                        break
                if not self._calendar:
                    logger.warning(
                        f"Calendar '{config.caldav_calendar_name}' not found, "
                        f"using first available: {calendars[0].name}"
                    )
                    self._calendar = calendars[0]
            else:
                self._calendar = calendars[0]

            logger.info(f"Connected to CalDAV calendar: {self._calendar.name}")
            return True

        except Exception as e:
            logger.error(f"CalDAV connection error: {e}")
            self._client = None
            self._calendar = None
            return False

    async def get_current_event(self) -> Optional[CalendarEvent]:
        """Get currently active calendar event.

        Returns the first active event that matches meeting keywords,
        or None if no active meeting.
        """
        if not self._calendar:
            if not await self.connect():
                return None

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._get_current_event_sync)
        except Exception as e:
            logger.error(f"Error fetching calendar events: {e}")
            # Reset connection on error
            self._calendar = None
            return None

    def _get_current_event_sync(self) -> Optional[CalendarEvent]:
        """Synchronously get current calendar event."""
        now = datetime.now(self._tz)

        # Search for events in a small window around now
        # We look 1 minute back to catch events that just started
        start = now - timedelta(minutes=1)
        end = now + timedelta(minutes=1)

        try:
            events = self._calendar.search(
                start=start,
                end=end,
                event=True,
                expand=True
            )
        except Exception as e:
            logger.error(f"CalDAV search error: {e}")
            return None

        if not events:
            return None

        # Parse events and find active meetings
        for event in events:
            try:
                cal_event = self._parse_event(event)
                if cal_event and self._is_event_active(cal_event, now):
                    if cal_event.is_meeting(config.caldav_meeting_keywords):
                        return cal_event
            except Exception as e:
                logger.warning(f"Error parsing calendar event: {e}")
                continue

        return None

    def _parse_event(self, event) -> Optional[CalendarEvent]:
        """Parse caldav event into CalendarEvent dataclass."""
        try:
            vevent = event.vobject_instance.vevent

            # Get event times
            dtstart = vevent.dtstart.value
            dtend = vevent.dtend.value if hasattr(vevent, 'dtend') else None

            # Handle all-day events (date instead of datetime)
            if not isinstance(dtstart, datetime):
                # All-day event - convert to datetime
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
                # Default 1 hour duration if no end time
                dtend = dtstart + timedelta(hours=1)

            summary = str(vevent.summary.value) if hasattr(vevent, 'summary') else "Untitled"
            description = str(vevent.description.value) if hasattr(vevent, 'description') else None
            uid = str(vevent.uid.value) if hasattr(vevent, 'uid') else str(id(event))

            return CalendarEvent(
                uid=uid,
                summary=summary,
                start=dtstart,
                end=dtend,
                description=description
            )
        except Exception as e:
            logger.warning(f"Failed to parse event: {e}")
            return None

    def _is_event_active(self, event: CalendarEvent, now: datetime) -> bool:
        """Check if event is currently active."""
        return event.start <= now <= event.end

    async def check_meeting_status(self) -> tuple[bool, Optional[CalendarEvent]]:
        """Check if there's an active meeting.

        Returns:
            Tuple of (is_in_meeting, current_event)
        """
        event = await self.get_current_event()

        if event:
            # Track event UID to detect changes
            if event.uid != self._last_event_uid:
                logger.info(f"Calendar meeting started: {event.summary}")
                self._last_event_uid = event.uid
            return True, event
        else:
            if self._last_event_uid:
                logger.info("Calendar meeting ended")
                self._last_event_uid = None
            return False, None

    def get_last_event_uid(self) -> Optional[str]:
        """Get UID of the last tracked event."""
        return self._last_event_uid

    def clear_state(self):
        """Clear internal state (e.g., when disabling calendar sync)."""
        self._last_event_uid = None


# Global service instance
caldav_service = CalDAVService()
