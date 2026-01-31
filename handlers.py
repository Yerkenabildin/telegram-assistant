"""
Telegram event handlers for auto-reply bot.

Handles incoming messages for auto-reply and ASAP notifications.
All configuration is done via the bot interface (bot_handlers.py).
"""
from telethon import events
from telethon.errors import ReactionInvalidError
from telethon.tl import types
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import MessageEntityCustomEmoji

from config import config
from logging_config import logger
from models import Reply
from services.autoreply_service import AutoReplyService
from services.notification_service import NotificationService
from services.mention_service import MentionService

# Services initialized once
_autoreply_service = AutoReplyService(cooldown_minutes=config.autoreply_cooldown_minutes)
_notification_service = NotificationService(
    personal_tg_login=config.personal_tg_login,
    webhook_url=config.asap_webhook_url,
    webhook_timeout=config.webhook_timeout_seconds
)
_mention_service = MentionService(
    message_limit=config.mention_message_limit,
    time_limit_minutes=config.mention_time_limit_minutes,
    available_emoji_id=config.available_emoji_id
)


def _is_user_mentioned(message, user_id: int, username: str = None) -> bool:
    """
    Check if message mentions the specified user.

    Checks for:
    - MessageEntityMention (@username)
    - MessageEntityMentionName (inline mention with user_id)
    - InputMessageEntityMentionName

    Args:
        message: Telethon Message object
        user_id: User's numeric ID
        username: User's username (without @)

    Returns:
        True if user is mentioned in the message
    """
    if not message.entities:
        return False

    text = message.text or ''

    for entity in message.entities:
        # Check @username mention
        if isinstance(entity, types.MessageEntityMention):
            # Extract the mentioned username from text
            mentioned = text[entity.offset:entity.offset + entity.length]
            if mentioned.startswith('@'):
                mentioned = mentioned[1:]
            if username and mentioned.lower() == username.lower():
                return True

        # Check inline mention by user_id
        elif isinstance(entity, types.MessageEntityMentionName):
            if entity.user_id == user_id:
                return True

        # Check input mention name (less common)
        elif hasattr(types, 'InputMessageEntityMentionName'):
            if isinstance(entity, types.InputMessageEntityMentionName):
                if hasattr(entity, 'user_id') and entity.user_id == user_id:
                    return True

    return False


def _get_display_name(user) -> str:
    """
    Get display name for a user.

    Args:
        user: Telethon User object

    Returns:
        Display name (first name + last name, or username, or 'Unknown')
    """
    if not user:
        return 'Unknown'

    first_name = getattr(user, 'first_name', '') or ''
    last_name = getattr(user, 'last_name', '') or ''

    if first_name or last_name:
        return f"{first_name} {last_name}".strip()

    username = getattr(user, 'username', None)
    if username:
        return f"@{username}"

    return 'Unknown'


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

    @client.on(events.NewMessage(incoming=True, pattern=".*[Aa][Ss][Aa][Pp].*"))
    async def asap_handler(event):
        """Handle incoming messages with ASAP keyword."""
        if not event.is_private:
            return

        sender = await event.get_sender()
        if getattr(sender, 'bot', False):
            return

        me = await client.get_me()
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

        if not _notification_service.should_notify_asap(
            message_text=event.message.text or '',
            is_private=event.is_private,
            emoji_status_id=emoji_status_id
        ):
            return

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
    async def group_mention_handler(event):
        """Handle mentions in group chats when user is offline."""
        # Only group chats (not private)
        if event.is_private:
            return

        # Check if this message mentions the current user
        me = await client.get_me()
        if not _is_user_mentioned(event.message, me.id, me.username):
            return

        # Check if user is "offline" (not available emoji)
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None
        if not _mention_service.should_notify(emoji_status_id):
            logger.debug(f"User is online, not sending mention notification")
            return

        # Get chat info
        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', 'Unknown chat')

        # Get sender info
        sender = await event.get_sender()
        if getattr(sender, 'bot', False):
            return  # Ignore bot mentions

        sender_name = _get_display_name(sender)
        sender_username = getattr(sender, 'username', None)

        logger.info(f"Mention detected in '{chat_title}' from {sender_name}")

        # Fetch recent messages for context
        try:
            messages = await client.get_messages(
                event.chat_id,
                limit=_mention_service.message_limit
            )
            # Filter by time
            messages = _mention_service.filter_messages_by_time(messages)
        except Exception as e:
            logger.warning(f"Failed to fetch messages for context: {e}")
            messages = [event.message]

        # Generate summary
        summary = _mention_service.generate_summary(messages, event.message)

        # Check urgency
        is_urgent = _mention_service.is_urgent(messages)

        # Format notification
        notification = _mention_service.format_notification(
            chat_title=chat_title,
            chat_id=event.chat_id,
            sender_name=sender_name,
            sender_username=sender_username,
            summary=summary,
            is_urgent=is_urgent
        )

        # Send notification (silent if not urgent)
        try:
            await client.send_message(
                config.personal_tg_login,
                notification,
                silent=not is_urgent  # Silent notification if not urgent
            )
            logger.info(f"Mention notification sent (urgent={is_urgent})")
        except Exception as e:
            logger.error(f"Failed to send mention notification: {e}")

    @client.on(events.NewMessage(incoming=True))
    async def new_messages(event):
        """Handle incoming messages for auto-reply."""
        if not event.is_private:
            return

        sender = await event.get_sender()
        if getattr(sender, 'bot', False):
            return

        me = await client.get_me()
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

        reply = Reply.get_by_emoji(emoji_status_id) if emoji_status_id else None

        sender_username = getattr(sender, 'username', None)
        sender_id = getattr(sender, 'id', 0)

        # Use username or ID for message lookup
        user_identifier = sender_username or sender_id
        if not user_identifier:
            logger.warning("Could not identify sender, skipping auto-reply")
            return

        # Get last outgoing message for rate limiting
        try:
            messages = await client.get_messages(user_identifier, limit=10)
            last_outgoing = next((m for m in messages if m.out), None)
        except Exception as e:
            logger.warning(f"Could not get messages for rate limiting: {e}")
            last_outgoing = None

        if not _autoreply_service.should_send_reply(
            emoji_status_id=emoji_status_id,
            reply_exists=reply is not None,
            last_outgoing_message=last_outgoing
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
