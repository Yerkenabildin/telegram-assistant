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


def parse_date_str(date_str: str, reference_year: int = None) -> date:
    """Parse date string in DD.MM or DD.MM.YYYY format to date object.

    Args:
        date_str: Date string like "25.12" or "25.12.2024"
        reference_year: Year to use if not specified in date_str

    Returns:
        date object
    """
    if reference_year is None:
        reference_year = get_now().year

    parts = date_str.split('.')
    day = int(parts[0])
    month = int(parts[1])
    year = int(parts[2]) if len(parts) > 2 else reference_year

    return date(year, month, day)

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
PRIORITY_MORNING = 2     # Morning (before work) on weekdays
PRIORITY_EVENING = 3     # Evening (after work) on weekdays
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

    # =========================================================================
    # Autoreply Settings
    # =========================================================================

    @staticmethod
    def is_autoreply_enabled() -> bool:
        """Check if autoreply is enabled (default: True)."""
        value = Settings.get('autoreply_enabled')
        return value != 'false'  # Default is True

    @staticmethod
    def set_autoreply_enabled(enabled: bool) -> None:
        """Enable or disable autoreply."""
        Settings.set('autoreply_enabled', 'true' if enabled else 'false')

    # =========================================================================
    # Mention Notification Settings
    # =========================================================================

    @staticmethod
    def is_offline_mention_enabled() -> bool:
        """Check if offline mention notifications are enabled (default: True)."""
        value = Settings.get('offline_mention_enabled')
        return value != 'false'  # Default is True

    @staticmethod
    def set_offline_mention_enabled(enabled: bool) -> None:
        """Enable or disable offline mention notifications."""
        Settings.set('offline_mention_enabled', 'true' if enabled else 'false')

    @staticmethod
    def is_online_mention_enabled() -> bool:
        """Check if online mention notifications are enabled (default: True)."""
        value = Settings.get('online_mention_enabled')
        return value != 'false'  # Default is True

    @staticmethod
    def set_online_mention_enabled(enabled: bool) -> None:
        """Enable or disable online mention notifications."""
        Settings.set('online_mention_enabled', 'true' if enabled else 'false')

    @staticmethod
    def get_online_mention_delay() -> int:
        """Get delay in minutes before sending online mention notifications (default: 10)."""
        value = Settings.get('online_mention_delay')
        if value is None:
            return 10
        try:
            return int(value)
        except ValueError:
            return 10

    @staticmethod
    def set_online_mention_delay(minutes: int) -> None:
        """Set delay in minutes before sending online mention notifications."""
        Settings.set('online_mention_delay', str(minutes))

    # =========================================================================
    # Productivity Summary Settings
    # =========================================================================

    @staticmethod
    def is_productivity_summary_enabled() -> bool:
        """Check if daily productivity summary is enabled (default: False)."""
        value = Settings.get('productivity_summary_enabled')
        return value == 'true'

    @staticmethod
    def set_productivity_summary_enabled(enabled: bool) -> None:
        """Enable or disable daily productivity summary."""
        Settings.set('productivity_summary_enabled', 'true' if enabled else 'false')

    @staticmethod
    def get_productivity_summary_time() -> Optional[str]:
        """Get time for daily productivity summary (HH:MM format).

        Returns:
            Time string like "19:00" or None if not set
        """
        return Settings.get('productivity_summary_time')

    @staticmethod
    def set_productivity_summary_time(time_str: Optional[str]) -> None:
        """Set time for daily productivity summary.

        Args:
            time_str: Time in HH:MM format, or None to clear
        """
        if time_str is None:
            setting = Settings().selectOne(SQL().WHERE('key', '=', 'productivity_summary_time'))
            if setting:
                setting.delete()
        else:
            Settings.set('productivity_summary_time', time_str)

    @staticmethod
    def get_productivity_extra_chats() -> List[int]:
        """Get list of extra chat IDs to always include in productivity summary.

        Returns:
            List of chat IDs
        """
        value = Settings.get('productivity_extra_chats')
        if not value:
            return []
        try:
            return [int(x) for x in value.split(',') if x.strip()]
        except ValueError:
            return []

    @staticmethod
    def add_productivity_extra_chat(chat_id: int) -> None:
        """Add a chat to the extra chats list for productivity summary."""
        chats = Settings.get_productivity_extra_chats()
        if chat_id not in chats:
            chats.append(chat_id)
            Settings.set('productivity_extra_chats', ','.join(str(c) for c in chats))

    @staticmethod
    def remove_productivity_extra_chat(chat_id: int) -> bool:
        """Remove a chat from the extra chats list.

        Returns:
            True if removed, False if not found
        """
        chats = Settings.get_productivity_extra_chats()
        if chat_id in chats:
            chats.remove(chat_id)
            Settings.set('productivity_extra_chats', ','.join(str(c) for c in chats))
            return True
        return False


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
    def create_override(emoji_id, date_start, date_end, time_start="00:00", time_end="23:59", name="Перекрытие"):
        """Create an override rule within date/time range.

        Args:
            emoji_id: Emoji document ID
            date_start: Start date (DD.MM or DD.MM.YYYY)
            date_end: End date (DD.MM or DD.MM.YYYY)
            time_start: Start time (HH:MM), default "00:00"
            time_end: End time (HH:MM), default "23:59"
            name: Rule name
        """
        return Schedule.create(
            emoji_id=emoji_id,
            days=[0, 1, 2, 3, 4, 5, 6],  # Every day
            time_start=time_start,
            time_end=time_end,
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
        for schedule in Schedule.get_all():
            if schedule.id == schedule_id:
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

        # Check if time is not default (00:00-23:59)
        has_custom_time = (self.time_start and self.time_start != "00:00") or \
                          (self.time_end and self.time_end != "23:59")

        if self.date_start and self.date_end:
            if has_custom_time:
                if self.date_start == self.date_end:
                    # Same day with time: "06.01 9:30-11:30"
                    return f"{self.date_start} {self.time_start}-{self.time_end}"
                else:
                    # Date range with time: "06.01 12:00 - 07.01 15:00"
                    return f"{self.date_start} {self.time_start} — {self.date_end} {self.time_end}"
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
        try:
            end_date = parse_date_str(self.date_end)
            return now.date() > end_date
        except (ValueError, IndexError):
            return False

    def matches_now(self, now=None):
        """Check if this schedule rule matches current time"""
        if now is None:
            now = get_now()

        # For override rules with specific times, check full datetime range
        if self.is_override() and self.date_start and self.date_end:
            try:
                start_date = parse_date_str(self.date_start)
                end_date = parse_date_str(self.date_end)

                # Parse time components
                start_h, start_m = map(int, self.time_start.split(':'))
                end_h, end_m = map(int, self.time_end.split(':'))

                start_dt = datetime.combine(start_date, datetime.min.time().replace(hour=start_h, minute=start_m))
                end_dt = datetime.combine(end_date, datetime.min.time().replace(hour=end_h, minute=end_m))

                # Make timezone-aware if now is timezone-aware
                if now.tzinfo:
                    start_dt = start_dt.replace(tzinfo=now.tzinfo)
                    end_dt = end_dt.replace(tzinfo=now.tzinfo)

                return start_dt <= now <= end_dt
            except (ValueError, IndexError):
                pass  # Fall through to regular check

        today = now.date()

        # Check date range if specified (for non-override or fallback)
        try:
            if self.date_start:
                start_date = parse_date_str(self.date_start)
                if today < start_date:
                    return False
            if self.date_end:
                end_date = parse_date_str(self.date_end)
                if today > end_date:
                    return False
        except (ValueError, IndexError):
            pass  # Invalid date format, skip date check

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

    @staticmethod
    def get_work_schedule():
        """Get the work schedule rule (priority=PRIORITY_WORK).

        Returns:
            Schedule object or None if no work schedule is configured.
        """
        all_rules = Schedule.get_all()
        for rule in all_rules:
            if rule.priority == PRIORITY_WORK:
                return rule
        return None

    @staticmethod
    def get_work_emoji_id() -> Optional[int]:
        """Get emoji_id from work schedule rule (priority=PRIORITY_WORK).

        Returns:
            Emoji ID as int, or None if no work schedule is configured.
        """
        work = Schedule.get_work_schedule()
        return int(work.emoji_id) if work else None

    @staticmethod
    def get_friday_weekend_schedule():
        """Get the weekend schedule rule that includes Friday (day 4).

        Returns:
            Schedule object or None if no such rule exists.
        """
        all_rules = Schedule.get_all()
        for rule in all_rules:
            if rule.priority == PRIORITY_WEEKENDS and 4 in rule.get_days_list():
                return rule
        return None

    @staticmethod
    def get_morning_schedule():
        """Get the morning schedule rule (before work on weekdays).

        Returns:
            Schedule object or None if no such rule exists.
        """
        all_rules = Schedule.get_all()
        for rule in all_rules:
            if rule.priority == PRIORITY_MORNING:
                return rule
        return None

    @staticmethod
    def get_evening_schedule():
        """Get the evening schedule rule (after work on weekdays).

        Returns:
            Schedule object or None if no such rule exists.
        """
        all_rules = Schedule.get_all()
        for rule in all_rules:
            if rule.priority == PRIORITY_EVENING:
                return rule
        return None

    @staticmethod
    def set_morning_emoji(emoji_id, work_start: str = "09:00"):
        """Set or update morning schedule emoji.

        Args:
            emoji_id: Emoji document ID
            work_start: Work start time (morning ends at this time)
        """
        morning = Schedule.get_morning_schedule()
        if morning:
            morning.emoji_id = str(emoji_id)
            morning.time_end = work_start
            morning.save()
        else:
            Schedule.create(
                emoji_id=emoji_id,
                days=[0, 1, 2, 3, 4],  # Mon-Fri
                time_start="00:00",
                time_end=work_start,
                priority=PRIORITY_MORNING,
                name="morning"
            )

    @staticmethod
    def set_evening_emoji(emoji_id, work_end: str = "18:00"):
        """Set or update evening schedule emoji.

        Args:
            emoji_id: Emoji document ID
            work_end: Work end time (evening starts at this time)
        """
        evening = Schedule.get_evening_schedule()
        if evening:
            evening.emoji_id = str(emoji_id)
            evening.time_start = work_end
            evening.save()
        else:
            Schedule.create(
                emoji_id=emoji_id,
                days=[0, 1, 2, 3, 4],  # Mon-Fri
                time_start=work_end,
                time_end="23:59",
                priority=PRIORITY_EVENING,
                name="evening"
            )

    @staticmethod
    def get_weekend_schedule():
        """Get the weekend schedule rule for Sat-Sun (full day).

        Returns:
            Schedule object or None if no such rule exists.
        """
        all_rules = Schedule.get_all()
        for rule in all_rules:
            # Weekend rule: priority WEEKENDS, covers Sat-Sun (days 5,6)
            if rule.priority == PRIORITY_WEEKENDS and 5 in rule.get_days_list() and 6 in rule.get_days_list():
                return rule
        return None

    @staticmethod
    def get_rest_schedule():
        """Get the rest/fallback schedule rule.

        Returns:
            Schedule object or None if no such rule exists.
        """
        all_rules = Schedule.get_all()
        for rule in all_rules:
            if rule.priority == PRIORITY_REST:
                return rule
        return None

    @staticmethod
    def set_weekend_emoji(emoji_id, work_end: str = "18:00"):
        """Set or update weekend schedule emoji.

        Creates two rules:
        - Friday evening (work_end - 23:59)
        - Sat-Sun all day

        Args:
            emoji_id: Emoji document ID
            work_end: Work end time (Friday weekend starts at this time)
        """
        # Update or create Friday weekend rule
        friday = Schedule.get_friday_weekend_schedule()
        if friday:
            friday.emoji_id = str(emoji_id)
            friday.time_start = work_end
            friday.save()
        else:
            Schedule.create(
                emoji_id=emoji_id,
                days=[4],  # Friday only
                time_start=work_end,
                time_end="23:59",
                priority=PRIORITY_WEEKENDS,
                name="weekends"
            )

        # Update or create Sat-Sun rule
        weekend = Schedule.get_weekend_schedule()
        if weekend:
            weekend.emoji_id = str(emoji_id)
            weekend.save()
        else:
            Schedule.create(
                emoji_id=emoji_id,
                days=[5, 6],  # Sat-Sun
                time_start="00:00",
                time_end="23:59",
                priority=PRIORITY_WEEKENDS,
                name="weekends"
            )

    @staticmethod
    def set_rest_emoji(emoji_id):
        """Set or update rest/fallback schedule emoji.

        Args:
            emoji_id: Emoji document ID
        """
        rest = Schedule.get_rest_schedule()
        if rest:
            rest.emoji_id = str(emoji_id)
            rest.save()
        else:
            Schedule.create(
                emoji_id=emoji_id,
                days=[0, 1, 2, 3, 4, 5, 6],  # Every day
                time_start="00:00",
                time_end="23:59",
                priority=PRIORITY_REST,
                name="rest"
            )

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


class VipList(Model):
    """
    Model for storing VIP users and chats for urgent notifications.

    VIP users' mentions are always treated as urgent.
    VIP chats have all their mentions treated as urgent.

    Attributes:
        item_type: 'user' or 'chat'
        item_id: username (without @) or chat_id as string
        display_name: Optional display name
    """

    item_type: str
    item_id: str
    display_name: str

    def __init__(self, id: Optional[int] = None):
        Model.__init__(self, id, foreign_keys=True)

    def tablename(self) -> str:
        return 'vip_list'

    def columns(self) -> list[dict[str, str]]:
        return [
            {'name': 'item_type', 'type': 'TEXT'},
            {'name': 'item_id', 'type': 'TEXT'},
            {'name': 'display_name', 'type': 'TEXT'}
        ]

    @staticmethod
    def get_all() -> list['VipList']:
        """Get all VIP entries."""
        return VipList().select(SQL()) or []

    @staticmethod
    def get_users() -> list[str]:
        """Get list of VIP usernames (lowercased)."""
        entries = VipList().select(SQL().WHERE('item_type', '=', 'user')) or []
        return [e.item_id.lower() for e in entries]

    @staticmethod
    def get_chats() -> list[int]:
        """Get list of VIP chat IDs."""
        entries = VipList().select(SQL().WHERE('item_type', '=', 'chat')) or []
        result = []
        for e in entries:
            try:
                result.append(int(e.item_id))
            except ValueError:
                pass
        return result

    @staticmethod
    def add_user(username: str, display_name: str = None) -> 'VipList':
        """Add a VIP user by username."""
        username = username.lower().lstrip('@')
        # Check if already exists
        users = VipList().select(SQL().WHERE('item_type', '=', 'user')) or []
        for u in users:
            if u.item_id == username:
                if display_name:
                    u.display_name = display_name
                    u.save()
                return u

        entry = VipList()
        entry.item_type = 'user'
        entry.item_id = username
        entry.display_name = display_name or ''
        entry.save()
        return entry

    @staticmethod
    def add_chat(chat_id: int, display_name: str = None) -> 'VipList':
        """Add a VIP chat by ID."""
        chat_id_str = str(chat_id)
        # Check if already exists
        chats = VipList().select(SQL().WHERE('item_type', '=', 'chat')) or []
        for c in chats:
            if c.item_id == chat_id_str:
                if display_name:
                    c.display_name = display_name
                    c.save()
                return c

        entry = VipList()
        entry.item_type = 'chat'
        entry.item_id = chat_id_str
        entry.display_name = display_name or ''
        entry.save()
        return entry

    @staticmethod
    def remove(item_id: str) -> bool:
        """Remove a VIP entry by item_id (username or chat_id)."""
        item_id = item_id.lower().lstrip('@')
        entry = VipList().selectOne(SQL().WHERE('item_id', '=', item_id))
        if entry:
            entry.delete()
            return True
        return False

    @staticmethod
    def remove_by_id(entry_id: int) -> bool:
        """Remove a VIP entry by database ID."""
        entries = VipList.get_all()
        for entry in entries:
            if entry.id == entry_id:
                entry.delete()
                return True
        return False

    @staticmethod
    def migrate_from_env(env_usernames: list[str]) -> int:
        """
        Migrate VIP usernames from environment variable to database.

        Args:
            env_usernames: List of usernames from VIP_USERNAMES env var

        Returns:
            Number of users migrated
        """
        count = 0
        for username in env_usernames:
            username = username.strip()
            if username:
                VipList.add_user(username)
                count += 1
        return count


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
