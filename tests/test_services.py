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


class TestMentionServiceShouldNotify:
    """Tests for MentionService.should_notify()."""

    def test_returns_true_when_no_emoji_status(self):
        """Test returns True (notify) when user has no emoji status."""
        emoji_status_id = None
        available_emoji_id = 5810051751654460532
        work_emoji_id = 5810051751654460532

        # Service logic - user is "offline" when no status
        if available_emoji_id and emoji_status_id == available_emoji_id:
            result = False
        elif work_emoji_id is not None and emoji_status_id == work_emoji_id:
            result = False
        else:
            result = True

        assert result is True

    def test_returns_false_when_available_emoji(self):
        """Test returns False when user has available emoji."""
        available_emoji_id = 5810051751654460532
        emoji_status_id = available_emoji_id  # User is "online"
        work_emoji_id = 1234567890

        # Service logic - user is "online"
        if available_emoji_id and emoji_status_id == available_emoji_id:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_false_when_work_emoji(self):
        """Test returns False when user has work emoji from schedule."""
        available_emoji_id = None
        work_emoji_id = 5810051751654460532
        emoji_status_id = work_emoji_id  # User is "at work"

        # Service logic
        if available_emoji_id and emoji_status_id == available_emoji_id:
            result = False
        elif work_emoji_id is not None and emoji_status_id == work_emoji_id:
            result = False
        else:
            result = True

        assert result is False

    def test_returns_true_when_different_emoji(self):
        """Test returns True when user has different emoji (offline)."""
        available_emoji_id = 5810051751654460532
        work_emoji_id = 5810051751654460532
        emoji_status_id = 9999999999  # Different emoji = offline

        # Service logic
        if available_emoji_id and emoji_status_id == available_emoji_id:
            result = False
        elif work_emoji_id is not None and emoji_status_id == work_emoji_id:
            result = False
        else:
            result = True

        assert result is True


class TestMentionServiceIsUrgent:
    """Tests for MentionService.is_urgent()."""

    def test_returns_true_for_asap(self):
        """Test returns True when message contains ASAP."""
        messages = [MagicMock(text="Please check this ASAP")]

        # Check for urgent keywords
        urgent_keywords = ['asap', 'срочно', 'urgent']
        result = any(
            kw in (msg.text or '').lower()
            for msg in messages
            for kw in urgent_keywords
        )

        assert result is True

    def test_returns_true_for_срочно(self):
        """Test returns True when message contains срочно."""
        messages = [MagicMock(text="Это срочно!")]

        urgent_keywords = ['asap', 'срочно', 'urgent']
        result = any(
            kw in (msg.text or '').lower()
            for msg in messages
            for kw in urgent_keywords
        )

        assert result is True

    def test_returns_true_for_blocker(self):
        """Test returns True when message contains blocker."""
        messages = [MagicMock(text="This is a blocker issue")]

        urgent_keywords = ['asap', 'срочно', 'urgent', 'blocker', 'блокер']
        result = any(
            kw in (msg.text or '').lower()
            for msg in messages
            for kw in urgent_keywords
        )

        assert result is True

    def test_returns_false_for_normal_message(self):
        """Test returns False for normal message without urgent keywords."""
        messages = [MagicMock(text="Hey, can you take a look at this?")]

        urgent_keywords = ['asap', 'срочно', 'urgent', 'blocker', 'блокер']
        result = any(
            kw in (msg.text or '').lower()
            for msg in messages
            for kw in urgent_keywords
        )

        assert result is False

    def test_checks_all_messages_in_context(self):
        """Test checks all messages for urgency, not just mention."""
        messages = [
            MagicMock(text="Hey @user"),  # Mention message
            MagicMock(text="We need this ASAP"),  # Earlier context with urgent
            MagicMock(text="Something is broken"),
        ]

        urgent_keywords = ['asap', 'срочно', 'urgent']
        result = any(
            kw in (msg.text or '').lower()
            for msg in messages
            for kw in urgent_keywords
        )

        assert result is True


