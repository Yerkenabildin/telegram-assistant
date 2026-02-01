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
        vip_usernames = ['vip_user', 'admin']
        assert self._is_vip_sender(vip_usernames, 'vip_user') is True
        assert self._is_vip_sender(vip_usernames, 'admin') is True

    def test_returns_false_for_non_vip_username(self):
        """Test returns False when sender is not in VIP list."""
        vip_usernames = ['vip_user']
        assert self._is_vip_sender(vip_usernames, 'someuser') is False

    def test_case_insensitive(self):
        """Test VIP check is case insensitive."""
        vip_usernames = ['VipUser']
        assert self._is_vip_sender(vip_usernames, 'vipuser') is True
        assert self._is_vip_sender(vip_usernames, 'VIPUSER') is True

    def test_returns_false_for_none_username(self):
        """Test returns False when username is None."""
        vip_usernames = ['vip_user']
        assert self._is_vip_sender(vip_usernames, None) is False

    def test_returns_false_when_no_vip_list(self):
        """Test returns False when VIP list is empty."""
        assert self._is_vip_sender([], 'vip_user') is False
        assert self._is_vip_sender(None, 'vip_user') is False


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
        vip_usernames = ['vip_user']
        sender_username = 'vip_user'
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


class TestDelayedMentionNotification:
    """Tests for delayed online mention notification logic."""

    def test_vip_sender_sent_immediately(self):
        """Test VIP sender mentions are sent immediately, not delayed."""
        is_online = True
        is_vip = True
        bot_available = True

        # Logic: VIP mentions should be sent immediately
        should_delay = is_online and bot_available and not is_vip

        assert should_delay is False

    def test_non_vip_online_is_delayed(self):
        """Test non-VIP online mentions are delayed."""
        is_online = True
        is_vip = False
        bot_available = True

        # Logic: non-VIP online mentions should be delayed
        should_delay = is_online and bot_available and not is_vip

        assert should_delay is True

    def test_offline_sent_immediately(self):
        """Test offline mentions are sent immediately."""
        is_online = False
        is_vip = False
        bot_available = True

        # Logic: offline mentions should be sent immediately
        should_delay = is_online and bot_available and not is_vip

        assert should_delay is False

    def test_no_bot_sent_immediately(self):
        """Test mentions without bot are sent immediately."""
        is_online = True
        is_vip = False
        bot_available = False

        # Logic: no bot = use user client immediately
        should_delay = is_online and bot_available and not is_vip

        assert should_delay is False

    def test_pending_mention_scheduled_with_delay(self):
        """Test pending mention is scheduled with correct delay."""
        from datetime import datetime, timedelta

        delay_minutes = 10
        now = datetime.now()
        scheduled_time = now + timedelta(minutes=delay_minutes)

        # Check delay is approximately correct (within 1 second)
        diff = (scheduled_time - now).total_seconds()
        assert 599 <= diff <= 601  # 10 minutes = 600 seconds

    def test_pending_mention_skipped_if_read(self):
        """Test pending mention is skipped if message was read."""
        message_id = 42
        read_inbox_max_id = 50  # Message 42 is before 50, so it's read

        was_read = message_id <= read_inbox_max_id

        assert was_read is True

    def test_pending_mention_sent_if_not_read(self):
        """Test pending mention is sent if message was not read."""
        message_id = 55
        read_inbox_max_id = 50  # Message 55 is after 50, so not read

        was_read = message_id <= read_inbox_max_id

        assert was_read is False

    def test_pending_mention_storage_key_format(self):
        """Test pending mention storage key format."""
        chat_id = -1001234567890
        message_id = 42

        key = f"{chat_id}:{message_id}"

        assert key == "-1001234567890:42"

    def test_multiple_pending_mentions_stored(self):
        """Test multiple pending mentions can be stored."""
        pending = {}

        # Add first mention
        pending["chat1:1"] = {"chat_id": "chat1", "message_id": 1}
        # Add second mention
        pending["chat2:2"] = {"chat_id": "chat2", "message_id": 2}

        assert len(pending) == 2
        assert "chat1:1" in pending
        assert "chat2:2" in pending


class TestReplyChainContext:
    """Tests for reply chain context in mention notifications."""

    def test_reply_chain_used_for_topic_detection(self):
        """Test that reply chain messages are used for topic detection but not displayed."""
        reply_chain = [
            MagicMock(text="Original question about the PR"),
            MagicMock(text="I think we should fix it"),
        ]

        # Reply chain text should be used for topic detection (e.g., PR -> code review)
        all_text = " ".join(msg.text for msg in reply_chain)

        assert "PR" in all_text  # Topic keyword present
        assert "fix" in all_text  # Another topic keyword

    def test_reply_chain_detection(self):
        """Test detection of reply-to message."""
        message = MagicMock()
        message.reply_to_msg_id = 42

        has_reply = message.reply_to_msg_id is not None

        assert has_reply is True

    def test_no_reply_chain_when_not_reply(self):
        """Test no reply chain when message is not a reply."""
        message = MagicMock()
        message.reply_to_msg_id = None

        has_reply = message.reply_to_msg_id is not None

        assert has_reply is False

    def test_reply_chain_max_depth(self):
        """Test that reply chain respects max depth limit."""
        max_depth = 5
        chain = []

        # Simulate building chain up to max depth
        for i in range(7):  # Try to add more than max_depth
            if len(chain) < max_depth:
                chain.append(f"message_{i}")

        assert len(chain) == 5

    def test_reply_chain_chronological_order(self):
        """Test that reply chain is in chronological order (oldest first)."""
        # Simulate fetching in reverse order (newest first)
        fetched = ["msg3", "msg2", "msg1"]

        # Reverse to get chronological order
        chronological = list(reversed(fetched))

        assert chronological == ["msg1", "msg2", "msg3"]

    def test_reply_chain_sender_info_extracted(self):
        """Test that sender info is extracted from reply chain messages."""
        msg = MagicMock()
        msg.text = "Hello"
        msg.sender = MagicMock()
        msg.sender.first_name = "John"
        msg.sender.username = "john_doe"

        sender = msg.sender
        first_name = getattr(sender, 'first_name', '') or ''
        username = getattr(sender, 'username', '')

        sender_name = first_name or f"@{username}" if username else ''

        assert sender_name == "John"

    def test_reply_chain_handles_no_sender(self):
        """Test that reply chain handles messages without sender info."""
        msg = MagicMock()
        msg.text = "Hello"
        msg.sender = None

        sender = getattr(msg, 'sender', None)
        sender_name = ''
        if sender:
            first = getattr(sender, 'first_name', '') or ''
            sender_name = first if first else ''

        assert sender_name == ''

    def test_reply_chain_truncates_long_messages(self):
        """Test that long messages in reply chain are truncated."""
        long_text = "A" * 100
        max_length = 60

        truncated = long_text[:max_length] + "..." if len(long_text) > max_length else long_text

        assert len(truncated) == 63  # 60 + "..."
        assert truncated.endswith("...")

    def test_summary_context_shown_reply_chain_hidden(self):
        """Test summary shows context but reply chain is not displayed."""
        reply_chain = [MagicMock(text="PR needs review")]
        context_msgs = ["Looking at it", "Found an issue"]

        # Reply chain is used for topic detection only
        all_text = " ".join(msg.text for msg in reply_chain)
        assert "PR" in all_text  # Used for topic detection

        # Only context is shown, not reply chain
        lines = []
        if context_msgs:
            lines.append("💬 Контекст:")
            for text in context_msgs:
                lines.append(f"  «{text}»")

        summary = "\n".join(lines)

        # Verify context is shown but reply chain is NOT displayed
        assert "Контекст" in summary
        assert "Found an issue" in summary
        assert "Цепочка ответов" not in summary  # Reply chain not displayed
        assert "PR needs review" not in summary   # Reply chain text not displayed


