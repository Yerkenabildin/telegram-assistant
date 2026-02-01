"""
Unit tests for models.py logic using mock models.

These tests validate the model behavior patterns without requiring
actual sqlitemodel/telethon dependencies.
"""
import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMockReply:
    """Tests for Reply model behavior using MockReply."""

    def test_create_new_reply(self, mock_reply, mock_message):
        """Test creating a new reply mapping."""
        emoji_id = "12345"

        mock_reply.create(emoji_id, mock_message)

        result = mock_reply.get_by_emoji(emoji_id)
        assert result is not None
        assert result.emoji == emoji_id

    def test_update_existing_reply(self, mock_reply, mock_message):
        """Test updating an existing reply mapping (upsert behavior)."""
        emoji_id = "12345"

        # Create first
        mock_reply.create(emoji_id, mock_message)

        # Update (create with same emoji)
        mock_reply.create(emoji_id, mock_message)

        result = mock_reply.get_by_emoji(emoji_id)
        assert result is not None

    def test_get_nonexistent_reply(self, mock_reply):
        """Test getting a reply for non-existent emoji returns None."""
        result = mock_reply.get_by_emoji("nonexistent")
        assert result is None

    def test_create_with_integer_emoji(self, mock_reply, mock_message, sample_emoji_id):
        """Test creating reply with integer emoji ID."""
        mock_reply.create(sample_emoji_id, mock_message)

        result = mock_reply.get_by_emoji(sample_emoji_id)
        assert result is not None

    def test_multiple_replies(self, mock_reply, mock_message):
        """Test storing multiple different emoji replies."""
        emojis = ["emoji1", "emoji2", "emoji3"]

        for emoji in emojis:
            mock_reply.create(emoji, mock_message)

        for emoji in emojis:
            result = mock_reply.get_by_emoji(emoji)
            assert result is not None
            assert result.emoji == emoji

    def test_message_property_returns_object(self, mock_reply, mock_message):
        """Test that message property returns a message-like object."""
        mock_reply.create("test", mock_message)
        result = mock_reply.get_by_emoji("test")

        # message property should return something with text
        assert result.message is not None
        assert hasattr(result.message, 'text')


class TestMockSettings:
    """Tests for Settings model behavior using MockSettings."""

    def test_set_and_get_value(self, mock_settings):
        """Test setting and getting a value."""
        mock_settings.set('test_key', 'test_value')

        result = mock_settings.get('test_key')
        assert result == 'test_value'

    def test_get_nonexistent_key(self, mock_settings):
        """Test getting a non-existent key returns None."""
        result = mock_settings.get('nonexistent_key')
        assert result is None

    def test_update_existing_value(self, mock_settings):
        """Test updating an existing setting."""
        mock_settings.set('key', 'value1')
        mock_settings.set('key', 'value2')

        result = mock_settings.get('key')
        assert result == 'value2'

    def test_set_settings_chat_id(self, mock_settings):
        """Test setting settings_chat_id."""
        chat_id = 123456789
        mock_settings.set_settings_chat_id(chat_id)

        result = mock_settings.get_settings_chat_id()
        assert result == chat_id

    def test_get_settings_chat_id_not_set(self, mock_settings):
        """Test getting settings_chat_id when not set returns None."""
        result = mock_settings.get_settings_chat_id()
        assert result is None

    def test_clear_settings_chat_id(self, mock_settings):
        """Test clearing settings_chat_id by setting to None."""
        # First set a value
        mock_settings.set_settings_chat_id(123456789)
        assert mock_settings.get_settings_chat_id() == 123456789

        # Clear it
        mock_settings.set_settings_chat_id(None)
        assert mock_settings.get_settings_chat_id() is None

    def test_settings_chat_id_returns_int(self, mock_settings):
        """Test that get_settings_chat_id returns an integer."""
        chat_id = 987654321
        mock_settings.set_settings_chat_id(chat_id)

        result = mock_settings.get_settings_chat_id()
        assert isinstance(result, int)
        assert result == chat_id

    def test_multiple_settings(self, mock_settings):
        """Test storing multiple settings."""
        mock_settings.set('key1', 'value1')
        mock_settings.set('key2', 'value2')
        mock_settings.set('key3', 'value3')

        assert mock_settings.get('key1') == 'value1'
        assert mock_settings.get('key2') == 'value2'
        assert mock_settings.get('key3') == 'value3'