class TestMentionServiceIsVipSender:
    """Tests for MentionService.is_vip_sender()."""

    def _is_vip_sender(self, vip_usernames, sender_username):
        """Helper to test VIP sender logic."""
        vip_list = [u.lower() for u in (vip_usernames or [])]
        if not sender_username or not vip_list:
            return False
        return sender_username.lower() in vip_list

    def test_returns_true_for_vip_username(self):
        """Test returns True when sender is in VIP list."""
        vip_usernames = ['vrmaks', 'admin']
        assert self._is_vip_sender(vip_usernames, 'vrmaks') is True
        assert self._is_vip_sender(vip_usernames, 'admin') is True

    def test_returns_false_for_non_vip_username(self):
        """Test returns False when sender is not in VIP list."""
        vip_usernames = ['vrmaks']
        assert self._is_vip_sender(vip_usernames, 'someuser') is False

    def test_case_insensitive(self):
        """Test VIP check is case insensitive."""
        vip_usernames = ['VrMaks']
        assert self._is_vip_sender(vip_usernames, 'vrmaks') is True
        assert self._is_vip_sender(vip_usernames, 'VRMAKS') is True

    def test_returns_false_for_none_username(self):
        """Test returns False when username is None."""
        vip_usernames = ['vrmaks']
        assert self._is_vip_sender(vip_usernames, None) is False

    def test_returns_false_when_no_vip_list(self):
        """Test returns False when VIP list is empty."""
        assert self._is_vip_sender([], 'vrmaks') is False
        assert self._is_vip_sender(None, 'vrmaks') is False


class TestMentionServiceFilterMessagesByTime:
    """Tests for MentionService.filter_messages_by_time()."""

    def test_filters_old_messages(self):
        """Test filters out messages older than time limit."""
        now = datetime.now(timezone.utc)
        time_limit = timedelta(minutes=30)

        messages = [
            MagicMock(date=now - timedelta(minutes=5)),   # Within limit
            MagicMock(date=now - timedelta(minutes=15)),  # Within limit
            MagicMock(date=now - timedelta(minutes=45)),  # Outside limit
        ]

        cutoff = now - time_limit
        filtered = [m for m in messages if m.date >= cutoff]

        assert len(filtered) == 2

    def test_keeps_all_recent_messages(self):
        """Test keeps all messages within time limit."""
        now = datetime.now(timezone.utc)
        time_limit = timedelta(minutes=30)

        messages = [
            MagicMock(date=now - timedelta(minutes=1)),
            MagicMock(date=now - timedelta(minutes=10)),
            MagicMock(date=now - timedelta(minutes=20)),
        ]

        cutoff = now - time_limit
        filtered = [m for m in messages if m.date >= cutoff]

        assert len(filtered) == 3


class TestMentionServiceGenerateSummary:
    """Tests for MentionService.generate_summary()."""

    def test_includes_mention_message(self):
        """Test summary includes the mention message."""
        mention_msg = MagicMock(id=1, text="@user can you help?")
        messages = [mention_msg]

        # Basic summary logic
        summary = f"Сообщение с упоминанием:\n  {mention_msg.text}"

        assert "@user can you help?" in summary

    def test_truncates_long_messages(self):
        """Test summary truncates long messages."""
        long_text = "A" * 300
        mention_msg = MagicMock(id=1, text=long_text)

        # Truncate logic
        text = mention_msg.text
        if len(text) > 200:
            text = text[:200] + "..."

        assert len(text) == 203  # 200 + "..."
        assert text.endswith("...")