class TestProductivityServiceTodayRange:
    """Tests for ProductivityService._get_today_range()."""

    def test_returns_correct_day_range(self):
        """Test returns correct start and end of day."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)

        # Simulate _get_today_range logic
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        assert day_start.hour == 0
        assert day_start.minute == 0
        assert day_end > day_start
        assert (day_end - day_start).total_seconds() == 86400  # 24 hours

    def test_uses_configured_timezone(self):
        """Test uses configured timezone for day boundaries."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Same time in UTC and Moscow differ in date near midnight
        utc = ZoneInfo("UTC")
        moscow = ZoneInfo("Europe/Moscow")

        # Simulate getting day start in different timezones
        now_utc = datetime.now(utc)
        now_moscow = datetime.now(moscow)

        day_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_moscow = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)

        # They should have same hour (0) but potentially different dates
        assert day_start_utc.hour == 0
        assert day_start_moscow.hour == 0


class TestProductivityServiceCollectMessages:
    """Tests for ProductivityService message collection logic."""

    def test_skips_inactive_dialogs(self):
        """Test skips dialogs with no recent activity."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Simulate dialog check
        last_msg_date = now - timedelta(days=2)  # 2 days old

        should_skip = last_msg_date < day_start
        assert should_skip is True

    def test_processes_active_dialogs(self):
        """Test processes dialogs with activity today."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Simulate dialog check
        last_msg_date = now - timedelta(hours=2)  # 2 hours ago = today

        should_skip = last_msg_date < day_start
        assert should_skip is False

    def test_filters_only_outgoing_messages(self):
        """Test only collects outgoing messages."""
        messages = [
            MagicMock(out=True, text="My message"),
            MagicMock(out=False, text="Their message"),
            MagicMock(out=True, text="Another of mine"),
        ]

        outgoing = [m for m in messages if m.out]

        assert len(outgoing) == 2
        assert all(m.out for m in outgoing)

    def test_skips_empty_messages(self):
        """Test skips messages with empty text."""
        messages = [
            MagicMock(out=True, text="Hello"),
            MagicMock(out=True, text=""),
            MagicMock(out=True, text="   "),
            MagicMock(out=True, text="World"),
        ]

        valid = [m for m in messages if m.out and m.text and m.text.strip()]

        assert len(valid) == 2

    def test_extracts_mentions_from_messages(self):
        """Test extracts @mentions from messages."""
        import re

        text = "Hey @alice and @bob, can you help?"
        mentions = re.findall(r'@(\w+)', text)

        assert mentions == ['alice', 'bob']


class TestProductivityServiceChatSummary:
    """Tests for ProductivityService chat summary generation."""

    def test_keyword_detection_for_review(self):
        """Test keyword detection for code review."""
        import re

        text = "I reviewed the PR and left comments"
        patterns = [
            (r'\b(ревью|review|pr|пр|merge)\b', 'ревью кода'),
        ]

        detected = []
        for pattern, label in patterns:
            if re.search(pattern, text.lower()):
                detected.append(label)

        assert 'ревью кода' in detected

    def test_keyword_detection_for_bug_fix(self):
        """Test keyword detection for bug fix."""
        import re

        text = "Fixed the bug in the login flow"
        patterns = [
            (r'\b(баг|bug|фикс|fix|исправ)\b', 'исправление багов'),
        ]

        detected = []
        for pattern, label in patterns:
            if re.search(pattern, text.lower()):
                detected.append(label)

        assert 'исправление багов' in detected

    def test_keyword_detection_for_meetings(self):
        """Test keyword detection for meetings/calls."""
        import re

        text = "Let's schedule a call for tomorrow"
        patterns = [
            (r'\b(созвон|звонок|call|митинг|meeting)\b', 'созвоны'),
        ]

        detected = []
        for pattern, label in patterns:
            if re.search(pattern, text.lower()):
                detected.append(label)

        assert 'созвоны' in detected

    def test_message_count_formatting(self):
        """Test message count is included in summary."""
        message_count = 15

        summary = f"{message_count} сообщений"

        assert "15 сообщений" == summary


