"""
Database models for telegram-assistant.

Uses sqlitemodel ORM for SQLite persistence.
"""
from typing import Optional, Any

from sqlitemodel import Model, Database, SQL
from telethon.extensions import BinaryReader
from telethon.tl.types import Message

# Configure database path (can be overridden by config)
Database.DB_FILE = './storage/database.db'


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