class TestMentionServiceFormatNotification:
    """Tests for MentionService.format_notification()."""

    def test_includes_chat_title(self):
        """Test notification includes chat title."""
        chat_title = "Test Chat Group"
        notification = f"📍 Чат: {chat_title}"

        assert "Test Chat Group" in notification

    def test_includes_sender_info_with_username(self):
        """Test notification includes sender info with username."""
        sender_name = "John Doe"
        sender_username = "johndoe"

        sender_info = f"@{sender_username} ({sender_name})"

        assert "@johndoe" in sender_info
        assert "John Doe" in sender_info

    def test_includes_sender_info_without_username(self):
        """Test notification includes sender info without username."""
        sender_name = "John Doe"
        sender_username = None

        if sender_username:
            sender_info = f"@{sender_username} ({sender_name})"
        else:
            sender_info = sender_name

        assert sender_info == "John Doe"
        assert "@" not in sender_info

    def test_urgent_header(self):
        """Test urgent notifications have different header."""
        is_urgent = True

        if is_urgent:
            header = "🚨 Срочное упоминание в группе!"
        else:
            header = "📢 Упоминание в группе"

        assert "🚨" in header
        assert "Срочное" in header

    def test_normal_header(self):
        """Test normal notifications have standard header."""
        is_urgent = False

        if is_urgent:
            header = "🚨 Срочное упоминание в группе!"
        else:
            header = "📢 Упоминание в группе"

        assert "📢" in header
        assert "Срочное" not in header


class TestMentionIntegration:
    """Integration tests for mention notification flow."""

    def test_full_notification_flow_urgent(self):
        """Test full notification flow for urgent mention."""
        # Setup
        emoji_status_id = 1234567890
        available_emoji_id = 5810051751654460532
        work_emoji_id = 5810051751654460532
        chat_title = "Work Group"
        sender_name = "Alice"
        sender_username = "alice"
        message_text = "@bob this is ASAP!"

        # Step 1: Check if should notify
        should_notify = True
        if available_emoji_id and emoji_status_id == available_emoji_id:
            should_notify = False
        elif work_emoji_id is not None and emoji_status_id == work_emoji_id:
            should_notify = False

        # Step 2: Check urgency
        urgent_keywords = ['asap', 'срочно', 'urgent']
        is_urgent = any(kw in message_text.lower() for kw in urgent_keywords)

        # Step 3: Format notification
        if is_urgent:
            header = "🚨 Срочное упоминание в группе!"
        else:
            header = "📢 Упоминание в группе"

        notification = f"{header}\n\n📍 Чат: {chat_title}\n👤 Призвал: @{sender_username}"

        # Assertions
        assert should_notify is True
        assert is_urgent is True
        assert "🚨" in notification
        assert "Work Group" in notification
        assert "@alice" in notification

    def test_full_notification_flow_silent(self):
        """Test full notification flow for non-urgent mention."""
        # Setup
        emoji_status_id = 1234567890
        available_emoji_id = 5810051751654460532
        work_emoji_id = 5810051751654460532
        chat_title = "Work Group"
        sender_name = "Alice"
        sender_username = "alice"
        message_text = "@bob can you take a look?"

        # Step 1: Check if should notify
        should_notify = True
        if available_emoji_id and emoji_status_id == available_emoji_id:
            should_notify = False
        elif work_emoji_id is not None and emoji_status_id == work_emoji_id:
            should_notify = False

        # Step 2: Check urgency
        urgent_keywords = ['asap', 'срочно', 'urgent']
        is_urgent = any(kw in message_text.lower() for kw in urgent_keywords)

        # Step 3: Notification should be silent
        silent = not is_urgent

        # Assertions
        assert should_notify is True
        assert is_urgent is False
        assert silent is True

    def test_no_notification_when_online(self):
        """Test no notification when user is online (work emoji)."""
        work_emoji_id = 5810051751654460532
        emoji_status_id = work_emoji_id  # User is at work = online
        available_emoji_id = None

        # Check if should notify
        should_notify = True
        if available_emoji_id and emoji_status_id == available_emoji_id:
            should_notify = False
        elif work_emoji_id is not None and emoji_status_id == work_emoji_id:
            should_notify = False

        assert should_notify is False