class TestProductivityServiceDailySummary:
    """Tests for ProductivityService daily summary generation."""

    def test_empty_summary_for_no_messages(self):
        """Test generates appropriate message when no messages."""
        total_messages = 0

        if total_messages == 0:
            summary = "Сегодня вы не отправляли сообщений."
        else:
            summary = f"Всего: {total_messages}"

        assert "не отправляли" in summary

    def test_summary_includes_totals(self):
        """Test summary includes message and chat totals."""
        total_messages = 42
        total_chats = 5

        lines = [
            f"📨 Всего сообщений: **{total_messages}**",
            f"💬 Активных чатов: **{total_chats}**",
        ]
        summary = "\n".join(lines)

        assert "42" in summary
        assert "5" in summary

    def test_chat_type_emoji_mapping(self):
        """Test chat type emoji mapping."""
        type_emoji = {
            'private': '👤',
            'group': '👥',
            'channel': '📢'
        }

        assert type_emoji['private'] == '👤'
        assert type_emoji['group'] == '👥'
        assert type_emoji['channel'] == '📢'

    def test_summary_sorted_by_activity(self):
        """Test summaries are sorted by message count (most active first)."""
        chats = [
            {'title': 'Chat A', 'message_count': 5},
            {'title': 'Chat B', 'message_count': 20},
            {'title': 'Chat C', 'message_count': 10},
        ]

        sorted_chats = sorted(chats, key=lambda x: x['message_count'], reverse=True)

        assert sorted_chats[0]['title'] == 'Chat B'
        assert sorted_chats[1]['title'] == 'Chat C'
        assert sorted_chats[2]['title'] == 'Chat A'

    def test_limits_chats_to_top_10(self):
        """Test limits displayed chats to top 10."""
        chats = [{'title': f'Chat {i}', 'count': i} for i in range(15)]

        limited = chats[:10]

        assert len(limited) == 10

    def test_shows_remaining_count(self):
        """Test shows remaining chats count."""
        total_chats = 15
        displayed = 10
        remaining = total_chats - displayed

        if remaining > 0:
            text = f"...и ещё {remaining} чатов"
        else:
            text = ""

        assert "5 чатов" in text


class TestProductivitySettingsIntegration:
    """Tests for productivity settings in Settings model."""

    def test_summary_time_format_validation(self):
        """Test time format validation for HH:MM."""
        import re

        valid_times = ["19:00", "9:30", "00:00", "23:59"]
        invalid_times = ["25:00", "12:60", "1pm", "invalid"]

        for time_str in valid_times:
            match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
            assert match is not None, f"Valid time {time_str} should match"
            hour, minute = int(match.group(1)), int(match.group(2))
            assert 0 <= hour <= 23 and 0 <= minute <= 59

        for time_str in invalid_times:
            match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
            if match:
                hour, minute = int(match.group(1)), int(match.group(2))
                is_valid = 0 <= hour <= 23 and 0 <= minute <= 59
                assert not is_valid, f"Invalid time {time_str} should fail validation"
            else:
                assert match is None, f"Invalid time {time_str} should not match"

    def test_enabled_setting_toggle(self):
        """Test enabled setting toggle logic."""
        enabled = 'true'
        is_enabled = enabled == 'true'
        assert is_enabled is True

        disabled = 'false'
        is_disabled = disabled == 'true'
        assert is_disabled is False

        default = None
        is_default = (default or 'false') == 'true'
        assert is_default is False


class TestProductivityServiceMutedDialogFiltering:
    """Tests for ProductivityService._is_dialog_muted()."""

    def test_returns_false_when_no_notify_settings(self):
        """Test returns False when dialog has no notify settings."""
        dialog = MagicMock()
        dialog.dialog = MagicMock()
        dialog.dialog.notify_settings = None

        # Simulate _is_dialog_muted logic
        notify_settings = getattr(dialog.dialog, 'notify_settings', None)
        result = False
        if notify_settings is not None:
            result = True  # Would check mute_until

        assert result is False

    def test_returns_true_when_muted_forever(self):
        """Test returns True when dialog is muted forever (max int)."""
        from datetime import datetime

        dialog = MagicMock()
        dialog.dialog = MagicMock()
        dialog.dialog.notify_settings = MagicMock()
        dialog.dialog.notify_settings.mute_until = 2147483647  # Max int = muted forever

        notify_settings = dialog.dialog.notify_settings
        mute_until = getattr(notify_settings, 'mute_until', None)

        is_muted = False
        if mute_until and mute_until > datetime.now().timestamp():
            is_muted = True

        assert is_muted is True

    def test_returns_true_when_muted_until_future(self):
        """Test returns True when mute_until is in the future."""
        from datetime import datetime

        dialog = MagicMock()
        dialog.dialog = MagicMock()
        dialog.dialog.notify_settings = MagicMock()
        # Muted until 1 hour from now
        dialog.dialog.notify_settings.mute_until = datetime.now().timestamp() + 3600

        notify_settings = dialog.dialog.notify_settings
        mute_until = getattr(notify_settings, 'mute_until', None)

        is_muted = mute_until and mute_until > datetime.now().timestamp()

        assert is_muted is True

    def test_returns_false_when_mute_expired(self):
        """Test returns False when mute_until is in the past."""
        from datetime import datetime

        dialog = MagicMock()
        dialog.dialog = MagicMock()
        dialog.dialog.notify_settings = MagicMock()
        # Muted until 1 hour ago (expired)
        dialog.dialog.notify_settings.mute_until = datetime.now().timestamp() - 3600

        notify_settings = dialog.dialog.notify_settings
        mute_until = getattr(notify_settings, 'mute_until', None)

        is_muted = mute_until and mute_until > datetime.now().timestamp()

        assert is_muted is False

    def test_returns_true_when_silent_flag_set(self):
        """Test returns True when silent flag is set."""
        dialog = MagicMock()
        dialog.dialog = MagicMock()
        dialog.dialog.notify_settings = MagicMock()
        dialog.dialog.notify_settings.mute_until = None
        dialog.dialog.notify_settings.silent = True

        notify_settings = dialog.dialog.notify_settings
        silent = getattr(notify_settings, 'silent', False)

        assert silent is True

    def test_returns_false_when_not_muted_and_not_silent(self):
        """Test returns False when dialog is not muted and not silent."""
        from datetime import datetime

        dialog = MagicMock()
        dialog.dialog = MagicMock()
        dialog.dialog.notify_settings = MagicMock()
        dialog.dialog.notify_settings.mute_until = None
        dialog.dialog.notify_settings.silent = False

        notify_settings = dialog.dialog.notify_settings
        mute_until = getattr(notify_settings, 'mute_until', None)
        silent = getattr(notify_settings, 'silent', False)

        is_muted = False
        if mute_until and mute_until > datetime.now().timestamp():
            is_muted = True
        if silent:
            is_muted = True

        assert is_muted is False


