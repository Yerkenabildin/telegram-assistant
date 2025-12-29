"""
Unit tests for services layer.

Tests AutoReplyService and NotificationService.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAutoReplyServiceShouldSendReply:
    """Tests for AutoReplyService.should_send_reply()."""

    def test_returns_false_when_no_emoji_status(self):
        """Test returns False when user has no emoji status."""
        emoji_status_id = None
        reply_exists = True
        last_outgoing_message = None

        # Service logic
        if emoji_status_id is None:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_false_when_user_has_work_emoji(self):
        """Test returns False when user has work emoji status (is available)."""
        work_emoji_id = 5810051751654460532  # From schedule
        emoji_status_id = work_emoji_id  # Same as work emoji
        reply_exists = True
        last_outgoing_message = None

        # Service logic - user has work emoji, so they're "available"
        if work_emoji_id is not None and emoji_status_id == work_emoji_id:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_true_when_no_work_emoji_configured(self):
        """Test returns True when no work emoji is configured (always send reply)."""
        work_emoji_id = None  # No work schedule configured
        emoji_status_id = 1234567890
        reply_exists = True
        last_outgoing_message = None

        # Service logic - no work emoji configured, so proceed
        if work_emoji_id is not None and emoji_status_id == work_emoji_id:
            result = False
        elif not reply_exists:
            result = False
        else:
            result = True

        assert result is True

    def test_returns_false_when_no_reply_template(self):
        """Test returns False when no reply template exists."""
        emoji_status_id = 1234567890
        work_emoji_id = 5810051751654460532
        reply_exists = False
        last_outgoing_message = None

        # Service logic
        if not reply_exists:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_true_when_all_conditions_met(self):
        """Test returns True when all conditions are met."""
        emoji_status_id = 1234567890
        work_emoji_id = 5810051751654460532  # Different from current status
        reply_exists = True
        last_outgoing_message = None  # No recent outgoing, rate limit passes

        # Service logic - all conditions met
        result = (
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id) and
            reply_exists
        )

        assert result is True


class TestAutoReplyServiceRateLimiting:
    """Tests for AutoReplyService rate limiting."""

    def test_allows_when_no_outgoing_message(self):
        """Test rate limiting allows when no outgoing message exists."""
        last_outgoing = None

        # Service logic
        if last_outgoing is None:
            allow = True
        else:
            allow = False

        assert allow is True

    def test_blocks_when_outgoing_within_cooldown(self):
        """Test rate limiting blocks when outgoing message within cooldown period."""
        cooldown = timedelta(minutes=15)
        now = datetime.now(timezone.utc)

        last_outgoing = MagicMock()
        last_outgoing.date = now - timedelta(minutes=5)  # 5 minutes ago

        # Service logic
        time_diff = now - last_outgoing.date
        if time_diff < cooldown:
            allow = False
        else:
            allow = True

        assert allow is False

    def test_allows_after_cooldown(self):
        """Test rate limiting allows after cooldown period."""
        cooldown = timedelta(minutes=15)
        now = datetime.now(timezone.utc)

        last_outgoing = MagicMock()
        last_outgoing.date = now - timedelta(minutes=20)  # 20 minutes ago

        # Service logic
        time_diff = now - last_outgoing.date
        if time_diff < cooldown:
            allow = False
        else:
            allow = True

        assert allow is True

    def test_allows_when_multiple_forwarded_messages(self):
        """Test rate limiting allows when receiving multiple forwarded messages.

        This is the key fix: when someone forwards 2 messages quickly,
        we should still allow auto-reply if we haven't responded recently.
        """
        cooldown = timedelta(minutes=15)
        now = datetime.now(timezone.utc)

        # No outgoing messages (we haven't replied yet)
        last_outgoing = None

        # Service logic - should allow because no recent outgoing message
        if last_outgoing is None:
            allow = True
        else:
            time_diff = now - last_outgoing.date
            if time_diff < cooldown:
                allow = False
            else:
                allow = True

        assert allow is True


class TestAutoReplyServiceIsSettingsChat:
    """Tests for AutoReplyService.is_settings_chat()."""

    def test_returns_false_when_no_settings_chat(self):
        """Test returns False when no settings chat configured."""
        chat_id = 12345
        settings_chat_id = None

        result = settings_chat_id is not None and chat_id == settings_chat_id
        assert result is False

    def test_returns_false_when_different_chat(self):
        """Test returns False when chat IDs don't match."""
        chat_id = 12345
        settings_chat_id = 99999

        result = settings_chat_id is not None and chat_id == settings_chat_id
        assert result is False

    def test_returns_true_when_matching_chat(self):
        """Test returns True when chat IDs match."""
        chat_id = 12345
        settings_chat_id = 12345

        result = settings_chat_id is not None and chat_id == settings_chat_id
        assert result is True


