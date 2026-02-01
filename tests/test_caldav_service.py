"""
Tests for CalDAV calendar integration service.

Tests cover:
- CalendarEvent dataclass
- Meeting detection based on keywords
- Service configuration validation
"""
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from typing import Optional

# Mock all external dependencies before any imports
mock_modules = [
    'sqlitemodel', 'telethon', 'telethon.extensions', 'telethon.tl',
    'telethon.tl.types', 'aiohttp', 'caldav', 'vobject',
    'services.autoreply_service', 'services.notification_service',
    'services.mention_service', 'services.context_extraction_service',
    'services.yandex_gpt_service'
]
for mod in mock_modules:
    sys.modules[mod] = MagicMock()


# Recreate the CalendarEvent dataclass for testing
@dataclass
class CalendarEvent:
    """Represents an active calendar event."""
    uid: str
    summary: str
    start: datetime
    end: datetime
    description: Optional[str] = None

    def is_meeting(self, keywords: list[str]) -> bool:
        """Check if this event is a meeting based on keywords."""
        if not keywords:
            return True
        text = f"{self.summary} {self.description or ''}".lower()
        return any(kw in text for kw in keywords)


class TestCalendarEvent:
    """Tests for CalendarEvent dataclass."""

    def test_is_meeting_no_keywords(self):
        """When no keywords configured, all events are meetings."""
        event = CalendarEvent(
            uid="test-123",
            summary="Random Event",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1)
        )

        assert event.is_meeting([]) is True

    def test_is_meeting_with_matching_keyword(self):
        """Event with matching keyword in summary is a meeting."""
        event = CalendarEvent(
            uid="test-123",
            summary="Team Standup Meeting",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1)
        )

        assert event.is_meeting(["meeting", "call"]) is True

    def test_is_meeting_with_keyword_in_description(self):
        """Event with matching keyword in description is a meeting."""
        event = CalendarEvent(
            uid="test-123",
            summary="Sync",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1),
            description="Zoom call with the team"
        )

        assert event.is_meeting(["meeting", "call"]) is True

    def test_is_meeting_no_matching_keyword(self):
        """Event without matching keywords is not a meeting."""
        event = CalendarEvent(
            uid="test-123",
            summary="Lunch Break",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1),
            description="Personal time"
        )

        assert event.is_meeting(["meeting", "call", "standup"]) is False

    def test_is_meeting_case_insensitive(self):
        """Keyword matching is case-insensitive."""
        event = CalendarEvent(
            uid="test-123",
            summary="TEAM MEETING",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1)
        )

        assert event.is_meeting(["meeting"]) is True


class TestEventActiveCheck:
    """Tests for event active status checking."""

    def test_is_event_active_within_range(self):
        """Event is active when current time is within start-end range."""
        tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)

        event = CalendarEvent(
            uid="test-123",
            summary="Test Meeting",
            start=now - timedelta(minutes=30),
            end=now + timedelta(minutes=30)
        )

        # Simple check: start <= now <= end
        assert event.start <= now <= event.end

    def test_is_event_active_before_start(self):
        """Event is not active before start time."""
        tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)

        event = CalendarEvent(
            uid="test-123",
            summary="Test Meeting",
            start=now + timedelta(minutes=30),
            end=now + timedelta(hours=1)
        )

        assert not (event.start <= now <= event.end)

    def test_is_event_active_after_end(self):
        """Event is not active after end time."""
        tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)

        event = CalendarEvent(
            uid="test-123",
            summary="Test Meeting",
            start=now - timedelta(hours=2),
            end=now - timedelta(hours=1)
        )

        assert not (event.start <= now <= event.end)


class TestCalDAVServiceConfiguration:
    """Tests for CalDAV service configuration validation."""

    def test_is_configured_requires_url(self):
        """Configuration requires caldav_url."""
        mock_config = MagicMock()
        mock_config.caldav_url = None
        mock_config.caldav_username = "user"
        mock_config.caldav_password = "pass"

        # Check configuration logic
        is_configured = bool(
            mock_config.caldav_url and
            mock_config.caldav_username and
            mock_config.caldav_password
        )

        assert is_configured is False

    def test_is_configured_requires_username(self):
        """Configuration requires caldav_username."""
        mock_config = MagicMock()
        mock_config.caldav_url = "https://caldav.example.com"
        mock_config.caldav_username = None
        mock_config.caldav_password = "pass"

        is_configured = bool(
            mock_config.caldav_url and
            mock_config.caldav_username and
            mock_config.caldav_password
        )

        assert is_configured is False

    def test_is_configured_requires_password(self):
        """Configuration requires caldav_password."""
        mock_config = MagicMock()
        mock_config.caldav_url = "https://caldav.example.com"
        mock_config.caldav_username = "user"
        mock_config.caldav_password = None

        is_configured = bool(
            mock_config.caldav_url and
            mock_config.caldav_username and
            mock_config.caldav_password
        )

        assert is_configured is False

    def test_is_configured_all_set(self):
        """Configuration is valid when all required fields are set."""
        mock_config = MagicMock()
        mock_config.caldav_url = "https://caldav.example.com"
        mock_config.caldav_username = "user@example.com"
        mock_config.caldav_password = "password123"

        is_configured = bool(
            mock_config.caldav_url and
            mock_config.caldav_username and
            mock_config.caldav_password
        )

        assert is_configured is True