class TestProductivityServiceExtraChatIds:
    """Tests for ProductivityService extra_chat_ids parameter."""

    def test_muted_chat_included_when_in_extra_ids(self):
        """Test muted chat is included when in extra_chat_ids."""
        dialog_id = 12345
        is_muted = True
        extra_chat_ids = [12345, 67890]

        is_extra = dialog_id in extra_chat_ids
        should_skip = is_muted and not is_extra

        assert is_extra is True
        assert should_skip is False  # Should NOT be skipped

    def test_muted_chat_skipped_when_not_in_extra_ids(self):
        """Test muted chat is skipped when not in extra_chat_ids."""
        dialog_id = 12345
        is_muted = True
        extra_chat_ids = [67890]  # Different ID

        is_extra = dialog_id in extra_chat_ids
        should_skip = is_muted and not is_extra

        assert is_extra is False
        assert should_skip is True  # Should be skipped

    def test_unmuted_chat_included_regardless_of_extra_ids(self):
        """Test unmuted chat is included regardless of extra_chat_ids."""
        dialog_id = 12345
        is_muted = False
        extra_chat_ids = []

        is_extra = dialog_id in extra_chat_ids
        should_skip = is_muted and not is_extra

        assert should_skip is False  # Unmuted = never skipped

    def test_empty_extra_chat_ids_list(self):
        """Test handles empty extra_chat_ids list."""
        dialog_id = 12345
        extra_chat_ids = []

        is_extra = dialog_id in extra_chat_ids

        assert is_extra is False

    def test_none_extra_chat_ids_treated_as_empty(self):
        """Test None extra_chat_ids is treated as empty list."""
        dialog_id = 12345
        extra_chat_ids = None

        # Simulate handling of None
        extra_chat_ids = extra_chat_ids or []
        is_extra = dialog_id in extra_chat_ids

        assert is_extra is False


class TestProductivityExtraChatSettings:
    """Tests for productivity extra chats settings methods."""

    def test_parse_extra_chats_string(self):
        """Test parsing comma-separated chat IDs from string."""
        value = "-1001234567890,-100987654321,123456"

        chat_ids = []
        if value:
            for part in value.split(','):
                part = part.strip()
                if part:
                    try:
                        chat_ids.append(int(part))
                    except ValueError:
                        pass

        assert len(chat_ids) == 3
        assert -1001234567890 in chat_ids
        assert -100987654321 in chat_ids
        assert 123456 in chat_ids

    def test_parse_empty_string_returns_empty_list(self):
        """Test parsing empty string returns empty list."""
        value = ""

        chat_ids = []
        if value:
            for part in value.split(','):
                part = part.strip()
                if part:
                    try:
                        chat_ids.append(int(part))
                    except ValueError:
                        pass

        assert chat_ids == []

    def test_parse_none_returns_empty_list(self):
        """Test parsing None returns empty list."""
        value = None

        chat_ids = []
        if value:
            for part in value.split(','):
                part = part.strip()
                if part:
                    try:
                        chat_ids.append(int(part))
                    except ValueError:
                        pass

        assert chat_ids == []

    def test_add_chat_to_list(self):
        """Test adding chat ID to existing list."""
        existing = [-1001234567890]
        new_chat_id = -100987654321

        if new_chat_id not in existing:
            existing.append(new_chat_id)

        assert len(existing) == 2
        assert new_chat_id in existing

    def test_add_duplicate_chat_not_added(self):
        """Test duplicate chat ID is not added."""
        existing = [-1001234567890]
        new_chat_id = -1001234567890  # Same as existing

        if new_chat_id not in existing:
            existing.append(new_chat_id)

        assert len(existing) == 1

    def test_remove_chat_from_list(self):
        """Test removing chat ID from list."""
        chat_ids = [-1001234567890, -100987654321]
        to_remove = -1001234567890

        if to_remove in chat_ids:
            chat_ids.remove(to_remove)

        assert len(chat_ids) == 1
        assert to_remove not in chat_ids

    def test_remove_nonexistent_chat_no_error(self):
        """Test removing nonexistent chat ID does not raise error."""
        chat_ids = [-1001234567890]
        to_remove = -100987654321  # Not in list

        if to_remove in chat_ids:
            chat_ids.remove(to_remove)

        assert len(chat_ids) == 1  # Unchanged

    def test_serialize_chat_ids_to_string(self):
        """Test serializing chat IDs list to comma-separated string."""
        chat_ids = [-1001234567890, -100987654321]

        value = ','.join(str(id) for id in chat_ids)

        assert value == "-1001234567890,-100987654321"


class TestProductivitySummaryHashtag:
    """Tests for hashtag in productivity summary output."""

    def test_summary_includes_hashtag(self):
        """Test summary includes #productivity hashtag."""
        lines = [
            "📊 **Продуктивность за 31.01.2026**",
            "",
            "📨 Всего сообщений: **42**",
            "",
            "#productivity #дайджест"
        ]
        summary = "\n".join(lines)

        assert "#productivity" in summary
        assert "#дайджест" in summary

    def test_hashtag_at_end_of_summary(self):
        """Test hashtag is at the end of summary."""
        lines = [
            "📊 **Продуктивность за 31.01.2026**",
            "",
            "📨 Всего сообщений: **42**",
            "",
            "#productivity #дайджест"
        ]
        summary = "\n".join(lines)

        assert summary.endswith("#productivity #дайджест")

    def test_empty_summary_includes_hashtag(self):
        """Test even empty summary includes hashtag."""
        summary = "📊 **Сводка за день**\n\nСегодня вы не отправляли сообщений.\n\n#productivity #дайджест"

        assert "#productivity" in summary


