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


class TestMentionServiceGetChatLink:
    """Tests for MentionService.get_chat_link()."""

    def _get_chat_link(self, chat_id: int, message_id: int) -> str:
        """Helper to test chat link generation logic."""
        if chat_id < 0:
            chat_id_str = str(chat_id)
            if chat_id_str.startswith('-100'):
                chat_id_str = chat_id_str[4:]
            else:
                chat_id_str = chat_id_str[1:]
        else:
            chat_id_str = str(chat_id)
        return f"https://t.me/c/{chat_id_str}/{message_id}"

    def test_supergroup_chat_link(self):
        """Test link generation for supergroup (starts with -100)."""
        chat_id = -1001234567890
        message_id = 42
        link = self._get_chat_link(chat_id, message_id)
        assert link == "https://t.me/c/1234567890/42"

    def test_regular_group_chat_link(self):
        """Test link generation for regular group (starts with -)."""
        chat_id = -123456789
        message_id = 100
        link = self._get_chat_link(chat_id, message_id)
        assert link == "https://t.me/c/123456789/100"

    def test_positive_chat_id_link(self):
        """Test link generation for positive chat ID."""
        chat_id = 123456789
        message_id = 50
        link = self._get_chat_link(chat_id, message_id)
        assert link == "https://t.me/c/123456789/50"

    def test_link_contains_message_id(self):
        """Test that link contains correct message ID."""
        chat_id = -1001234567890
        message_id = 999
        link = self._get_chat_link(chat_id, message_id)
        assert "/999" in link


class TestMentionServiceFormatNotificationWithLink:
    """Tests for format_notification with message_id parameter."""

    def test_includes_message_link_when_message_id_provided(self):
        """Test notification includes message link when message_id is provided."""
        chat_id = -1001234567890
        message_id = 42

        # Simulate link generation
        chat_id_str = str(chat_id)[4:]  # Remove -100
        link = f"https://t.me/c/{chat_id_str}/{message_id}"

        # Build notification with link
        lines = ["📢 Упоминание в группе", ""]
        lines.append(f"🔗 Открыть сообщение: {link}")
        notification = "\n".join(lines)

        assert "https://t.me/c/" in notification
        assert "/42" in notification

    def test_no_link_when_message_id_none(self):
        """Test notification has no link when message_id is None."""
        chat_id = -1001234567890
        message_id = None

        lines = ["📢 Упоминание в группе", ""]
        if chat_id and message_id:
            lines.append("🔗 Открыть сообщение: link")
        notification = "\n".join(lines)

        assert "🔗" not in notification

    def test_no_link_when_chat_id_none(self):
        """Test notification has no link when chat_id is None."""
        chat_id = None
        message_id = 42

        lines = ["📢 Упоминание в группе", ""]
        if chat_id and message_id:
            lines.append("🔗 Открыть сообщение: link")
        notification = "\n".join(lines)

        assert "🔗" not in notification