class TestDatabaseFixtureIsolation:
    """Tests to verify fixture isolation between tests."""

    def test_mock_reply_isolation_a(self, mock_reply, mock_message):
        """First test - creates a reply."""
        mock_reply.create("isolation_test", mock_message)
        assert mock_reply.get_by_emoji("isolation_test") is not None

    def test_mock_reply_isolation_b(self, mock_reply):
        """Second test - should not see data from first test."""
        # This should be None because fixtures clean up between tests
        result = mock_reply.get_by_emoji("isolation_test")
        assert result is None

    def test_mock_settings_isolation_a(self, mock_settings):
        """First test - sets a setting."""
        mock_settings.set_settings_chat_id(99999)
        assert mock_settings.get_settings_chat_id() == 99999

    def test_mock_settings_isolation_b(self, mock_settings):
        """Second test - should not see data from first test."""
        result = mock_settings.get_settings_chat_id()
        assert result is None


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_emoji_string(self, mock_reply, mock_message):
        """Test handling of empty emoji string."""
        mock_reply.create("", mock_message)
        result = mock_reply.get_by_emoji("")
        assert result is not None

    def test_very_long_emoji_id(self, mock_reply, mock_message):
        """Test handling of very long emoji ID."""
        long_id = "1" * 100
        mock_reply.create(long_id, mock_message)
        result = mock_reply.get_by_emoji(long_id)
        assert result is not None

    def test_special_characters_in_settings_value(self, mock_settings):
        """Test handling of special characters in settings values."""
        special_value = "test\n\t\"'special<>&chars"
        mock_settings.set('special', special_value)
        assert mock_settings.get('special') == special_value

    def test_unicode_in_settings(self, mock_settings):
        """Test handling of unicode in settings."""
        unicode_value = "тест 测试"
        mock_settings.set('unicode', unicode_value)
        assert mock_settings.get('unicode') == unicode_value

    def test_numeric_string_emoji(self, mock_reply, mock_message):
        """Test handling of numeric string as emoji ID."""
        mock_reply.create("5379748062124056162", mock_message)
        result = mock_reply.get_by_emoji("5379748062124056162")
        assert result is not None


class TestMockSettingsPersonalChat:
    """Tests for personal chat settings."""

    def test_set_and_get_personal_chat_id(self, mock_settings):
        """Test setting and getting personal chat ID."""
        chat_id = 123456789
        mock_settings.set_personal_chat_id(chat_id)

        result = mock_settings.get_personal_chat_id()
        assert result == chat_id

    def test_get_personal_chat_id_not_set(self, mock_settings):
        """Test getting personal chat ID when not set returns None."""
        result = mock_settings.get_personal_chat_id()
        assert result is None

    def test_clear_personal_chat_id(self, mock_settings):
        """Test clearing personal chat ID by setting to None."""
        mock_settings.set_personal_chat_id(123456789)
        assert mock_settings.get_personal_chat_id() == 123456789

        mock_settings.set_personal_chat_id(None)
        assert mock_settings.get_personal_chat_id() is None

    def test_personal_chat_id_returns_int(self, mock_settings):
        """Test that get_personal_chat_id returns an integer."""
        chat_id = 987654321
        mock_settings.set_personal_chat_id(chat_id)

        result = mock_settings.get_personal_chat_id()
        assert isinstance(result, int)
        assert result == chat_id

    def test_personal_chat_id_negative_id(self, mock_settings):
        """Test handling negative chat ID (group chats)."""
        chat_id = -1001234567890
        mock_settings.set_personal_chat_id(chat_id)

        result = mock_settings.get_personal_chat_id()
        assert result == chat_id