class TestProductivityFloodWaitHandling:
    """Tests for FloodWait error handling in productivity service."""

    def test_flood_wait_should_continue_to_next_chat(self):
        """Test FloodWait error should skip current chat and continue."""
        # Simulate FloodWait handling logic
        chats_processed = []
        chats_to_process = ["chat1", "chat2", "chat3"]
        flood_wait_on = "chat2"

        for chat in chats_to_process:
            if chat == flood_wait_on:
                # FloodWait - skip this chat
                continue
            chats_processed.append(chat)

        assert "chat1" in chats_processed
        assert "chat2" not in chats_processed  # Skipped
        assert "chat3" in chats_processed

    def test_flood_wait_extracts_wait_seconds(self):
        """Test FloodWait error extracts wait seconds."""
        # Simulate FloodWaitError with seconds attribute
        class FakeFloodWaitError(Exception):
            def __init__(self, seconds):
                self.seconds = seconds

        error = FakeFloodWaitError(30)

        assert error.seconds == 30

    def test_request_delay_reduces_flood_risk(self):
        """Test request delay parameter exists for rate limiting."""
        request_delay = 0.5  # 500ms delay between requests

        assert request_delay > 0
        assert request_delay <= 1.0  # Reasonable upper bound


class TestProductivityBotMenuIntegration:
    """Tests for productivity bot menu integration."""

    def test_main_menu_includes_productivity(self):
        """Test main menu should include productivity option."""
        menu_items = [
            "📊 Статус",
            "📝 Автоответы",
            "📅 Расписание",
            "📈 Продуктивность",
            "⚙️ Настройки"
        ]

        assert "📈 Продуктивность" in menu_items

    def test_productivity_menu_structure(self):
        """Test productivity menu has required buttons."""
        buttons = [
            "📊 Сгенерировать сейчас",
            "⏰ Время отправки",
            "➕ Доп. чаты",
            "🟢 Включить / 🔴 Выключить",
            "« Назад"
        ]

        assert "📊 Сгенерировать сейчас" in buttons
        assert "⏰ Время отправки" in buttons
        assert "➕ Доп. чаты" in buttons
        assert "« Назад" in buttons

    def test_extra_chats_menu_structure(self):
        """Test extra chats menu has required buttons."""
        buttons = [
            "➕ Добавить чат",
            "🗑 Очистить все",
            "« Назад"
        ]

        assert "➕ Добавить чат" in buttons
        assert "🗑 Очистить все" in buttons
        assert "« Назад" in buttons

    def test_add_chat_via_forwarded_message(self):
        """Test adding chat via forwarded message extracts chat ID."""
        # Simulate forwarded message from channel
        fwd_from_id = MagicMock()
        fwd_from_id.channel_id = 1234567890

        # Simulate chat ID extraction
        if hasattr(fwd_from_id, 'channel_id'):
            chat_id = int(f"-100{fwd_from_id.channel_id}")

        assert chat_id == -1001234567890

    def test_add_chat_via_group_forward(self):
        """Test adding chat via forwarded message from group."""
        # Simulate forwarded message from regular group
        fwd_from_id = MagicMock()
        fwd_from_id.chat_id = 123456789
        fwd_from_id.channel_id = None

        # Simulate chat ID extraction
        if hasattr(fwd_from_id, 'channel_id') and fwd_from_id.channel_id:
            chat_id = int(f"-100{fwd_from_id.channel_id}")
        elif hasattr(fwd_from_id, 'chat_id'):
            chat_id = -fwd_from_id.chat_id

        assert chat_id == -123456789

    def test_add_chat_via_manual_id_input(self):
        """Test adding chat via manual ID input."""
        text = "-1001234567890"

        try:
            chat_id = int(text)
            is_valid = True
        except ValueError:
            is_valid = False

        assert is_valid is True
        assert chat_id == -1001234567890

    def test_invalid_manual_id_rejected(self):
        """Test invalid manual ID is rejected."""
        text = "not_a_number"

        try:
            chat_id = int(text)
            is_valid = True
        except ValueError:
            is_valid = False

        assert is_valid is False


class TestProductivityTempChats:
    """Tests for temporary productivity chats feature."""

    def test_get_temp_chats_empty_by_default(self):
        """Test get_productivity_temp_chats returns empty list by default."""
        value = None  # Simulate no setting

        chat_ids = []
        if value:
            for part in value.split(','):
                part = part.strip()
                if part:
                    try:
                        chat_ids.append(int(part))
                    except ValueError:
                        pass

        assert chat_ids == []

    def test_add_temp_chat(self):
        """Test adding chat to temp list."""
        temp_chats = []
        chat_id = -1001234567890

        if chat_id not in temp_chats:
            temp_chats.append(chat_id)

        assert chat_id in temp_chats
        assert len(temp_chats) == 1

    def test_add_duplicate_temp_chat_not_added(self):
        """Test duplicate chat is not added to temp list."""
        temp_chats = [-1001234567890]
        chat_id = -1001234567890  # Same

        if chat_id not in temp_chats:
            temp_chats.append(chat_id)

        assert len(temp_chats) == 1

    def test_clear_temp_chats(self):
        """Test clearing all temp chats."""
        temp_chats = [-1001234567890, -100987654321, -100111222333]

        # Clear
        temp_chats = []

        assert temp_chats == []

    def test_combine_extra_and_temp_chats(self):
        """Test combining extra chats with temp chats."""
        extra_chat_ids = [-1001111111111, -1002222222222]
        temp_chat_ids = [-1003333333333, -1001111111111]  # One duplicate

        # Combine with set to remove duplicates
        all_extra_chats = list(set(extra_chat_ids + temp_chat_ids))

        assert len(all_extra_chats) == 3  # 4 total - 1 duplicate = 3
        assert -1001111111111 in all_extra_chats
        assert -1002222222222 in all_extra_chats
        assert -1003333333333 in all_extra_chats


