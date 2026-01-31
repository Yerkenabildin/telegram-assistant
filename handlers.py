"""
Telegram event handlers for auto-reply bot.

Handles incoming messages for auto-reply and ASAP notifications.
All configuration is done via the bot interface (bot_handlers.py).
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from telethon import events
from telethon.errors import ReactionInvalidError
from telethon.tl import types
from telethon.tl.functions.messages import SendReactionRequest, GetPeerDialogsRequest
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
    available_emoji_id=config.available_emoji_id,
    vip_usernames=config.vip_usernames
)

# Bot client for sending online notifications (set via register_handlers)
_bot_client = None
_user_client = None


@dataclass
class PendingMention:
    """Represents a pending mention notification waiting to be sent."""
    chat_id: int
    message_id: int
    notification: str
    is_urgent: bool
    scheduled_time: datetime
    chat_title: str
    sender_name: str


# Storage for pending mentions (key: "chat_id:message_id")
_pending_mentions: Dict[str, PendingMention] = {}
_pending_checker_started = False


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


async def _get_reply_chain(client, chat_id: int, message, max_depth: int = 5) -> list:
    """
    Get the chain of reply messages leading to this message.

    Walks backwards through reply_to_msg_id to build the conversation chain.

    Args:
        client: Telethon client
        chat_id: Chat ID
        message: Starting message (the mention message)
        max_depth: Maximum number of messages to fetch in chain

    Returns:
        List of messages in chronological order (oldest first)
    """
    chain = []
    current_msg = message
    depth = 0

    while depth < max_depth:
        reply_to_id = getattr(current_msg, 'reply_to_msg_id', None)
        if not reply_to_id:
            # Also check reply_to.reply_to_msg_id for newer API
            reply_to = getattr(current_msg, 'reply_to', None)
            if reply_to:
                reply_to_id = getattr(reply_to, 'reply_to_msg_id', None)

        if not reply_to_id:
            break

        try:
            # Fetch the replied-to message
            replied_msg = await client.get_messages(chat_id, ids=reply_to_id)
            if replied_msg:
                chain.append(replied_msg)
                current_msg = replied_msg
                depth += 1
            else:
                break
        except Exception as e:
            logger.warning(f"Failed to fetch reply message {reply_to_id}: {e}")
            break

    # Reverse to get chronological order (oldest first)
    chain.reverse()
    return chain


async def _is_message_read(client, chat_id: int, message_id: int) -> bool:
    """
    Check if a message in a chat has been read.

    Uses GetPeerDialogsRequest to get read_inbox_max_id for the chat.

    Args:
        client: Telethon client
        chat_id: Chat ID
        message_id: Message ID to check

    Returns:
        True if message has been read, False otherwise
    """
    try:
        peer = await client.get_input_entity(chat_id)
        result = await client(GetPeerDialogsRequest(peers=[peer]))

        if result.dialogs:
            dialog = result.dialogs[0]
            read_inbox_max_id = dialog.read_inbox_max_id
            logger.debug(f"Chat {chat_id}: read_inbox_max_id={read_inbox_max_id}, message_id={message_id}")
            return message_id <= read_inbox_max_id

        return False
    except Exception as e:
        logger.warning(f"Failed to check if message {message_id} in chat {chat_id} was read: {e}")
        return False


async def _process_pending_mentions():
    """
    Background task to process pending mention notifications.

    Runs every 30 seconds, checks each pending mention:
    - If scheduled time has passed and message not read -> send notification
    - If message was read -> remove from pending
    """
    global _pending_checker_started

    if _pending_checker_started:
        return

    _pending_checker_started = True
    logger.info("Starting pending mentions checker...")

    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds

            if not _pending_mentions:
                continue

            now = datetime.now()
            to_remove = []

            for key, mention in list(_pending_mentions.items()):
                # Check if it's time to process this mention
                if now < mention.scheduled_time:
                    continue

                # Check if message was read
                if _user_client:
                    was_read = await _is_message_read(
                        _user_client,
                        mention.chat_id,
                        mention.message_id
                    )

                    if was_read:
                        logger.info(
                            f"Mention in '{mention.chat_title}' from {mention.sender_name} "
                            f"was read, skipping notification"
                        )
                        to_remove.append(key)
                        continue

                # Message not read, send notification via bot
                if _bot_client:
                    try:
                        from bot_handlers import get_owner_id
                        owner_id = get_owner_id()
                        if owner_id:
                            await _bot_client.send_message(
                                owner_id,
                                mention.notification,
                                silent=not mention.is_urgent
                            )
                            logger.info(
                                f"Delayed mention notification sent for '{mention.chat_title}' "
                                f"(urgent={mention.is_urgent})"
                            )
                    except Exception as e:
                        logger.error(f"Failed to send delayed notification: {e}")

                to_remove.append(key)

            # Remove processed mentions
            for key in to_remove:
                _pending_mentions.pop(key, None)

        except asyncio.CancelledError:
            logger.info("Pending mentions checker stopped")
            break
        except Exception as e:
            logger.error(f"Error in pending mentions checker: {e}")


def _schedule_pending_mention(
    chat_id: int,
    message_id: int,
    notification: str,
    is_urgent: bool,
    chat_title: str,
    sender_name: str
):
    """
    Schedule a mention notification to be sent after delay.

    Args:
        chat_id: Chat where mention occurred
        message_id: Message ID with mention
        notification: Formatted notification text
        is_urgent: Whether this is urgent
        chat_title: Title of the chat
        sender_name: Name of person who mentioned
    """
    key = f"{chat_id}:{message_id}"
    delay_minutes = config.online_mention_delay_minutes

    _pending_mentions[key] = PendingMention(
        chat_id=chat_id,
        message_id=message_id,
        notification=notification,
        is_urgent=is_urgent,
        scheduled_time=datetime.now() + timedelta(minutes=delay_minutes),
        chat_title=chat_title,
        sender_name=sender_name
    )

    logger.info(
        f"Scheduled mention notification for '{chat_title}' from {sender_name} "
        f"in {delay_minutes} minutes"
    )


def register_handlers(client, bot=None):
    """
    Register all Telegram event handlers on the client.

    Args:
        client: Telethon client instance
        bot: Telethon bot client for sending online mention notifications
    """
    global _bot_client, _user_client
    _bot_client = bot
    _user_client = client

    # Start background task for pending mentions
    asyncio.get_event_loop().create_task(_process_pending_mentions())

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
        """Handle mentions in group chats - notify both when online and offline."""
        # Only group chats (not private)
        if event.is_private:
            return

        # Check if this message mentions the current user
        me = await client.get_me()
        if not _is_user_mentioned(event.message, me.id, me.username):
            return

        # Check if user is "online" (has available/work emoji)
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None
        is_online = not _mention_service.should_notify(emoji_status_id)

        # Get chat info
        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', 'Unknown chat')

        # Get sender info
        sender = await event.get_sender()
        if getattr(sender, 'bot', False):
            return  # Ignore bot mentions

        sender_name = _get_display_name(sender)
        sender_username = getattr(sender, 'username', None)

        logger.info(f"Mention detected in '{chat_title}' from {sender_name} (online={is_online})")

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

        # Fetch reply chain if this is a reply
        reply_chain = []
        if event.message.reply_to_msg_id:
            try:
                reply_chain = await _get_reply_chain(client, event.chat_id, event.message, max_depth=5)
                if reply_chain:
                    logger.debug(f"Found reply chain with {len(reply_chain)} messages")
            except Exception as e:
                logger.warning(f"Failed to fetch reply chain: {e}")

        # Generate summary (try AI first, fallback to keywords)
        summary, ai_urgency = await _mention_service.generate_summary_with_ai(
            messages, event.message, chat_title, reply_chain=reply_chain
        )

        # Check urgency: VIP sender always urgent, then AI, then keywords
        is_vip = _mention_service.is_vip_sender(sender_username)
        if is_vip:
            is_urgent = True
            logger.debug(f"Urgency from VIP sender: {sender_username}")
        elif ai_urgency is not None:
            is_urgent = ai_urgency
            logger.debug(f"Urgency from AI: {is_urgent}")
        else:
            is_urgent = _mention_service.is_urgent(messages)
            logger.debug(f"Urgency from keywords: {is_urgent}")

        # Format notification with online/offline indicator
        if is_online:
            header_suffix = " (вы онлайн)"
        else:
            header_suffix = ""

        notification = _mention_service.format_notification(
            chat_title=chat_title,
            chat_id=event.chat_id,
            sender_name=sender_name,
            sender_username=sender_username,
            summary=summary,
            is_urgent=is_urgent,
            message_id=event.message.id
        )

        # Add online indicator to notification header
        if is_online and not is_urgent:
            notification = notification.replace("📢 Упоминание в группе", "📢 Упоминание в группе (вы онлайн)")
        elif is_online and is_urgent:
            notification = notification.replace("🚨 Срочное упоминание в группе!", "🚨 Срочное упоминание (вы онлайн)!")

        # Send notification
        # - Offline: send immediately via user client
        # - Online + VIP urgent: send immediately via bot
        # - Online + not VIP: schedule with delay (check if read before sending)
        try:
            if is_online and _bot_client:
                if is_vip:
                    # VIP mentions are always sent immediately
                    from bot_handlers import get_owner_id
                    owner_id = get_owner_id()
                    if owner_id:
                        await _bot_client.send_message(
                            owner_id,
                            notification,
                            silent=False  # VIP is always loud
                        )
                        logger.info(f"VIP mention notification sent immediately via bot")
                else:
                    # Non-VIP online mentions: schedule with delay
                    _schedule_pending_mention(
                        chat_id=event.chat_id,
                        message_id=event.message.id,
                        notification=notification,
                        is_urgent=is_urgent,
                        chat_title=chat_title,
                        sender_name=sender_name
                    )
            else:
                # Offline or no bot: send immediately via user client
                await client.send_message(
                    config.personal_tg_login,
                    notification,
                    silent=not is_urgent
                )
                logger.info(f"Mention notification sent via user client (offline, urgent={is_urgent})")
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