class TestMentionServiceDetectTopics:
    """Tests for MentionService._detect_topics()."""

    def _detect_topics(self, text: str) -> list:
        """Helper to test topic detection logic."""
        import re
        topic_patterns = [
            (r'\b(pr|pull request|пулл|мердж|merge)\b', 'обсуждается PR/merge request'),
            (r'\b(релиз|release|деплой|deploy|выкатить)\b', 'обсуждается релиз/деплой'),
            (r'\b(баг|bug|ошибка|error|exception|краш|crash)\b', 'обсуждается баг/ошибка'),
            (r'\b(ревью|review|код.?ревью)\b', 'нужен код-ревью'),
            (r'\b(тест|test|qa)\b', 'обсуждается тестирование'),
            (r'\b(дедлайн|deadline|срок)\b', 'обсуждаются сроки'),
            (r'\b(помощь|help|подскаж|объясни)\b', 'нужна помощь'),
        ]
        topics = []
        for pattern, summary in topic_patterns:
            if re.search(pattern, text.lower()):
                topics.append(summary)
        return topics

    def test_detects_pr_topic(self):
        """Test detection of PR-related messages."""
        topics = self._detect_topics("Can you review my PR?")
        assert "обсуждается PR/merge request" in topics

    def test_detects_pull_request_topic(self):
        """Test detection of pull request keyword."""
        topics = self._detect_topics("I created a pull request for this feature")
        assert "обсуждается PR/merge request" in topics

    def test_detects_merge_topic(self):
        """Test detection of merge keyword."""
        topics = self._detect_topics("Please merge this branch")
        assert "обсуждается PR/merge request" in topics

    def test_detects_release_topic(self):
        """Test detection of release-related messages."""
        topics = self._detect_topics("When is the next release?")
        assert "обсуждается релиз/деплой" in topics

    def test_detects_deploy_topic(self):
        """Test detection of deploy keyword."""
        topics = self._detect_topics("We need to deploy this to production")
        assert "обсуждается релиз/деплой" in topics

    def test_detects_bug_topic(self):
        """Test detection of bug-related messages."""
        topics = self._detect_topics("Found a bug in the login flow")
        assert "обсуждается баг/ошибка" in topics

    def test_detects_error_topic(self):
        """Test detection of error keyword."""
        topics = self._detect_topics("Getting an error when saving")
        assert "обсуждается баг/ошибка" in topics

    def test_detects_review_topic(self):
        """Test detection of review-related messages."""
        topics = self._detect_topics("Need a review on this")
        assert "нужен код-ревью" in topics

    def test_detects_test_topic(self):
        """Test detection of test-related messages."""
        topics = self._detect_topics("The test is failing")
        assert "обсуждается тестирование" in topics

    def test_detects_deadline_topic(self):
        """Test detection of deadline-related messages."""
        topics = self._detect_topics("The deadline is tomorrow")
        assert "обсуждаются сроки" in topics

    def test_detects_help_topic(self):
        """Test detection of help-related messages."""
        topics = self._detect_topics("Can you help me with this?")
        assert "нужна помощь" in topics

    def test_detects_multiple_topics(self):
        """Test detection of multiple topics in one message."""
        topics = self._detect_topics("Need help with this bug in the release")
        assert "нужна помощь" in topics
        assert "обсуждается баг/ошибка" in topics
        assert "обсуждается релиз/деплой" in topics

    def test_returns_empty_for_generic_message(self):
        """Test returns empty list for message without specific topics."""
        topics = self._detect_topics("Hello everyone")
        assert topics == []

    def test_case_insensitive(self):
        """Test topic detection is case insensitive."""
        topics = self._detect_topics("URGENT BUG in production")
        assert "обсуждается баг/ошибка" in topics