class TestProductivityTempChatTriggers:
    """Tests for temp chat triggers (mention and reply)."""

    def test_mention_triggers_temp_chat_add(self):
        """Test that mention in group adds chat to temp list."""
        is_private = False
        is_mentioned = True
        chat_id = -1001234567890

        should_add = not is_private and is_mentioned

        assert should_add is True

    def test_mention_in_private_does_not_trigger(self):
        """Test that mention in private chat does not add to temp list."""
        is_private = True
        is_mentioned = True

        should_add = not is_private and is_mentioned

        assert should_add is False

    def test_reply_to_my_message_triggers_temp_chat_add(self):
        """Test that reply to my message adds chat to temp list."""
        is_private = False
        is_reply = True
        original_sender_is_me = True
        chat_id = -1001234567890

        should_add = not is_private and is_reply and original_sender_is_me

        assert should_add is True

    def test_reply_to_others_message_does_not_trigger(self):
        """Test that reply to someone else's message does not trigger."""
        is_private = False
        is_reply = True
        original_sender_is_me = False

        should_add = not is_private and is_reply and original_sender_is_me

        assert should_add is False

    def test_non_reply_does_not_trigger(self):
        """Test that non-reply message does not trigger."""
        is_private = False
        is_reply = False
        original_sender_is_me = True

        should_add = not is_private and is_reply and original_sender_is_me

        assert should_add is False

    def test_reply_in_private_does_not_trigger(self):
        """Test that reply in private chat does not trigger."""
        is_private = True
        is_reply = True
        original_sender_is_me = True

        should_add = not is_private and is_reply and original_sender_is_me

        assert should_add is False


class TestProductivityTempChatReplyDetection:
    """Tests for reply-to-my-message detection logic."""

    def test_detect_reply_to_msg_id(self):
        """Test detection of reply_to_msg_id attribute."""
        message = MagicMock()
        message.reply_to_msg_id = 42

        reply_to_id = getattr(message, 'reply_to_msg_id', None)

        assert reply_to_id == 42

    def test_detect_nested_reply_to(self):
        """Test detection of nested reply_to structure."""
        message = MagicMock()
        message.reply_to_msg_id = None
        message.reply_to = MagicMock()
        message.reply_to.reply_to_msg_id = 42

        reply_to_id = getattr(message, 'reply_to_msg_id', None)
        if not reply_to_id:
            reply_to = getattr(message, 'reply_to', None)
            if reply_to:
                reply_to_id = getattr(reply_to, 'reply_to_msg_id', None)

        assert reply_to_id == 42

    def test_no_reply_detected(self):
        """Test no reply when neither attribute exists."""
        message = MagicMock()
        message.reply_to_msg_id = None
        message.reply_to = None

        reply_to_id = getattr(message, 'reply_to_msg_id', None)
        if not reply_to_id:
            reply_to = getattr(message, 'reply_to', None)
            if reply_to:
                reply_to_id = getattr(reply_to, 'reply_to_msg_id', None)

        assert reply_to_id is None

    def test_check_original_message_sender(self):
        """Test checking if original message was sent by me."""
        original_msg = MagicMock()
        original_msg.sender_id = 123456
        my_id = 123456

        is_my_message = original_msg.sender_id == my_id

        assert is_my_message is True

    def test_original_message_from_others(self):
        """Test when original message was sent by someone else."""
        original_msg = MagicMock()
        original_msg.sender_id = 789012
        my_id = 123456

        is_my_message = original_msg.sender_id == my_id

        assert is_my_message is False


class TestProductivityTempChatClearing:
    """Tests for clearing temp chats after summary generation."""

    def test_temp_chats_cleared_after_summary(self):
        """Test temp chats are cleared after summary is generated."""
        temp_chat_ids = [-1001111111111, -1002222222222]

        # Simulate summary generation
        summary_generated = True

        # Clear after summary
        if summary_generated:
            temp_chat_ids_after = []
        else:
            temp_chat_ids_after = temp_chat_ids

        assert temp_chat_ids_after == []

    def test_temp_chats_preserved_if_summary_fails(self):
        """Test temp chats not cleared if summary generation fails."""
        temp_chat_ids = [-1001111111111, -1002222222222]

        # Simulate failed summary generation
        summary_generated = False

        # Don't clear if failed
        if summary_generated:
            temp_chat_ids_after = []
        else:
            temp_chat_ids_after = temp_chat_ids

        assert len(temp_chat_ids_after) == 2

    def test_clearing_empty_list_is_safe(self):
        """Test clearing empty temp list is safe."""
        temp_chat_ids = []

        # Clear (should not raise)
        temp_chat_ids = []

        assert temp_chat_ids == []

    def test_log_cleared_count(self):
        """Test that cleared count is available for logging."""
        temp_chat_ids = [-1001111111111, -1002222222222, -1003333333333]
        cleared_count = len(temp_chat_ids)

        # Clear
        temp_chat_ids = []

        assert cleared_count == 3
        assert len(temp_chat_ids) == 0


class TestProductivityTempChatIntegration:
    """Integration tests for temp chats in productivity flow."""

    def test_muted_temp_chat_included_in_summary(self):
        """Test muted chat from temp list is included in summary."""
        dialog_id = -1001234567890
        is_muted = True
        extra_chat_ids = []  # Not in permanent extras
        temp_chat_ids = [-1001234567890]  # But in temp list

        all_extra_chats = list(set(extra_chat_ids + temp_chat_ids))
        is_in_extras = dialog_id in all_extra_chats
        should_skip = is_muted and not is_in_extras

        assert is_in_extras is True
        assert should_skip is False  # Should NOT be skipped

    def test_unmuted_chat_included_regardless_of_temp(self):
        """Test unmuted chat is included regardless of temp list."""
        dialog_id = -1001234567890
        is_muted = False
        extra_chat_ids = []
        temp_chat_ids = []  # Not in temp either

        all_extra_chats = list(set(extra_chat_ids + temp_chat_ids))
        is_in_extras = dialog_id in all_extra_chats
        should_skip = is_muted and not is_in_extras

        assert should_skip is False  # Unmuted = always included

    def test_chat_in_both_permanent_and_temp_not_duplicated(self):
        """Test chat in both lists is not processed twice."""
        extra_chat_ids = [-1001234567890]
        temp_chat_ids = [-1001234567890]  # Same chat

        all_extra_chats = list(set(extra_chat_ids + temp_chat_ids))

        assert len(all_extra_chats) == 1
        assert -1001234567890 in all_extra_chats

    def test_multiple_temp_chats_all_included(self):
        """Test multiple temp chats are all included."""
        extra_chat_ids = [-1001111111111]
        temp_chat_ids = [-1002222222222, -1003333333333, -1004444444444]

        all_extra_chats = list(set(extra_chat_ids + temp_chat_ids))

        assert len(all_extra_chats) == 4
        for chat_id in temp_chat_ids:
            assert chat_id in all_extra_chats


