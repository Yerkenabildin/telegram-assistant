"""
Database models for telegram-assistant.

Uses sqlitemodel ORM for SQLite persistence.
"""
import json
from datetime import datetime, date
from typing import Optional, Any
from zoneinfo import ZoneInfo

from sqlitemodel import Model, Database, SQL
from telethon.extensions import BinaryReader
from telethon.tl.types import Message

from config import config

# Configure database path (can be overridden by config)
Database.DB_FILE = './storage/database.db'


def get_now() -> datetime:
    """Get current datetime in the configured timezone."""
    return datetime.now(ZoneInfo(config.timezone))

# Day name mappings for parsing
DAY_NAMES = {
    'пн': 0, 'mon': 0, 'пнд': 0,
    'вт': 1, 'tue': 1, 'втр': 1,
    'ср': 2, 'wed': 2, 'срд': 2,
    'чт': 3, 'thu': 3, 'чтв': 3,
    'пт': 4, 'fri': 4, 'птн': 4,
    'сб': 5, 'sat': 5, 'суб': 5,
    'вс': 6, 'sun': 6, 'вск': 6,
}

DAY_DISPLAY = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']

# Priority levels
PRIORITY_REST = 1        # Fallback/rest rules
PRIORITY_WEEKENDS = 8    # Weekends schedule
PRIORITY_WORK = 10       # Work schedule
PRIORITY_MEETING = 50    # Active meeting/call (via API)
PRIORITY_OVERRIDE = 100  # Override rules (vacation, sick leave, etc.)


class Reply(Model):
    """
    Model for storing emoji-to-message reply mappings.

    Attributes:
        emoji: Custom emoji document ID (stored as string)
        _message: Serialized Telethon Message object
    """

    emoji: str
    _message: bytes

    def __init__(self, id: Optional[int] = None):
        Model.__init__(self, id, foreign_keys=True)

    def tablename(self) -> str:
        # Note: Historical typo kept for backwards compatibility
        return 'replays'

    @property
    def message(self) -> Optional[Message]:
        """Deserialize and return the stored message."""
        if not self._message:
            return None
        try:
            reader = BinaryReader(self._message)
            reader.read_int()
            return Message.from_reader(reader)
        except Exception:
            return None

    @message.setter
    def message(self, value: Message) -> None:
        """Serialize and store a message."""
        self._message = value._bytes()

    def columns(self) -> list[dict[str, str]]:
        return [
            {'name': 'emoji', 'type': 'TEXT'},
            {'name': '_message', 'type': 'TEXT'}
        ]

    @staticmethod
    def create(emoji: Any, msg: Message) -> None:
        """
        Create or update a reply mapping.

        Args:
            emoji: Emoji document ID (int or str)
            msg: Telethon Message object to store
        """
        emoji_str = str(emoji)
        reply = Reply.get_by_emoji(emoji_str)
        if reply is None:
            reply = Reply()
        reply.emoji = emoji_str
        reply.message = msg
        reply.save()

    @staticmethod
    def get_by_emoji(emoji: Any) -> Optional['Reply']:
        """
        Get reply by emoji ID.

        Args:
            emoji: Emoji document ID (int or str)

        Returns:
            Reply object or None if not found
        """
        emoji_str = str(emoji)
        return Reply().selectOne(SQL().WHERE('emoji', '=', emoji_str))


class Settings(Model):
    """
    Model for storing application settings as key-value pairs.

    Attributes:
        key: Setting identifier
        value: Setting value (stored as string)
    """

    key: str
    value: str

    def __init__(self, id: Optional[int] = None):
        Model.__init__(self, id, foreign_keys=True)

    def tablename(self) -> str:
        return 'settings'

    def columns(self) -> list[dict[str, str]]:
        return [
            {'name': 'key', 'type': 'TEXT'},
            {'name': 'value', 'type': 'TEXT'}
        ]

    @staticmethod
    def get(key: str) -> Optional[str]:
        """
        Get a setting value by key.

        Args:
            key: Setting key

        Returns:
            Setting value or None if not found
        """
        setting = Settings().selectOne(SQL().WHERE('key', '=', key))
        return setting.value if setting else None

    @staticmethod
    def set(key: str, value: str) -> None:
        """
        Set a setting value.

        Args:
            key: Setting key
            value: Setting value
        """
        setting = Settings().selectOne(SQL().WHERE('key', '=', key))
        if setting is None:
            setting = Settings()
        setting.key = key
        setting.value = value
        setting.save()

    @staticmethod
    def get_settings_chat_id() -> Optional[int]:
        """
        Get the settings chat ID.

        Returns:
            Chat ID as integer or None if not set
        """
        value = Settings.get('settings_chat_id')
        return int(value) if value else None

    @staticmethod
    def set_settings_chat_id(chat_id: Optional[int]) -> None:
        """
        Set or clear the settings chat ID.

        Args:
            chat_id: Chat ID to set, or None to clear
        """
        if chat_id is None:
            setting = Settings().selectOne(SQL().WHERE('key', '=', 'settings_chat_id'))
            if setting:
                setting.delete()
        else:
            Settings.set('settings_chat_id', str(chat_id))