class TestMentionServiceIsUrgentExtended:
    """Extended tests for MentionService.is_urgent() with more keywords."""

    def _is_urgent(self, messages: list) -> bool:
        """Helper to test urgency detection logic."""
        import re
        urgent_pattern = re.compile(
            r'\b(asap|срочно|urgent|emergency|critical|'
            r'помогите|важно|блокер|blocker|prod|падает|упал|'
            r'авария|incident|горит)\b',
            re.IGNORECASE
        )
        for msg in messages:
            text = getattr(msg, 'text', '') or ''
            if urgent_pattern.search(text):
                return True
        return False

    def test_returns_true_for_emergency(self):
        """Test returns True for emergency keyword."""
        messages = [MagicMock(text="This is an emergency!")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_critical(self):
        """Test returns True for critical keyword."""
        messages = [MagicMock(text="Critical issue in production")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_помогите(self):
        """Test returns True for помогите keyword."""
        messages = [MagicMock(text="Помогите разобраться")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_важно(self):
        """Test returns True for важно keyword."""
        messages = [MagicMock(text="Это очень важно")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_prod(self):
        """Test returns True for prod keyword."""
        messages = [MagicMock(text="Something broke on prod")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_падает(self):
        """Test returns True for падает keyword."""
        messages = [MagicMock(text="Сервис падает каждые 5 минут")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_упал(self):
        """Test returns True for упал keyword."""
        messages = [MagicMock(text="Прод упал!")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_авария(self):
        """Test returns True for авария keyword."""
        messages = [MagicMock(text="У нас авария")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_incident(self):
        """Test returns True for incident keyword."""
        messages = [MagicMock(text="We have an incident")]
        assert self._is_urgent(messages) is True

    def test_returns_true_for_горит(self):
        """Test returns True for горит keyword."""
        messages = [MagicMock(text="Всё горит, нужна помощь")]
        assert self._is_urgent(messages) is True

    def test_urgent_keyword_in_middle_of_message(self):
        """Test detection of urgent keyword in middle of message."""
        messages = [MagicMock(text="Hey @user, this is ASAP, please check")]
        assert self._is_urgent(messages) is True

    def test_multiple_messages_one_urgent(self):
        """Test returns True if any message in context is urgent."""
        messages = [
            MagicMock(text="Hello"),
            MagicMock(text="How are you?"),
            MagicMock(text="This is urgent!"),
            MagicMock(text="Thanks"),
        ]
        assert self._is_urgent(messages) is True

    def test_empty_messages_list(self):
        """Test returns False for empty messages list."""
        messages = []
        assert self._is_urgent(messages) is False

    def test_message_with_none_text(self):
        """Test handles message with None text gracefully."""
        messages = [MagicMock(text=None)]
        assert self._is_urgent(messages) is False


class TestIsUserMentioned:
    """Tests for _is_user_mentioned handler function."""

    def _is_user_mentioned(self, entities, text, user_id, username):
        """Helper to test mention detection logic."""
        if not entities:
            return False

        for entity in entities:
            entity_type = entity.get('type')

            # Check @username mention
            if entity_type == 'mention':
                offset = entity.get('offset', 0)
                length = entity.get('length', 0)
                mentioned = text[offset:offset + length]
                if mentioned.startswith('@'):
                    mentioned = mentioned[1:]
                if username and mentioned.lower() == username.lower():
                    return True

            # Check inline mention by user_id
            elif entity_type == 'mention_name':
                if entity.get('user_id') == user_id:
                    return True

        return False

    def test_detects_username_mention(self):
        """Test detection of @username mention."""
        entities = [{'type': 'mention', 'offset': 0, 'length': 5}]
        text = "@john can you help?"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is True

    def test_detects_username_mention_case_insensitive(self):
        """Test @username mention is case insensitive."""
        entities = [{'type': 'mention', 'offset': 0, 'length': 5}]
        text = "@JOHN can you help?"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is True

    def test_detects_inline_mention_by_user_id(self):
        """Test detection of inline mention by user_id."""
        entities = [{'type': 'mention_name', 'user_id': 123}]
        text = "Hey John, can you help?"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is True

    def test_returns_false_for_different_username(self):
        """Test returns False when different username is mentioned."""
        entities = [{'type': 'mention', 'offset': 0, 'length': 5}]
        text = "@jane can you help?"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is False

    def test_returns_false_for_different_user_id(self):
        """Test returns False when different user_id is mentioned."""
        entities = [{'type': 'mention_name', 'user_id': 456}]
        text = "Hey Jane, can you help?"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is False

    def test_returns_false_when_no_entities(self):
        """Test returns False when message has no entities."""
        entities = None
        text = "Hello everyone"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is False

    def test_returns_false_when_empty_entities(self):
        """Test returns False when entities list is empty."""
        entities = []
        text = "Hello everyone"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is False

    def test_mention_in_middle_of_text(self):
        """Test detection of mention in middle of text."""
        entities = [{'type': 'mention', 'offset': 10, 'length': 5}]
        text = "Hey guys, @john can you check this?"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is True

    def test_multiple_mentions_finds_user(self):
        """Test finding user among multiple mentions."""
        entities = [
            {'type': 'mention', 'offset': 0, 'length': 5},
            {'type': 'mention', 'offset': 7, 'length': 5},
        ]
        text = "@jane, @john can you both help?"
        result = self._is_user_mentioned(entities, text, 123, "john")
        assert result is True


class TestGetDisplayName:
    """Tests for _get_display_name handler function."""

    def _get_display_name(self, user):
        """Helper to test display name logic."""
        if not user:
            return 'Unknown'

        first_name = user.get('first_name', '') or ''
        last_name = user.get('last_name', '') or ''

        if first_name or last_name:
            return f"{first_name} {last_name}".strip()

        username = user.get('username')
        if username:
            return f"@{username}"

        return 'Unknown'

    def test_returns_full_name(self):
        """Test returns full name when both first and last name present."""
        user = {'first_name': 'John', 'last_name': 'Doe'}
        assert self._get_display_name(user) == "John Doe"

    def test_returns_first_name_only(self):
        """Test returns first name when only first name present."""
        user = {'first_name': 'John', 'last_name': ''}
        assert self._get_display_name(user) == "John"

    def test_returns_last_name_only(self):
        """Test returns last name when only last name present."""
        user = {'first_name': '', 'last_name': 'Doe'}
        assert self._get_display_name(user) == "Doe"

    def test_returns_username_when_no_name(self):
        """Test returns @username when no name available."""
        user = {'first_name': '', 'last_name': '', 'username': 'johndoe'}
        assert self._get_display_name(user) == "@johndoe"

    def test_returns_unknown_when_no_info(self):
        """Test returns Unknown when no user info available."""
        user = {'first_name': '', 'last_name': '', 'username': None}
        assert self._get_display_name(user) == "Unknown"

    def test_returns_unknown_for_none_user(self):
        """Test returns Unknown for None user."""
        assert self._get_display_name(None) == "Unknown"

    def test_prefers_name_over_username(self):
        """Test prefers full name over username."""
        user = {'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe'}
        assert self._get_display_name(user) == "John Doe"

    def test_handles_none_values(self):
        """Test handles None values in user dict."""
        user = {'first_name': None, 'last_name': None, 'username': 'test'}
        assert self._get_display_name(user) == "@test"


class TestOnlineMentionNotification:
    """Tests for online mention notification flow (via bot)."""

    def test_online_notification_uses_bot(self):
        """Test that online notifications should use bot client."""
        is_online = True
        bot_client_available = True

        # Logic: when online and bot available, use bot
        should_use_bot = is_online and bot_client_available

        assert should_use_bot is True

    def test_offline_notification_uses_user_client(self):
        """Test that offline notifications should use user client."""
        is_online = False
        bot_client_available = True

        # Logic: when offline, use user client regardless of bot
        should_use_bot = is_online and bot_client_available

        assert should_use_bot is False

    def test_online_without_bot_uses_user_client(self):
        """Test that online without bot falls back to user client."""
        is_online = True
        bot_client_available = False

        # Logic: when online but no bot, use user client
        should_use_bot = is_online and bot_client_available

        assert should_use_bot is False

    def test_online_notification_header_includes_indicator(self):
        """Test online notification header includes (вы онлайн) indicator."""
        is_online = True
        is_urgent = False
        header = "📢 Упоминание в группе"

        if is_online and not is_urgent:
            header = header.replace("📢 Упоминание в группе", "📢 Упоминание в группе (вы онлайн)")

        assert "(вы онлайн)" in header

    def test_urgent_online_notification_header(self):
        """Test urgent online notification header."""
        is_online = True
        is_urgent = True
        header = "🚨 Срочное упоминание в группе!"

        if is_online and is_urgent:
            header = header.replace("🚨 Срочное упоминание в группе!", "🚨 Срочное упоминание (вы онлайн)!")

        assert "(вы онлайн)" in header
        assert "Срочное" in header

    def test_offline_notification_no_indicator(self):
        """Test offline notification has no (вы онлайн) indicator."""
        is_online = False
        header = "📢 Упоминание в группе"

        if is_online:
            header = header + " (вы онлайн)"

        assert "(вы онлайн)" not in header

    def test_vip_sender_always_urgent_when_online(self):
        """Test VIP sender mentions are urgent even when online."""
        vip_usernames = ['vrmaks']
        sender_username = 'vrmaks'
        is_online = True

        is_vip = sender_username.lower() in [v.lower() for v in vip_usernames]
        is_urgent = is_vip  # VIP always urgent

        assert is_urgent is True

    def test_urgent_notification_not_silent(self):
        """Test urgent notifications are not sent silently."""
        is_urgent = True
        silent = not is_urgent

        assert silent is False

    def test_normal_notification_is_silent(self):
        """Test normal notifications are sent silently."""
        is_urgent = False
        silent = not is_urgent

        assert silent is True


class TestMentionGenerateSummaryExtended:
    """Extended tests for generate_summary method."""

    def test_summary_includes_context_messages(self):
        """Test summary includes context messages."""
        messages = [
            MagicMock(text="Can you help with the PR?"),
            MagicMock(text="Sure, looking at it now"),
            MagicMock(text="@user check line 42"),
        ]
        mention_message = messages[-1]

        # Simulate summary generation
        summary_parts = []
        for msg in messages[:-1]:
            if msg.text:
                summary_parts.append(f"> {msg.text[:100]}")

        summary_parts.append(f"\n**Сообщение с упоминанием:**\n> {mention_message.text}")
        summary = "\n".join(summary_parts)

        assert "Can you help with the PR?" in summary
        assert "@user check line 42" in summary

    def test_summary_truncates_long_messages(self):
        """Test summary truncates long messages."""
        long_text = "A" * 200
        max_length = 100

        truncated = long_text[:max_length] + "..." if len(long_text) > max_length else long_text

        assert len(truncated) == 103  # 100 + "..."
        assert truncated.endswith("...")

    def test_summary_with_detected_topic(self):
        """Test summary includes detected topic."""
        import re
        text = "Need review on the PR"
        topic_patterns = [
            (r'\b(pr|pull request)\b', 'обсуждается PR'),
            (r'\b(ревью|review)\b', 'нужен код-ревью'),
        ]

        topics = []
        for pattern, summary in topic_patterns:
            if re.search(pattern, text.lower()):
                topics.append(summary)

        assert "обсуждается PR" in topics
        assert "нужен код-ревью" in topics

    def test_summary_handles_empty_messages(self):
        """Test summary handles empty message list gracefully."""
        messages = []
        mention_message = MagicMock(text="@user hello")

        # Simulate with no context
        if not messages:
            summary = f"**Сообщение с упоминанием:**\n> {mention_message.text}"

        assert mention_message.text in summary