class TestMockSettingsAsap:
    """Tests for ASAP notification settings."""

    def test_asap_enabled_default_true(self, mock_settings):
        """Test ASAP notifications are enabled by default."""
        result = mock_settings.is_asap_enabled()
        assert result is True

    def test_disable_asap(self, mock_settings):
        """Test disabling ASAP notifications."""
        mock_settings.set_asap_enabled(False)

        result = mock_settings.is_asap_enabled()
        assert result is False

    def test_enable_asap(self, mock_settings):
        """Test enabling ASAP notifications."""
        mock_settings.set_asap_enabled(False)
        assert mock_settings.is_asap_enabled() is False

        mock_settings.set_asap_enabled(True)
        assert mock_settings.is_asap_enabled() is True

    def test_set_and_get_webhook_url(self, mock_settings):
        """Test setting and getting webhook URL."""
        url = "https://example.com/webhook"
        mock_settings.set_asap_webhook_url(url)

        result = mock_settings.get_asap_webhook_url()
        assert result == url

    def test_get_webhook_url_not_set(self, mock_settings):
        """Test getting webhook URL when not set returns None."""
        result = mock_settings.get_asap_webhook_url()
        assert result is None

    def test_clear_webhook_url(self, mock_settings):
        """Test clearing webhook URL by setting to None."""
        mock_settings.set_asap_webhook_url("https://example.com/webhook")
        assert mock_settings.get_asap_webhook_url() is not None

        mock_settings.set_asap_webhook_url(None)
        assert mock_settings.get_asap_webhook_url() is None

    def test_webhook_url_with_query_params(self, mock_settings):
        """Test webhook URL with query parameters."""
        url = "https://example.com/webhook?token=abc123&channel=alerts"
        mock_settings.set_asap_webhook_url(url)

        result = mock_settings.get_asap_webhook_url()
        assert result == url

    def test_asap_settings_isolation(self, mock_settings):
        """Test that ASAP settings are properly isolated."""
        # Set all ASAP-related settings
        mock_settings.set_personal_chat_id(111111)
        mock_settings.set_asap_enabled(False)
        mock_settings.set_asap_webhook_url("https://test.com")

        # Verify all are set correctly
        assert mock_settings.get_personal_chat_id() == 111111
        assert mock_settings.is_asap_enabled() is False
        assert mock_settings.get_asap_webhook_url() == "https://test.com"

        # Clear all
        mock_settings.set_personal_chat_id(None)
        mock_settings.set_asap_enabled(True)
        mock_settings.set_asap_webhook_url(None)

        # Verify all are cleared/reset
        assert mock_settings.get_personal_chat_id() is None
        assert mock_settings.is_asap_enabled() is True
        assert mock_settings.get_asap_webhook_url() is None


class TestAsapNotificationLogic:
    """Tests for ASAP notification decision logic."""

    def test_should_notify_when_enabled_and_has_asap(self, mock_settings):
        """Test notification triggered when ASAP enabled and message contains ASAP."""
        mock_settings.set_asap_enabled(True)
        mock_settings.set_personal_chat_id(123456789)

        is_enabled = mock_settings.is_asap_enabled()
        has_target = mock_settings.get_personal_chat_id() is not None
        message_text = "Please check this ASAP"

        should_notify = (
            is_enabled and
            has_target and
            'asap' in message_text.lower()
        )

        assert should_notify is True

    def test_should_not_notify_when_disabled(self, mock_settings):
        """Test notification not triggered when ASAP disabled."""
        mock_settings.set_asap_enabled(False)
        mock_settings.set_personal_chat_id(123456789)

        is_enabled = mock_settings.is_asap_enabled()
        has_target = mock_settings.get_personal_chat_id() is not None
        message_text = "Please check this ASAP"

        should_notify = (
            is_enabled and
            has_target and
            'asap' in message_text.lower()
        )

        assert should_notify is False

    def test_should_not_notify_without_personal_chat(self, mock_settings):
        """Test notification not triggered without personal chat configured."""
        mock_settings.set_asap_enabled(True)
        # Personal chat not set

        is_enabled = mock_settings.is_asap_enabled()
        has_target = mock_settings.get_personal_chat_id() is not None
        message_text = "Please check this ASAP"

        should_notify = (
            is_enabled and
            has_target and
            'asap' in message_text.lower()
        )

        assert should_notify is False

    def test_should_not_notify_without_asap_keyword(self, mock_settings):
        """Test notification not triggered without ASAP keyword."""
        mock_settings.set_asap_enabled(True)
        mock_settings.set_personal_chat_id(123456789)

        is_enabled = mock_settings.is_asap_enabled()
        has_target = mock_settings.get_personal_chat_id() is not None
        message_text = "Please check this when you have time"

        should_notify = (
            is_enabled and
            has_target and
            'asap' in message_text.lower()
        )

        assert should_notify is False
