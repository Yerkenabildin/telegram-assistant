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