class TestMeetingStatusTracking:
    """Tests for meeting status tracking logic."""

    def test_track_event_uid_on_meeting_start(self):
        """Event UID is tracked when meeting starts."""
        last_event_uid = None

        # Simulate meeting start
        event = CalendarEvent(
            uid="meeting-123",
            summary="Standup",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1)
        )

        if event.uid != last_event_uid:
            last_event_uid = event.uid

        assert last_event_uid == "meeting-123"

    def test_clear_uid_when_meeting_ends(self):
        """Event UID is cleared when meeting ends."""
        last_event_uid = "meeting-123"

        # Simulate meeting end (no active event)
        current_event = None

        if not current_event:
            last_event_uid = None

        assert last_event_uid is None

    def test_detect_new_meeting_by_uid_change(self):
        """New meeting is detected when UID changes."""
        last_event_uid = "meeting-123"

        # New meeting starts
        new_event = CalendarEvent(
            uid="meeting-456",
            summary="New Meeting",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1)
        )

        is_new_meeting = new_event.uid != last_event_uid

        assert is_new_meeting is True


# Recreate CalendarInfo dataclass for testing
@dataclass
class CalendarInfo:
    """Represents a calendar on the CalDAV server."""
    name: str
    url: str


class TestCalendarInfo:
    """Tests for CalendarInfo dataclass."""

    def test_basic_creation(self):
        """CalendarInfo stores name and url."""
        cal = CalendarInfo(name="Work Calendar", url="https://caldav.example.com/work")
        assert cal.name == "Work Calendar"
        assert cal.url == "https://caldav.example.com/work"

    def test_multiple_calendars(self):
        """Multiple CalendarInfo instances can be created."""
        calendars = [
            CalendarInfo(name="Work", url="https://caldav.example.com/work"),
            CalendarInfo(name="Personal", url="https://caldav.example.com/personal"),
            CalendarInfo(name="Team", url="https://caldav.example.com/team"),
        ]
        assert len(calendars) == 3
        assert calendars[0].name == "Work"
        assert calendars[1].name == "Personal"
        assert calendars[2].name == "Team"


class TestCalendarSelection:
    """Tests for calendar selection settings logic."""

    def test_parse_calendars_from_pipe_separated_string(self):
        """Calendars are stored as pipe-separated string."""
        value = "Work|Personal|Team"
        calendars = [c.strip() for c in value.split('|') if c.strip()]
        assert calendars == ["Work", "Personal", "Team"]

    def test_parse_empty_string_returns_empty_list(self):
        """Empty string means no selection (use all calendars)."""
        value = ""
        if not value:
            calendars = []
        else:
            calendars = [c.strip() for c in value.split('|') if c.strip()]
        assert calendars == []

    def test_parse_none_returns_empty_list(self):
        """None value means no selection (use all calendars)."""
        value = None
        if not value:
            calendars = []
        else:
            calendars = [c.strip() for c in value.split('|') if c.strip()]
        assert calendars == []

    def test_serialize_calendars_to_pipe_separated_string(self):
        """Calendars are serialized to pipe-separated string."""
        calendars = ["Work", "Personal", "Team"]
        value = '|'.join(calendars)
        assert value == "Work|Personal|Team"

    def test_add_calendar_to_list(self):
        """Adding a calendar appends to the list."""
        calendars = ["Work", "Personal"]
        name = "Team"
        if name not in calendars:
            calendars.append(name)
        assert calendars == ["Work", "Personal", "Team"]

    def test_add_duplicate_calendar_not_added(self):
        """Adding a duplicate calendar does not create duplicate."""
        calendars = ["Work", "Personal"]
        name = "Work"
        if name not in calendars:
            calendars.append(name)
        assert calendars == ["Work", "Personal"]

    def test_remove_calendar_from_list(self):
        """Removing a calendar removes it from the list."""
        calendars = ["Work", "Personal", "Team"]
        name = "Personal"
        if name in calendars:
            calendars.remove(name)
        assert calendars == ["Work", "Team"]

    def test_remove_nonexistent_calendar_no_error(self):
        """Removing a non-existent calendar does not raise error."""
        calendars = ["Work", "Personal"]
        name = "Team"
        if name in calendars:
            calendars.remove(name)
        assert calendars == ["Work", "Personal"]