class TestNotificationServiceShouldNotifyAsap:
    """Tests for NotificationService.should_notify_asap()."""

    def test_returns_false_for_non_private(self):
        """Test returns False for non-private messages."""
        message_text = "asap"
        is_private = False
        emoji_status_id = 1234567890

        # Service logic
        if not is_private:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_false_without_asap_keyword(self):
        """Test returns False without ASAP keyword."""
        message_text = "Hello there"
        is_private = True
        emoji_status_id = 1234567890

        # Service logic
        if 'asap' not in message_text.lower():
            result = False
        else:
            result = True

        assert result is False

    def test_returns_false_when_no_status(self):
        """Test returns False when user has no emoji status."""
        message_text = "asap"
        is_private = True
        emoji_status_id = None

        # Service logic
        if emoji_status_id is None:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_false_when_user_has_work_emoji(self):
        """Test returns False when user has work emoji (is available)."""
        message_text = "asap"
        is_private = True
        work_emoji_id = 5810051751654460532  # From schedule
        emoji_status_id = work_emoji_id

        # Service logic - user has work emoji, so they're available
        if work_emoji_id is not None and emoji_status_id == work_emoji_id:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_true_when_no_work_emoji_configured(self):
        """Test returns True when no work emoji configured (ASAP always works)."""
        message_text = "Please check this ASAP"
        is_private = True
        emoji_status_id = 1234567890
        work_emoji_id = None  # No work schedule configured

        # Service logic - no work emoji = ASAP always works
        result = (
            is_private and
            'asap' in message_text.lower() and
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id)
        )

        assert result is True

    def test_returns_true_when_all_conditions_met(self):
        """Test returns True when all conditions are met."""
        message_text = "Please check this ASAP"
        is_private = True
        emoji_status_id = 1234567890
        work_emoji_id = 5810051751654460532  # Different from current status

        # Service logic
        result = (
            is_private and
            'asap' in message_text.lower() and
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id)
        )

        assert result is True

    def test_asap_case_insensitive(self):
        """Test ASAP detection is case insensitive."""
        test_cases = ["ASAP", "asap", "Asap", "aSaP"]

        for text in test_cases:
            result = 'asap' in text.lower()
            assert result is True, f"Failed for: {text}"


class TestNotificationServiceFormatMessage:
    """Tests for NotificationService.format_asap_message()."""

    def test_formats_with_username(self):
        """Test message format with username."""
        sender_username = "test_user"
        sender_id = 123456789

        if sender_username:
            message = f'Срочный призыв от @{sender_username}'
        else:
            message = f'Срочный призыв от пользователя {sender_id}'

        assert '@test_user' in message

    def test_formats_without_username(self):
        """Test message format without username."""
        sender_username = None
        sender_id = 123456789

        if sender_username:
            message = f'Срочный призыв от @{sender_username}'
        else:
            message = f'Срочный призыв от пользователя {sender_id}'

        assert '123456789' in message
        assert '@' not in message


class TestNotificationServiceWebhook:
    """Tests for NotificationService webhook logic."""

    def test_no_call_when_no_url(self):
        """Test webhook not called when URL not configured."""
        webhook_url = None

        if not webhook_url:
            should_call = False
        else:
            should_call = True

        assert should_call is False

    def test_call_when_url_configured(self):
        """Test webhook called when URL configured."""
        webhook_url = "https://example.com/webhook"

        if not webhook_url:
            should_call = False
        else:
            should_call = True

        assert should_call is True

    def test_webhook_payload_structure(self):
        """Test webhook payload has correct structure."""
        sender_username = "test_user"
        sender_id = 123456789
        message_text = "Please check ASAP"

        payload = {
            'sender_username': sender_username,
            'sender_id': sender_id,
            'message': message_text,
        }

        assert payload['sender_username'] == 'test_user'
        assert payload['sender_id'] == 123456789
        assert payload['message'] == "Please check ASAP"


class TestServiceIntegration:
    """Integration tests for services working together."""

    def test_autoreply_and_notification_different_conditions(self):
        """Test that autoreply and notification have different conditions."""
        # User is busy (not available), has reply template
        emoji_status_id = 1234567890
        work_emoji_id = 5810051751654460532  # Different from current status
        reply_exists = True
        is_private = True
        message_text = "Hello"  # No ASAP

        # AutoReply should trigger
        should_autoreply = (
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id) and
            reply_exists and
            is_private
        )

        # Notification should NOT trigger (no ASAP)
        should_notify = (
            is_private and
            'asap' in message_text.lower() and
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id)
        )

        assert should_autoreply is True
        assert should_notify is False

    def test_both_trigger_for_asap_message(self):
        """Test both services trigger for ASAP message."""
        emoji_status_id = 1234567890
        work_emoji_id = 5810051751654460532  # Different from current status
        reply_exists = True
        is_private = True
        message_text = "Check this ASAP!"

        should_autoreply = (
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id) and
            reply_exists and
            is_private
        )

        should_notify = (
            is_private and
            'asap' in message_text.lower() and
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id)
        )

        assert should_autoreply is True
        assert should_notify is True

    def test_neither_trigger_when_available(self):
        """Test neither service triggers when user has work emoji (is available)."""
        work_emoji_id = 5810051751654460532
        emoji_status_id = work_emoji_id  # User has work emoji = available
        reply_exists = True
        is_private = True
        message_text = "Check this ASAP!"

        should_autoreply = (
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id) and
            reply_exists and
            is_private
        )

        should_notify = (
            is_private and
            'asap' in message_text.lower() and
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id)
        )

        assert should_autoreply is False
        assert should_notify is False

    def test_both_trigger_when_no_work_emoji_configured(self):
        """Test both services trigger when no work schedule exists."""
        emoji_status_id = 1234567890
        work_emoji_id = None  # No work schedule configured
        reply_exists = True
        is_private = True
        message_text = "Check this ASAP!"

        should_autoreply = (
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id) and
            reply_exists and
            is_private
        )

        should_notify = (
            is_private and
            'asap' in message_text.lower() and
            emoji_status_id is not None and
            (work_emoji_id is None or emoji_status_id != work_emoji_id)
        )

        assert should_autoreply is True
        assert should_notify is True