class Schedule(Model):
    """Model for storing emoji schedule rules"""

    def __init__(self, id=None):
        Model.__init__(self, id, foreign_keys=True)

    def tablename(self):
        return 'schedules'

    def columns(self):
        return [
            {'name': 'emoji_id', 'type': 'TEXT'},      # Telegram custom emoji document_id
            {'name': 'days', 'type': 'TEXT'},           # Comma-separated day numbers: "0,1,2,3,4" for Mon-Fri
            {'name': 'time_start', 'type': 'TEXT'},     # "09:00"
            {'name': 'time_end', 'type': 'TEXT'},       # "18:00"
            {'name': 'priority', 'type': 'INTEGER'},    # Higher priority wins in conflicts
            {'name': 'name', 'type': 'TEXT'},           # Human-readable rule name
            {'name': 'date_start', 'type': 'TEXT'},     # "2024-01-15" - optional start date
            {'name': 'date_end', 'type': 'TEXT'},       # "2024-01-20" - optional end date
        ]

    @staticmethod
    def create(emoji_id, days, time_start, time_end, priority=0, name="", date_start=None, date_end=None):
        """Create a new schedule rule"""
        schedule = Schedule()
        schedule.emoji_id = str(emoji_id)
        schedule.days = days if isinstance(days, str) else ','.join(map(str, days))
        schedule.time_start = time_start
        schedule.time_end = time_end
        schedule.priority = priority
        schedule.name = name
        schedule.date_start = date_start
        schedule.date_end = date_end
        schedule.save()
        return schedule

    @staticmethod
    def create_override(emoji_id, date_start, date_end, name="Перекрытие"):
        """Create an override rule that applies 24/7 within date range"""
        return Schedule.create(
            emoji_id=emoji_id,
            days=[0, 1, 2, 3, 4, 5, 6],  # Every day
            time_start="00:00",
            time_end="23:59",
            priority=PRIORITY_OVERRIDE,
            name=name,
            date_start=date_start,
            date_end=date_end
        )

    @staticmethod
    def get_all():
        """Get all schedule rules ordered by priority"""
        return Schedule().select(SQL().ORDER_BY('priority', 'DESC')) or []

    @staticmethod
    def get_overrides():
        """Get all override rules (rules with date ranges)"""
        all_rules = Schedule.get_all()
        return [r for r in all_rules if r.is_override()]

    @staticmethod
    def delete_expired():
        """Delete all expired override rules"""
        deleted = 0
        for schedule in Schedule.get_overrides():
            if schedule.is_expired():
                schedule.delete()
                deleted += 1
        return deleted

    @staticmethod
    def delete_all():
        """Delete all schedule rules"""
        for schedule in Schedule.get_all():
            schedule.delete()

    @staticmethod
    def delete_by_id(schedule_id):
        """Delete a schedule rule by ID"""
        schedule = Schedule(schedule_id)
        if schedule.emoji_id:  # exists
            schedule.delete()
            return True
        return False

    def get_days_list(self):
        """Get days as list of integers"""
        if not self.days:
            return []
        return [int(d) for d in self.days.split(',')]

    def get_days_display(self):
        """Get days as human-readable string"""
        days = self.get_days_list()
        if len(days) == 7:
            return "каждый день"
        if days == [0, 1, 2, 3, 4]:
            return "ПН-ПТ"
        if days == [5, 6]:
            return "СБ-ВС"
        return ', '.join(DAY_DISPLAY[d] for d in days)

    def is_override(self):
        """Check if this is an override rule (has date range)"""
        return self.date_start is not None or self.date_end is not None

    def get_date_display(self):
        """Get date range as human-readable string"""
        if not self.is_override():
            return None
        if self.date_start and self.date_end:
            return f"{self.date_start} — {self.date_end}"
        elif self.date_start:
            return f"с {self.date_start}"
        elif self.date_end:
            return f"до {self.date_end}"
        return None

    def is_expired(self, now=None):
        """Check if this override rule has expired"""
        if not self.date_end:
            return False
        if now is None:
            now = get_now()
        current_date = now.strftime('%Y-%m-%d')
        return current_date > self.date_end

    def matches_now(self, now=None):
        """Check if this schedule rule matches current time"""
        if now is None:
            now = get_now()

        current_date = now.strftime('%Y-%m-%d')

        # Check date range if specified
        if self.date_start and current_date < self.date_start:
            return False
        if self.date_end and current_date > self.date_end:
            return False

        current_day = now.weekday()  # 0=Monday, 6=Sunday
        current_time = now.strftime('%H:%M')

        # Check if current day matches
        if current_day not in self.get_days_list():
            return False

        # Check time range
        start = self.time_start
        end = self.time_end

        # Handle overnight ranges (e.g., 22:00-06:00)
        if start <= end:
            # Normal range (e.g., 09:00-18:00)
            return start <= current_time < end
        else:
            # Overnight range (e.g., 22:00-06:00)
            return current_time >= start or current_time < end

    @staticmethod
    def get_current_emoji_id(now=None):
        """Get the emoji_id that should be active right now based on schedule"""
        if now is None:
            now = get_now()

        matching_rules = []
        for schedule in Schedule.get_all():
            if schedule.matches_now(now):
                matching_rules.append(schedule)

        if not matching_rules:
            return None

        # Return highest priority match
        matching_rules.sort(key=lambda s: s.priority, reverse=True)
        return int(matching_rules[0].emoji_id)

    @staticmethod
    def is_scheduling_enabled():
        """Check if scheduling is enabled"""
        return Settings.get('schedule_enabled') == 'true'

    @staticmethod
    def set_scheduling_enabled(enabled):
        """Enable or disable scheduling"""
        Settings.set('schedule_enabled', 'true' if enabled else 'false')

    # Meeting management methods
    @staticmethod
    def get_active_meeting():
        """Get active meeting rule if exists"""
        all_rules = Schedule.get_all()
        for rule in all_rules:
            if rule.priority == PRIORITY_MEETING:
                return rule
        return None

    @staticmethod
    def start_meeting(emoji_id):
        """Start a meeting - creates a high-priority rule that covers all time"""
        # Remove any existing meeting rule first
        Schedule.end_meeting()

        # Create meeting rule (all days, all time, priority 50)
        return Schedule.create(
            emoji_id=emoji_id,
            days=[0, 1, 2, 3, 4, 5, 6],
            time_start="00:00",
            time_end="23:59",
            priority=PRIORITY_MEETING,
            name="meeting"
        )

    @staticmethod
    def end_meeting():
        """End meeting - removes the meeting rule"""
        meeting = Schedule.get_active_meeting()
        if meeting:
            meeting.delete()
            return True
        return False