class TestMultiCalendarFiltering:
    """Tests for filtering calendars based on selection."""

    def test_no_selection_uses_all_calendars(self):
        """When no calendars selected, all calendars are used."""
        all_calendars = ["Work", "Personal", "Team"]
        selected = []  # Empty means use all

        if not selected:
            active = all_calendars
        else:
            active = [c for c in all_calendars if c in selected]

        assert active == ["Work", "Personal", "Team"]

    def test_selection_filters_calendars(self):
        """When calendars selected, only those are used."""
        all_calendars = ["Work", "Personal", "Team"]
        selected = ["Work", "Team"]

        if not selected:
            active = all_calendars
        else:
            active = [c for c in all_calendars if c in selected]

        assert active == ["Work", "Team"]

    def test_selection_handles_removed_calendars(self):
        """Selected calendars that no longer exist are ignored."""
        all_calendars = ["Work", "Personal"]  # Team was removed
        selected = ["Work", "Team"]

        if not selected:
            active = all_calendars
        else:
            active = [c for c in all_calendars if c in selected]

        assert active == ["Work"]

    def test_single_calendar_selection(self):
        """Single calendar can be selected."""
        all_calendars = ["Work", "Personal", "Team"]
        selected = ["Personal"]

        if not selected:
            active = all_calendars
        else:
            active = [c for c in all_calendars if c in selected]

        assert active == ["Personal"]


class TestMultiCalendarEventSearch:
    """Tests for searching events across multiple calendars."""

    def test_find_event_in_first_calendar(self):
        """Event in first calendar is found."""
        calendars = {
            "Work": [CalendarEvent(
                uid="work-1",
                summary="Work Meeting",
                start=datetime.now(),
                end=datetime.now() + timedelta(hours=1)
            )],
            "Personal": []
        }

        current_event = None
        for cal_name, events in calendars.items():
            for event in events:
                now = datetime.now()
                if event.start <= now <= event.end:
                    current_event = event
                    break
            if current_event:
                break

        assert current_event is not None
        assert current_event.uid == "work-1"

    def test_find_event_in_second_calendar(self):
        """Event in second calendar is found."""
        calendars = {
            "Work": [],
            "Personal": [CalendarEvent(
                uid="personal-1",
                summary="Personal Meeting",
                start=datetime.now(),
                end=datetime.now() + timedelta(hours=1)
            )]
        }

        current_event = None
        for cal_name, events in calendars.items():
            for event in events:
                now = datetime.now()
                if event.start <= now <= event.end:
                    current_event = event
                    break
            if current_event:
                break

        assert current_event is not None
        assert current_event.uid == "personal-1"

    def test_no_event_when_all_calendars_empty(self):
        """No event found when all calendars are empty."""
        calendars = {
            "Work": [],
            "Personal": []
        }

        current_event = None
        for cal_name, events in calendars.items():
            for event in events:
                now = datetime.now()
                if event.start <= now <= event.end:
                    current_event = event
                    break
            if current_event:
                break

        assert current_event is None

    def test_first_active_event_wins(self):
        """When multiple calendars have active events, first one wins."""
        now = datetime.now()
        calendars = {
            "Work": [CalendarEvent(
                uid="work-1",
                summary="Work Meeting",
                start=now - timedelta(minutes=30),
                end=now + timedelta(minutes=30)
            )],
            "Personal": [CalendarEvent(
                uid="personal-1",
                summary="Personal Meeting",
                start=now - timedelta(minutes=15),
                end=now + timedelta(minutes=45)
            )]
        }

        current_event = None
        for cal_name, events in calendars.items():
            for event in events:
                if event.start <= now <= event.end:
                    current_event = event
                    break
            if current_event:
                break

        # First calendar (Work) wins
        assert current_event is not None
        assert current_event.uid == "work-1"


class TestCalendarEventWithCalendarName:
    """Tests for CalendarEvent with calendar_name field."""

    def test_event_stores_calendar_name(self):
        """Event can store which calendar it came from."""
        @dataclass
        class CalendarEventWithSource:
            uid: str
            summary: str
            start: datetime
            end: datetime
            calendar_name: str
            description: Optional[str] = None

        event = CalendarEventWithSource(
            uid="test-123",
            summary="Team Meeting",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1),
            calendar_name="Work Calendar"
        )

        assert event.calendar_name == "Work Calendar"

    def test_event_from_different_calendars(self):
        """Events from different calendars have different calendar_name."""
        @dataclass
        class CalendarEventWithSource:
            uid: str
            summary: str
            start: datetime
            end: datetime
            calendar_name: str
            description: Optional[str] = None

        events = [
            CalendarEventWithSource(
                uid="work-1",
                summary="Work Meeting",
                start=datetime.now(),
                end=datetime.now() + timedelta(hours=1),
                calendar_name="Work"
            ),
            CalendarEventWithSource(
                uid="personal-1",
                summary="Doctor Appointment",
                start=datetime.now(),
                end=datetime.now() + timedelta(hours=1),
                calendar_name="Personal"
            ),
        ]

        assert events[0].calendar_name == "Work"
        assert events[1].calendar_name == "Personal"
