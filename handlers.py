"""
Telegram event handlers for auto-reply bot.

Handles incoming/outgoing messages and commands.
"""
from telethon import events
from telethon.errors import ReactionInvalidError
from telethon.tl import types
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import MessageEntityCustomEmoji

from config import config
from logging_config import logger
from models import Reply, Settings
from services.autoreply_service import AutoReplyService
from services.notification_service import NotificationService

# Services initialized once
_autoreply_service = AutoReplyService(cooldown_minutes=config.autoreply_cooldown_minutes)
_notification_service = NotificationService(
    personal_tg_login=config.personal_tg_login,
    available_emoji_id=config.available_emoji_id,
    webhook_url=config.asap_webhook_url,
    webhook_timeout=config.webhook_timeout_seconds,
    webhook_method=config.asap_webhook_method
)


def register_handlers(client):
    """
    Register all Telegram event handlers on the client.

    Args:
        client: Telethon client instance
    """

    @client.on(events.NewMessage(outgoing=True))
    async def debug_outgoing(event):
        """Log all outgoing messages for debugging."""
        logger.debug(f"Outgoing: '{event.message.text}' in chat {event.chat_id}")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autoreply-settings\s*$"))
    async def select_settings_chat(event):
        """Handle /autoreply-settings command to set the settings chat."""
        chat_id = event.chat.id
        Settings.set_settings_chat_id(chat_id)
        logger.info(f"Settings chat set to: {chat_id}")

        await _send_reaction(client, event, '\u2705')  # ✅

        await client.send_message(
            entity=event.input_chat,
            message=(
                "✅ Этот чат выбран для настройки автоответчика.\n\n"
                "Доступные команды:\n"
                "• /set — ответом на сообщение, чтобы задать автоответ для текущего статуса\n"
                "• /set_for <эмодзи> — ответом на сообщение, чтобы задать автоответ для указанного эмодзи\n"
                "• /autoreply-off — отключить автоответчик"
            )
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autoreply-off\s*$"))
    async def disable_autoreply(event):
        """Handle /autoreply-off command to disable autoreply."""
        settings_chat_id = Settings.get_settings_chat_id()
        chat_id = event.chat.id

        if not _autoreply_service.is_settings_chat(chat_id, settings_chat_id):
            return

        Settings.set_settings_chat_id(None)
        logger.info("Autoreply disabled")

        await _send_reaction(client, event, '\u274c')  # ❌

        await client.send_message(
            entity=event.input_chat,
            message="❌ Автоответчик отключен. Используйте /autoreply-settings в любом чате, чтобы снова включить."
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/set_for\s+.*"))
    async def setup_response(event):
        """Handle /set_for command to set reply for specific emoji."""
        settings_chat_id = Settings.get_settings_chat_id()
        chat_id = event.chat.id

        if not _autoreply_service.is_settings_chat(chat_id, settings_chat_id):
            return

        if not event.reply_to:
            await client.send_message(
                entity=event.input_chat,
                message="Команда должна быть ответом на сообщение"
            )
            return

        msg_id = event.reply_to.reply_to_msg_id
        message = await client.get_messages(event.input_chat, ids=msg_id)

        entities = event.message.entities or []
        custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

        if len(custom_emojis) != 1:
            await client.send_message(
                entity=event.input_chat,
                reply_to=msg_id,
                message=(
                    f"Нужен 1 кастомный эмодзи Telegram (премиум), найдено: {len(custom_emojis)}. "
                    "Обычные эмодзи (🎄) не поддерживаются — используйте эмодзи из панели премиум-стикеров."
                )
            )
            return

        emoji = custom_emojis[0]
        Reply.create(emoji.document_id, message)
        logger.info(f"Reply set for emoji: {emoji.document_id}")

        await _send_reaction(client, event, '\U0001fae1')  # 🫡

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/set\s*$"))
    async def setup_response_current_status(event):
        """Handle /set command to set reply for current emoji status."""
        settings_chat_id = Settings.get_settings_chat_id()
        chat_id = event.chat.id

        if not _autoreply_service.is_settings_chat(chat_id, settings_chat_id):
            return

        if not event.reply_to:
            await client.send_message(
                entity=event.input_chat,
                message="Команда должна быть ответом на сообщение"
            )
            return

        me = await client.get_me()
        if not me.emoji_status:
            await client.send_message(
                entity=event.input_chat,
                message="❌ У вас не установлен эмодзи-статус. Установите статус в настройках Telegram и попробуйте снова."
            )
            return

        msg_id = event.reply_to.reply_to_msg_id
        message = await client.get_messages(event.input_chat, ids=msg_id)

        emoji_id = me.emoji_status.document_id
        Reply.create(emoji_id, message)
        logger.info(f"Reply set for current status emoji: {emoji_id}")

        await _send_reaction(client, event, '\U0001fae1')  # 🫡

        await client.send_message(
            entity=event.input_chat,
            message=f"✅ Автоответ установлен для текущего статуса (ID: {emoji_id})"
        )

    @client.on(events.NewMessage(incoming=True, pattern=".*[Aa][Ss][Aa][Pp].*"))
    async def asap_handler(event):
        """Handle incoming messages with ASAP keyword."""
        if not event.is_private:
            return

        me = await client.get_me()
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

        if not _notification_service.should_notify_asap(
            message_text=event.message.text or '',
            is_private=event.is_private,
            emoji_status_id=emoji_status_id
        ):
            return

        sender = await event.get_sender()
        sender_username = getattr(sender, 'username', None)
        sender_id = getattr(sender, 'id', 0)

        # Send notification to personal account
        notification_message = _notification_service.format_asap_message(sender_username, sender_id)
        await client.send_message(
            config.personal_tg_login,
            notification_message,
            formatting_entities=[MessageEntityCustomEmoji(offset=0, length=2, document_id=5379748062124056162)]
        )
        logger.info(f"ASAP notification sent for message from {sender_username or sender_id}")

        # Call webhook if configured
        if config.asap_webhook_url:
            await _notification_service.call_webhook(
                sender_username=sender_username,
                sender_id=sender_id,
                message_text=event.message.text or ''
            )

        await _send_reaction(client, event, '\U0001fae1')  # 🫡

    @client.on(events.NewMessage(incoming=True))
    async def new_messages(event):
        """Handle incoming messages for auto-reply."""
        if not event.is_private:
            return

        me = await client.get_me()
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

        reply = Reply.get_by_emoji(emoji_status_id) if emoji_status_id else None

        sender = await event.get_sender()
        sender_username = getattr(sender, 'username', None)
        sender_id = getattr(sender, 'id', 0)

        # Use username or ID for message lookup
        user_identifier = sender_username or sender_id
        if not user_identifier:
            logger.warning("Could not identify sender, skipping auto-reply")
            return

        # Get last messages for rate limiting
        try:
            messages = await client.get_messages(user_identifier, limit=2)
        except Exception as e:
            logger.warning(f"Could not get messages for rate limiting: {e}")
            messages = []

        if not _autoreply_service.should_send_reply(
            emoji_status_id=emoji_status_id,
            available_emoji_id=config.available_emoji_id,
            reply_exists=reply is not None,
            last_two_messages=messages
        ):
            return

        message = reply.message if reply else None
        if message is None:
            return

        await client.send_message(user_identifier, message=message)
        logger.info(f"Auto-reply sent to {user_identifier}")


async def _send_reaction(client, event, emoticon: str) -> None:
    """Send a reaction to a message, handling errors gracefully."""
    try:
        # Use get_input_chat() for incoming messages where input_chat may be None
        input_chat = event.input_chat
        if input_chat is None:
            input_chat = await event.get_input_chat()
        if input_chat is None:
            logger.debug(f"Cannot get input_chat for reaction in chat {event.chat_id}")
            return

        await client(SendReactionRequest(
            peer=input_chat,
            msg_id=event.message.id,
            reaction=[types.ReactionEmoji(emoticon=emoticon)]
        ))
    except ReactionInvalidError:
        logger.debug(f"Reaction not allowed in chat {event.chat_id}")
    except Exception as e:
        logger.warning(f"Failed to send reaction: {e}")