def parse_days(days_str):
    """Parse days string like 'ПН-ПТ' or 'ПН,СР,ПТ' into list of day numbers"""
    days_str = days_str.lower().strip()

    # Handle range like "ПН-ПТ"
    if '-' in days_str:
        parts = days_str.split('-')
        if len(parts) == 2:
            start = DAY_NAMES.get(parts[0].strip())
            end = DAY_NAMES.get(parts[1].strip())
            if start is not None and end is not None:
                if start <= end:
                    return list(range(start, end + 1))
                else:
                    # Wrap around (e.g., ПТ-ПН)
                    return list(range(start, 7)) + list(range(0, end + 1))

    # Handle comma-separated like "ПН,СР,ПТ"
    if ',' in days_str:
        result = []
        for part in days_str.split(','):
            day = DAY_NAMES.get(part.strip())
            if day is not None:
                result.append(day)
        return sorted(result)

    # Single day
    day = DAY_NAMES.get(days_str)
    if day is not None:
        return [day]

    return None


def parse_time(time_str):
    """Parse time string like '09:00' or '9:00'"""
    time_str = time_str.strip()
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
            hour = int(parts[0])
            minute = int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
    except ValueError:
        pass
    return None


def parse_time_range(range_str):
    """Parse time range like '09:00-18:00'"""
    if '-' not in range_str:
        return None, None

    parts = range_str.split('-')
    if len(parts) != 2:
        return None, None

    start = parse_time(parts[0])
    end = parse_time(parts[1])

    return start, end


def parse_date(date_str):
    """Parse date string like '25.12', '25.12.2024', or '2024-12-25'"""
    date_str = date_str.strip()

    # Try different formats
    formats = [
        ('%d.%m.%Y', True),   # 25.12.2024
        ('%d.%m', False),      # 25.12 (current year)
        ('%Y-%m-%d', True),   # 2024-12-25
        ('%d/%m/%Y', True),   # 25/12/2024
        ('%d/%m', False),      # 25/12 (current year)
    ]

    for fmt, has_year in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if not has_year:
                # Use current year, or next year if date is in the past
                today = date.today()
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today:
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.strftime('%Y-%m-%d')
        except ValueError:
            continue

    return None


def parse_date_range(range_str):
    """Parse date range like '25.12-30.12' or '25.12.2024-05.01.2025'"""
    # Try to split by various separators
    for sep in [' - ', ' — ', '-', '—']:
        if sep in range_str:
            parts = range_str.split(sep)
            if len(parts) == 2:
                start = parse_date(parts[0].strip())
                end = parse_date(parts[1].strip())
                if start and end:
                    return start, end

    return None, None