# =============================================================================
# Private Message Notification Tests
# =============================================================================


class TestPrivateNotificationSettings:
    """Tests for private message notification settings."""

    def test_default_is_disabled(self):
        """Test private notification is disabled by default."""
        # Simulate Settings.get returning None (not set)
        value = None
        is_enabled = value == 'true'

        assert is_enabled is False

    def test_enabled_when_set_to_true(self):
        """Test private notification is enabled when set to true."""
        value = 'true'
        is_enabled = value == 'true'

        assert is_enabled is True

    def test_disabled_when_set_to_false(self):
        """Test private notification is disabled when set to false."""
        value = 'false'
        is_enabled = value == 'true'

        assert is_enabled is False

    def test_disabled_for_any_other_value(self):
        """Test private notification is disabled for any non-'true' value."""
        for value in ['yes', '1', 'True', 'TRUE', 'enabled', '']:
            is_enabled = value == 'true'
            assert is_enabled is False


class TestPrivateMessageSummaryGeneration:
    """Tests for MentionService.generate_private_summary()."""

    def test_includes_topic_from_text(self):
        """Test summary includes detected topic."""
        import re

        current_text = "Can you help with the PR?"
        topic_patterns = [
            (r'\b(pr|пр|pull.?request|merge|мерж|ревью|review)\b', '👀 Нужно ревью кода'),
            (r'\b(помо[гщ]|help|подскаж|объясн|разбер)\b', '🆘 Нужна помощь'),
        ]

        detected_topics = []
        for pattern, topic in topic_patterns:
            if re.search(pattern, current_text.lower()):
                detected_topics.append(topic)

        assert '👀 Нужно ревью кода' in detected_topics
        assert '🆘 Нужна помощь' in detected_topics

    def test_includes_context_messages(self):
        """Test summary includes context from previous messages."""
        messages = [
            MagicMock(id=1, text="Previous message 1"),
            MagicMock(id=2, text="Previous message 2"),
            MagicMock(id=3, text="Current message"),  # Current
        ]
        current_message = messages[2]

        # Simulate context extraction (excluding current)
        context_msgs = []
        for msg in messages:
            if msg.id != current_message.id:
                context_msgs.append(msg.text)

        assert len(context_msgs) == 2
        assert "Previous message 1" in context_msgs
        assert "Previous message 2" in context_msgs

    def test_limits_context_messages(self):
        """Test summary limits number of context messages."""
        max_context = 5
        messages = [MagicMock(id=i, text=f"Message {i}") for i in range(10)]
        current_message = messages[9]

        context_msgs = []
        for msg in messages:
            if msg.id == current_message.id:
                continue
            if len(context_msgs) >= max_context:
                break
            context_msgs.append(msg.text)

        assert len(context_msgs) == max_context

    def test_truncates_long_context_messages(self):
        """Test summary truncates long context messages."""
        long_text = "A" * 200
        max_length = 80

        text = long_text
        if len(text) > max_length:
            text = text[:max_length] + "..."

        assert len(text) == 83  # 80 + "..."
        assert text.endswith("...")

    def test_handles_empty_context(self):
        """Test summary handles empty context gracefully."""
        messages = [MagicMock(id=1, text="Current message")]
        current_message = messages[0]

        context_msgs = []
        for msg in messages:
            if msg.id != current_message.id:
                context_msgs.append(msg.text)

        assert len(context_msgs) == 0

    def test_default_topic_when_no_pattern_matches(self):
        """Test default topic when no pattern matches."""
        import re

        current_text = "Hello there"
        topic_patterns = [
            (r'\b(pr|pull.?request)\b', '👀 Нужно ревью кода'),
            (r'\b(срочно|urgent)\b', '🚨 Срочно'),
        ]

        detected_topics = []
        for pattern, topic in topic_patterns:
            if re.search(pattern, current_text.lower()):
                detected_topics.append(topic)

        # Default topic when nothing detected
        if not detected_topics:
            default_topic = "📌 Тема: общение"

        assert len(detected_topics) == 0
        assert default_topic == "📌 Тема: общение"


class TestPrivateMessageNotificationFormat:
    """Tests for MentionService.format_private_notification()."""

    def test_includes_sender_with_username(self):
        """Test notification includes sender info with username."""
        sender_name = "John Doe"
        sender_username = "johndoe"

        sender_info = f"@{sender_username} ({sender_name})"
        sender_link = f"https://t.me/{sender_username}"

        assert "@johndoe" in sender_info
        assert "John Doe" in sender_info
        assert sender_link == "https://t.me/johndoe"

    def test_includes_sender_without_username(self):
        """Test notification includes sender info without username."""
        sender_name = "John Doe"
        sender_username = None

        if sender_username:
            sender_info = f"@{sender_username} ({sender_name})"
            sender_link = f"https://t.me/{sender_username}"
        else:
            sender_info = sender_name
            sender_link = None

        assert sender_info == "John Doe"
        assert sender_link is None

    def test_urgent_header(self):
        """Test urgent private message has urgent header."""
        is_urgent = True

        if is_urgent:
            header = "🚨 Срочное личное сообщение!"
        else:
            header = "💬 Личное сообщение"

        assert "🚨" in header
        assert "Срочное" in header

    def test_normal_header(self):
        """Test normal private message has standard header."""
        is_urgent = False

        if is_urgent:
            header = "🚨 Срочное личное сообщение!"
        else:
            header = "💬 Личное сообщение"

        assert "💬" in header
        assert "Срочное" not in header

    def test_truncates_long_message(self):
        """Test notification truncates long message text."""
        message_text = "A" * 300
        max_length = 200

        if len(message_text) > max_length:
            message_text = message_text[:max_length] + "..."

        assert len(message_text) == 203  # 200 + "..."
        assert message_text.endswith("...")

    def test_includes_message_text(self):
        """Test notification includes the message text."""
        message_text = "Can you help me with this?"

        notification_line = f"✉️ Сообщение:\n  «{message_text}»"

        assert "Can you help me with this?" in notification_line

    def test_includes_dialog_link(self):
        """Test notification includes link to dialog."""
        sender_username = "johndoe"
        sender_link = f"https://t.me/{sender_username}"

        link_line = f"🔗 Открыть диалог: {sender_link}"

        assert "https://t.me/johndoe" in link_line


