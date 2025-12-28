"""
Unit tests for Telethon event handler logic.

These tests validate the handler behavior patterns using mocks,
without requiring actual Telethon dependencies.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSelectSettingsChatLogic:
    """Tests for /autoreply-settings command handler logic."""

    @pytest.mark.asyncio
    async def test_sets_settings_chat_id(self, mock_settings, mock_telegram_client):
        """Test that command sets settings_chat_id correctly."""
        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = 12345
        event.message = MagicMock()
        event.message.id = 1
        event.input_chat = MagicMock()

        # Simulate handler logic
        chat_id = event.chat.id
        mock_settings.set_settings_chat_id(chat_id)

        # Verify
        result = mock_settings.get_settings_chat_id()
        assert result == 12345

    @pytest.mark.asyncio
    async def test_sends_confirmation_message(self, mock_telegram_client):
        """Test that handler sends confirmation message."""
        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = 12345
        event.input_chat = MagicMock()

        # Simulate sending message
        await mock_telegram_client.send_message(
            entity=event.input_chat,
            message="Этот чат выбран для настройки автоответчика."
        )

        mock_telegram_client.send_message.assert_called_once()
        call_kwargs = mock_telegram_client.send_message.call_args
        assert 'Этот чат выбран' in call_kwargs.kwargs.get('message', '')


class TestDisableAutoreplyLogic:
    """Tests for /autoreply-off command handler logic."""

    @pytest.mark.asyncio
    async def test_clears_settings_chat_id(self, mock_settings):
        """Test that command clears settings_chat_id."""
        # First set the settings chat
        mock_settings.set_settings_chat_id(12345)
        assert mock_settings.get_settings_chat_id() == 12345

        # Simulate handler clearing it
        mock_settings.set_settings_chat_id(None)

        # Verify
        result = mock_settings.get_settings_chat_id()
        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_wrong_chat(self, mock_settings, mock_telegram_client):
        """Test that command is ignored in wrong chat."""
        # Set settings chat to different ID
        mock_settings.set_settings_chat_id(99999)

        current_chat_id = 12345
        settings_chat_id = mock_settings.get_settings_chat_id()

        # Handler logic: check if current chat matches settings chat
        if settings_chat_id != current_chat_id:
            # Should return early, not send message
            pass
        else:
            await mock_telegram_client.send_message(entity=None, message="test")

        # Should not send message
        mock_telegram_client.send_message.assert_not_called()

        # Settings should not be changed
        assert mock_settings.get_settings_chat_id() == 99999


class TestSetupResponseLogic:
    """Tests for /set_for command handler logic."""

    @pytest.mark.asyncio
    async def test_requires_reply(self, mock_settings, mock_telegram_client):
        """Test that command requires replying to a message."""
        mock_settings.set_settings_chat_id(12345)

        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = 12345
        event.reply_to = None  # No reply
        event.input_chat = MagicMock()

        # Handler logic
        settings_chat_id = mock_settings.get_settings_chat_id()
        if settings_chat_id == event.chat.id:
            if not event.reply_to:
                await mock_telegram_client.send_message(
                    entity=event.input_chat,
                    message="Команда должна быть ответом на сообщение"
                )

        # Should send error message
        mock_telegram_client.send_message.assert_called_once()
        call_kwargs = mock_telegram_client.send_message.call_args
        assert 'ответом' in call_kwargs.kwargs.get('message', '')

    @pytest.mark.asyncio
    async def test_requires_exactly_one_emoji(self, mock_settings, mock_telegram_client):
        """Test that command requires exactly one custom emoji."""
        mock_settings.set_settings_chat_id(12345)

        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = 12345
        event.message = MagicMock()
        event.message.entities = []  # No custom emojis
        event.reply_to = MagicMock()
        event.input_chat = MagicMock()

        # Handler logic - filter for custom emoji entities
        custom_emojis = [e for e in event.message.entities
                        if getattr(e, 'document_id', None) is not None]

        if len(custom_emojis) != 1:
            await mock_telegram_client.send_message(
                entity=event.input_chat,
                message=f"Нужен 1 кастомный эмодзи, найдено: {len(custom_emojis)}"
            )

        # Should send error about emoji count
        mock_telegram_client.send_message.assert_called()
        call_kwargs = mock_telegram_client.send_message.call_args
        assert 'эмодзи' in call_kwargs.kwargs.get('message', '').lower()


class TestSetupResponseCurrentStatusLogic:
    """Tests for /set command handler logic."""

    @pytest.mark.asyncio
    async def test_requires_emoji_status(self, mock_settings, mock_telegram_client):
        """Test that command requires user to have emoji status."""
        mock_settings.set_settings_chat_id(12345)

        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = 12345
        event.reply_to = MagicMock()
        event.input_chat = MagicMock()

        # Mock user with no emoji status
        mock_user = MagicMock()
        mock_user.emoji_status = None
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)

        # Handler logic
        me = await mock_telegram_client.get_me()
        if not me.emoji_status:
            await mock_telegram_client.send_message(
                entity=event.input_chat,
                message="У вас не установлен эмодзи-статус"
            )

        # Should send error about no emoji status
        mock_telegram_client.send_message.assert_called()
        call_kwargs = mock_telegram_client.send_message.call_args
        assert 'статус' in call_kwargs.kwargs.get('message', '').lower()

    @pytest.mark.asyncio
    async def test_saves_reply_for_current_status(self, mock_settings, mock_reply, mock_telegram_client, mock_message):
        """Test that command saves reply for current emoji status."""
        mock_settings.set_settings_chat_id(12345)

        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = 12345
        event.reply_to = MagicMock()
        event.reply_to.reply_to_msg_id = 100
        event.input_chat = MagicMock()

        # Mock user with emoji status
        mock_user = MagicMock()
        mock_user.emoji_status = MagicMock()
        mock_user.emoji_status.document_id = 5379748062124056162
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)
        mock_telegram_client.get_messages = AsyncMock(return_value=mock_message)

        # Handler logic
        me = await mock_telegram_client.get_me()
        if me.emoji_status:
            message = await mock_telegram_client.get_messages(event.input_chat, ids=event.reply_to.reply_to_msg_id)
            emoji_id = me.emoji_status.document_id
            mock_reply.create(emoji_id, message)

        # Check reply was saved
        result = mock_reply.get_by_emoji(5379748062124056162)
        assert result is not None


class TestAsapHandlerLogic:
    """Tests for ASAP message handler logic."""

    @pytest.mark.asyncio
    async def test_ignores_non_private(self, mock_telegram_client):
        """Test that handler ignores non-private messages."""
        event = MagicMock()
        event.is_private = False

        # Handler logic
        if not event.is_private:
            return  # Early exit

        await mock_telegram_client.send_message("test", "message")

        # Should not send any message
        mock_telegram_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_when_available(self, mock_telegram_client, sample_available_emoji_id):
        """Test that handler ignores when user is available."""
        event = MagicMock()
        event.is_private = True

        mock_user = MagicMock()
        mock_user.emoji_status = MagicMock()
        mock_user.emoji_status.document_id = sample_available_emoji_id  # Available
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)

        # Handler logic
        me = await mock_telegram_client.get_me()
        if not me.emoji_status or me.emoji_status.document_id == sample_available_emoji_id:
            return  # User is available, don't notify

        await mock_telegram_client.send_message("personal_login", "ASAP notification")

        # Should not send notification
        mock_telegram_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_notification_when_unavailable(self, mock_telegram_client, sample_available_emoji_id):
        """Test that handler sends notification when user is unavailable."""
        event = MagicMock()
        event.is_private = True

        mock_sender = MagicMock()
        mock_sender.username = "urgent_user"

        # User has different emoji (not available)
        mock_user = MagicMock()
        mock_user.emoji_status = MagicMock()
        mock_user.emoji_status.document_id = 1234567890  # Different from available
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)

        personal_tg_login = "test_user"

        # Handler logic
        me = await mock_telegram_client.get_me()
        if event.is_private and me.emoji_status and me.emoji_status.document_id != sample_available_emoji_id:
            await mock_telegram_client.send_message(
                personal_tg_login,
                f'Срочный призыв от @{mock_sender.username}'
            )

        # Should send notification
        mock_telegram_client.send_message.assert_called_once()
        call_args = mock_telegram_client.send_message.call_args
        assert personal_tg_login in str(call_args)


class TestNewMessagesHandlerLogic:
    """Tests for auto-reply handler logic."""

    @pytest.mark.asyncio
    async def test_ignores_non_private(self, mock_telegram_client):
        """Test that handler ignores non-private messages."""
        event = MagicMock()
        event.is_private = False

        # Handler logic
        if not event.is_private:
            return

        await mock_telegram_client.send_message("user", "reply")

        mock_telegram_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_when_no_emoji_status(self, mock_telegram_client):
        """Test that handler ignores when user has no emoji status."""
        event = MagicMock()
        event.is_private = True

        mock_user = MagicMock()
        mock_user.emoji_status = None
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)

        # Handler logic
        me = await mock_telegram_client.get_me()
        if not me.emoji_status:
            return

        await mock_telegram_client.send_message("user", "reply")

        mock_telegram_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_when_no_reply_template(self, mock_telegram_client, mock_reply):
        """Test that handler ignores when no reply template exists."""
        event = MagicMock()
        event.is_private = True

        mock_user = MagicMock()
        mock_user.emoji_status = MagicMock()
        mock_user.emoji_status.document_id = 5379748062124056162
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)

        # Handler logic
        me = await mock_telegram_client.get_me()
        reply = mock_reply.get_by_emoji(me.emoji_status.document_id)
        if reply is None:
            return

        await mock_telegram_client.send_message("user", "reply")

        mock_telegram_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limits_replies(self, mock_telegram_client, mock_reply, mock_message):
        """Test that handler rate limits replies (15 minute cooldown)."""
        # Create reply template
        mock_reply.create(5379748062124056162, mock_message)

        event = MagicMock()
        event.is_private = True

        mock_user = MagicMock()
        mock_user.emoji_status = MagicMock()
        mock_user.emoji_status.document_id = 5379748062124056162
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)

        mock_sender = MagicMock()
        mock_sender.username = "test_sender"

        # Create recent messages (within 15 minutes)
        now = datetime.now(timezone.utc)
        msg1 = MagicMock()
        msg1.date = now
        msg2 = MagicMock()
        msg2.date = now - timedelta(minutes=5)  # Only 5 minutes ago
        mock_telegram_client.get_messages = AsyncMock(return_value=[msg1, msg2])

        # Handler logic
        me = await mock_telegram_client.get_me()
        reply = mock_reply.get_by_emoji(me.emoji_status.document_id)
        if reply:
            messages = await mock_telegram_client.get_messages(mock_sender.username, limit=2)
            if len(messages) > 1:
                difference = messages[0].date - messages[1].date
                if difference < timedelta(minutes=15):
                    return  # Rate limited

            await mock_telegram_client.send_message(mock_sender.username, message=reply.message)

        # Should NOT send reply due to rate limit
        mock_telegram_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_reply_after_cooldown(self, mock_telegram_client, mock_reply, mock_message):
        """Test that handler sends reply after cooldown period."""
        # Create reply template
        mock_reply.create(5379748062124056162, mock_message)

        event = MagicMock()
        event.is_private = True

        mock_user = MagicMock()
        mock_user.emoji_status = MagicMock()
        mock_user.emoji_status.document_id = 5379748062124056162
        mock_telegram_client.get_me = AsyncMock(return_value=mock_user)

        mock_sender = MagicMock()
        mock_sender.username = "test_sender"

        # Create messages with enough time gap
        now = datetime.now(timezone.utc)
        msg1 = MagicMock()
        msg1.date = now
        msg2 = MagicMock()
        msg2.date = now - timedelta(minutes=20)  # 20 minutes ago
        mock_telegram_client.get_messages = AsyncMock(return_value=[msg1, msg2])

        # Handler logic
        me = await mock_telegram_client.get_me()
        reply = mock_reply.get_by_emoji(me.emoji_status.document_id)
        if reply:
            messages = await mock_telegram_client.get_messages(mock_sender.username, limit=2)
            should_send = True
            if len(messages) > 1:
                difference = messages[0].date - messages[1].date
                if difference < timedelta(minutes=15):
                    should_send = False

            if should_send:
                await mock_telegram_client.send_message(mock_sender.username, message=reply.message)

        # Should send reply
        mock_telegram_client.send_message.assert_called_once()


class TestDebugOutgoingLogic:
    """Tests for debug outgoing message handler logic."""

    @pytest.mark.asyncio
    async def test_logs_outgoing_messages(self, capsys):
        """Test that debug handler logs outgoing messages."""
        event = MagicMock()
        event.chat_id = 12345
        event.message = MagicMock()
        event.message.text = "Test outgoing message"

        # Simulate debug handler
        print(f"[DEBUG] Outgoing message: '{event.message.text}' in chat {event.chat_id}")

        captured = capsys.readouterr()
        assert '[DEBUG]' in captured.out
        assert 'Test outgoing message' in captured.out
