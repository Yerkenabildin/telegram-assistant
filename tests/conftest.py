"""
Shared pytest fixtures for telegram-assistant tests.

All tests use mocks to avoid requiring actual Telegram/DB dependencies.
"""
import os
import sys
import sqlite3
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Generator

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# Environment Setup - runs before any imports
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables before any imports."""
    os.environ['API_ID'] = '12345'
    os.environ['API_HASH'] = 'test_hash_value'
    os.environ['PERSONAL_TG_LOGIN'] = 'test_user'
    os.environ['AVAILABLE_EMOJI_ID'] = '5810051751654460532'
    os.environ['SECRET_KEY'] = 'test_secret_key_for_sessions'


# ============================================================================
# Database Fixtures (using raw SQLite)
# ============================================================================

@pytest.fixture
def temp_db_path():
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def temp_db_connection(temp_db_path):
    """Create a temporary SQLite database with tables."""
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    # Create replays table (matches models.py)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS replays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emoji TEXT,
            _message TEXT
        )
    ''')

    # Create settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT,
            value TEXT
        )
    ''')

    conn.commit()
    yield conn, temp_db_path
    conn.close()


# ============================================================================
# Mock Models (standalone, no sqlitemodel dependency)
# ============================================================================

class MockReply:
    """Mock Reply model for testing without sqlitemodel."""

    _db = {}  # In-memory storage

    def __init__(self, emoji=None, _message=None):
        self.emoji = emoji
        self._message = _message

    @property
    def message(self):
        """Return mock message object."""
        if self._message:
            msg = MagicMock()
            msg.text = "Mocked reply message"
            return msg
        return None

    @staticmethod
    def create(emoji, msg):
        """Create or update a reply."""
        MockReply._db[str(emoji)] = msg._bytes() if hasattr(msg, '_bytes') else b'mock_bytes'

    @staticmethod
    def get_by_emoji(emoji):
        """Get reply by emoji ID."""
        if str(emoji) in MockReply._db:
            reply = MockReply()
            reply.emoji = str(emoji)
            reply._message = MockReply._db[str(emoji)]
            return reply
        return None

    @staticmethod
    def clear():
        """Clear all stored replies."""
        MockReply._db = {}


class MockSettings:
    """Mock Settings model for testing without sqlitemodel."""

    _db = {}  # In-memory storage

    @staticmethod
    def get(key):
        """Get setting value."""
        return MockSettings._db.get(key)

    @staticmethod
    def set(key, value):
        """Set setting value."""
        MockSettings._db[key] = value

    @staticmethod
    def get_settings_chat_id():
        """Get settings chat ID as integer."""
        value = MockSettings._db.get('settings_chat_id')
        return int(value) if value else None

    @staticmethod
    def set_settings_chat_id(chat_id):
        """Set or clear settings chat ID."""
        if chat_id is None:
            MockSettings._db.pop('settings_chat_id', None)
        else:
            MockSettings._db['settings_chat_id'] = str(chat_id)

    @staticmethod
    def clear():
        """Clear all settings."""
        MockSettings._db = {}


@pytest.fixture
def mock_reply():
    """Provide MockReply and clear before/after test."""
    MockReply.clear()
    yield MockReply
    MockReply.clear()


@pytest.fixture
def mock_settings():
    """Provide MockSettings and clear before/after test."""
    MockSettings.clear()
    yield MockSettings
    MockSettings.clear()


# ============================================================================
# Mock Telethon Client
# ============================================================================

@pytest.fixture
def mock_telegram_client():
    """Create a mock Telegram client for testing."""
    client = MagicMock()
    client.is_connected.return_value = True
    client.is_user_authorized = AsyncMock(return_value=True)
    client.get_me = AsyncMock()
    client.send_message = AsyncMock()
    client.get_messages = AsyncMock(return_value=[])
    client.sign_in = AsyncMock()
    client.send_code_request = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.run_until_disconnected = AsyncMock()
    client.__call__ = AsyncMock()  # For SendReactionRequest

    return client


@pytest.fixture
def mock_user():
    """Create a mock Telegram user."""
    user = MagicMock()
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    user.emoji_status = None
    return user


@pytest.fixture
def mock_user_with_status():
    """Create a mock Telegram user with emoji status."""
    user = MagicMock()
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    user.emoji_status = MagicMock()
    user.emoji_status.document_id = 5379748062124056162
    return user


@pytest.fixture
def mock_message():
    """Create a mock Telegram message."""
    message = MagicMock()
    message.id = 1
    message.text = "Test message"
    message.date = MagicMock()
    message.entities = []
    message._bytes = MagicMock(return_value=b'\x00\x00\x00\x00test_message_bytes')
    return message


@pytest.fixture
def mock_event():
    """Create a mock Telegram event for incoming messages."""
    event = MagicMock()
    event.chat_id = 12345
    event.chat = MagicMock()
    event.chat.id = 12345
    event.is_private = True
    event.message = MagicMock()
    event.message.id = 1
    event.message.text = "Test message"
    event.message.entities = []
    event.input_chat = MagicMock()
    event.reply_to = None
    event.get_sender = AsyncMock()
    return event


@pytest.fixture
def mock_outgoing_event():
    """Create a mock Telegram event for outgoing messages."""
    event = MagicMock()
    event.chat_id = 12345
    event.chat = MagicMock()
    event.chat.id = 12345
    event.message = MagicMock()
    event.message.id = 1
    event.message.text = "/autoreply-settings"
    event.message.entities = []
    event.input_chat = MagicMock()
    event.reply_to = None
    return event


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def sample_emoji_id():
    """Sample custom emoji document ID."""
    return 5379748062124056162


@pytest.fixture
def sample_available_emoji_id():
    """Sample available emoji ID (disables auto-reply)."""
    return 5810051751654460532