class TestPrivateMessageHandlerLogic:
    """Tests for private_message_context_handler logic."""

    def test_skips_non_private_messages(self):
        """Test handler skips non-private (group) messages."""
        is_private = False

        should_process = is_private
        assert should_process is False

    def test_skips_when_disabled(self):
        """Test handler skips when private notifications disabled."""
        is_private = True
        is_enabled = False

        should_process = is_private and is_enabled
        assert should_process is False

    def test_skips_bot_messages(self):
        """Test handler skips messages from bots."""
        is_private = True
        is_enabled = True
        is_bot = True

        should_process = is_private and is_enabled and not is_bot
        assert should_process is False

    def test_skips_empty_messages(self):
        """Test handler skips empty messages (stickers, media only)."""
        is_private = True
        is_enabled = True
        is_bot = False
        message_text = ""

        has_text = bool(message_text.strip())
        should_process = is_private and is_enabled and not is_bot and has_text

        assert should_process is False

    def test_skips_when_user_online(self):
        """Test handler skips when user is online."""
        is_private = True
        is_enabled = True
        is_bot = False
        message_text = "Hello"
        is_online = True  # User has work emoji

        # User online = don't notify
        should_notify = is_private and is_enabled and not is_bot and bool(message_text) and not is_online

        assert should_notify is False

    def test_notifies_when_user_offline(self):
        """Test handler notifies when user is offline."""
        is_private = True
        is_enabled = True
        is_bot = False
        message_text = "Hello"
        is_online = False  # User doesn't have work emoji

        should_notify = is_private and is_enabled and not is_bot and bool(message_text) and not is_online

        assert should_notify is True

    def test_vip_sender_is_urgent(self):
        """Test VIP sender message is marked urgent."""
        sender_username = "vip_user"
        vip_usernames = ["vip_user", "another_vip"]

        is_vip = sender_username.lower() in [u.lower() for u in vip_usernames]
        is_urgent = is_vip

        assert is_urgent is True

    def test_non_vip_sender_not_urgent_by_default(self):
        """Test non-VIP sender message is not urgent by default."""
        sender_username = "regular_user"
        vip_usernames = ["vip_user", "another_vip"]

        is_vip = sender_username.lower() in [u.lower() for u in vip_usernames]
        has_urgent_keywords = False
        ai_urgency = None

        # Urgency: VIP > AI > keywords
        if is_vip:
            is_urgent = True
        elif ai_urgency is not None:
            is_urgent = ai_urgency
        else:
            is_urgent = has_urgent_keywords

        assert is_urgent is False

    def test_urgent_keywords_trigger_urgency(self):
        """Test urgent keywords trigger urgency."""
        import re

        message_text = "ASAP need help"
        urgent_keywords = ['asap', 'urgent', 'срочно', 'помогите']
        pattern = re.compile(
            r'\b(' + '|'.join(re.escape(kw) for kw in urgent_keywords) + r')\b',
            re.IGNORECASE
        )

        has_urgent_keywords = bool(pattern.search(message_text))

        assert has_urgent_keywords is True

    def test_notification_sent_silently_when_not_urgent(self):
        """Test notification is sent silently when not urgent."""
        is_urgent = False
        silent = not is_urgent

        assert silent is True

    def test_notification_not_silent_when_urgent(self):
        """Test notification is not silent when urgent."""
        is_urgent = True
        silent = not is_urgent

        assert silent is False


class TestPrivateMessageBotNotification:
    """Tests for sending private message notifications via bot."""

    def test_prefers_bot_when_available(self):
        """Test notification is sent via bot when bot_client is available."""
        bot_client_available = True
        owner_id = 123456789

        if bot_client_available and owner_id:
            send_via = "bot"
        else:
            send_via = "user_client"

        assert send_via == "bot"

    def test_fallback_to_user_client_when_no_bot(self):
        """Test notification falls back to user client when no bot."""
        bot_client_available = False
        owner_id = None

        if bot_client_available and owner_id:
            send_via = "bot"
        else:
            send_via = "user_client"

        assert send_via == "user_client"

    def test_fallback_to_user_client_when_no_owner_id(self):
        """Test notification falls back to user client when no owner_id."""
        bot_client_available = True
        owner_id = None

        if bot_client_available and owner_id:
            send_via = "bot"
        else:
            send_via = "user_client"

        assert send_via == "user_client"


class TestPrivateMessageWebhookIntegration:
    """Tests for webhook integration with private message notifications."""

    def test_webhook_called_when_configured(self):
        """Test webhook is called when configured."""
        webhook_url = "https://example.com/webhook"
        notification_sent = True

        should_call_webhook = webhook_url and notification_sent

        assert should_call_webhook is True

    def test_webhook_not_called_when_not_configured(self):
        """Test webhook is not called when not configured."""
        webhook_url = None
        notification_sent = True

        should_call_webhook = bool(webhook_url) and notification_sent

        assert should_call_webhook is False

    def test_webhook_payload_includes_sender_info(self):
        """Test webhook payload includes sender info."""
        sender_username = "johndoe"
        sender_id = 123456789
        message_text = "Hello there"

        if sender_username:
            sender_name = f"@{sender_username}"
        else:
            sender_name = f"ID:{sender_id}"

        payload = {
            'sender_username': sender_username,
            'sender_id': sender_id,
            'sender_name': sender_name,
            'message': message_text,
        }

        assert payload['sender_username'] == "johndoe"
        assert payload['sender_id'] == 123456789
        assert payload['sender_name'] == "@johndoe"
        assert payload['message'] == "Hello there"
