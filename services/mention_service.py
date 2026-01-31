"""
Mention notification service for handling group chat mentions.

Sends notifications when user is mentioned in group chats while "offline".
"""
from datetime import datetime, timedelta
from typing import Optional, Any, List, Tuple
import re

from logging_config import get_logger
from models import Schedule

logger = get_logger('mention')

# Urgent keywords that trigger notification with sound
URGENT_KEYWORDS = [
    'asap', 'срочно', 'urgent', 'emergency', 'помогите', 'help',
    'важно', 'critical', 'блокер', 'blocker', 'падает', 'упал',
    'прод', 'prod', 'авария', 'incident', 'горит'
]

# Compile regex pattern for urgent detection (case-insensitive)
URGENT_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(kw) for kw in URGENT_KEYWORDS) + r')\b',
    re.IGNORECASE
)


class MentionService:
    """
    Service for handling group chat mention notifications.

    Handles:
    - Detecting mentions while user is offline
    - Fetching context messages
    - Generating summaries
    - Determining notification urgency
    """

    def __init__(
        self,
        message_limit: int = 50,
        time_limit_minutes: int = 30,
        available_emoji_id: Optional[int] = None
    ):
        """
        Initialize the mention service.

        Args:
            message_limit: Maximum number of messages to fetch for context
            time_limit_minutes: Maximum age of messages to include in context
            available_emoji_id: Emoji ID that indicates user is "online/available"
        """
        self.message_limit = message_limit
        self.time_limit = timedelta(minutes=time_limit_minutes)
        self.available_emoji_id = available_emoji_id

    def should_notify(self, emoji_status_id: Optional[int]) -> bool:
        """
        Check if notification should be sent based on user's emoji status.

        User is considered "offline" if:
        - No emoji status set
        - Emoji status is different from "available" emoji
        - Work emoji from schedule is set and current status doesn't match

        Args:
            emoji_status_id: Current user's emoji status ID

        Returns:
            True if user is "offline" and should be notified
        """
        # If available emoji is configured and user has it - they're online
        if self.available_emoji_id and emoji_status_id == self.available_emoji_id:
            logger.debug(f"User has available emoji {emoji_status_id}, not notifying")
            return False

        # Check work emoji from schedule - if matches, user is "available"
        work_emoji_id = Schedule.get_work_emoji_id()
        if work_emoji_id is not None and emoji_status_id == work_emoji_id:
            logger.debug(f"User has work emoji {emoji_status_id}, not notifying")
            return False

        return True

    def is_urgent(self, messages: List[Any]) -> bool:
        """
        Check if mention context contains urgent keywords.

        Args:
            messages: List of message objects with text attribute

        Returns:
            True if any message contains urgent keywords
        """
        for msg in messages:
            text = getattr(msg, 'text', '') or ''
            if URGENT_PATTERN.search(text):
                logger.debug(f"Urgent keyword found in message: {text[:50]}...")
                return True
        return False

    def filter_messages_by_time(
        self,
        messages: List[Any],
        reference_time: Optional[datetime] = None
    ) -> List[Any]:
        """
        Filter messages to only include those within time limit.

        Args:
            messages: List of message objects with date attribute
            reference_time: Reference time (default: now)

        Returns:
            Filtered list of messages within time limit
        """
        if reference_time is None:
            # Use timezone from first message if available
            if messages and hasattr(messages[0], 'date') and messages[0].date:
                reference_time = datetime.now(messages[0].date.tzinfo)
            else:
                reference_time = datetime.now()

        cutoff_time = reference_time - self.time_limit
        filtered = []

        for msg in messages:
            msg_date = getattr(msg, 'date', None)
            if msg_date and msg_date >= cutoff_time:
                filtered.append(msg)

        return filtered

    def generate_summary(
        self,
        messages: List[Any],
        mention_message: Any,
        max_context_messages: int = 5
    ) -> str:
        """
        Generate a short summary of the mention context.

        Extracts the mention message and a few preceding messages
        to provide context about why the user was mentioned.

        Args:
            messages: List of messages (newest first)
            mention_message: The message that contains the mention
            max_context_messages: Maximum messages to include in summary

        Returns:
            Summary text
        """
        # Find mention message position and get context
        mention_text = getattr(mention_message, 'text', '') or ''

        # Get messages before the mention for context
        context_msgs = []
        found_mention = False

        for msg in messages:
            if msg.id == mention_message.id:
                found_mention = True
                continue
            if found_mention and len(context_msgs) < max_context_messages:
                text = getattr(msg, 'text', '') or ''
                if text.strip():
                    context_msgs.append(text)

        # Build summary
        lines = []

        # Add context messages (oldest first)
        if context_msgs:
            lines.append("Контекст:")
            for text in reversed(context_msgs[-3:]):  # Last 3 context messages
                # Truncate long messages
                if len(text) > 100:
                    text = text[:100] + "..."
                lines.append(f"  > {text}")

        # Add the mention message
        lines.append("\nСообщение с упоминанием:")
        if len(mention_text) > 200:
            mention_text = mention_text[:200] + "..."
        lines.append(f"  {mention_text}")

        return "\n".join(lines)

    def format_notification(
        self,
        chat_title: str,
        chat_id: int,
        sender_name: str,
        sender_username: Optional[str],
        summary: str,
        is_urgent: bool
    ) -> str:
        """
        Format the notification message.

        Args:
            chat_title: Title of the group chat
            chat_id: ID of the chat
            sender_name: Display name of the person who mentioned
            sender_username: Username of the sender (may be None)
            summary: Generated summary of context
            is_urgent: Whether this is an urgent mention

        Returns:
            Formatted notification message
        """
        # Header with urgency indicator
        if is_urgent:
            header = "🚨 Срочное упоминание в группе!"
        else:
            header = "📢 Упоминание в группе"

        # Sender info
        if sender_username:
            sender_info = f"@{sender_username} ({sender_name})"
        else:
            sender_info = sender_name

        # Build message
        lines = [
            header,
            "",
            f"📍 Чат: {chat_title}",
            f"👤 Призвал: {sender_info}",
            "",
            summary,
        ]

        # Add chat link if possible
        # Note: Private groups don't have public links
        if chat_id:
            lines.append("")
            lines.append(f"🔗 Открыть чат: tg://resolve?domain=c/{str(chat_id).replace('-100', '')}")

        return "\n".join(lines)

    def get_chat_link(self, chat_id: int, message_id: int) -> str:
        """
        Generate a deep link to the specific message in a chat.

        Args:
            chat_id: Chat ID (may be negative for groups)
            message_id: Message ID

        Returns:
            Deep link URL
        """
        # Convert supergroup/channel ID format
        if chat_id < 0:
            # Remove -100 prefix for supergroups
            chat_id_str = str(chat_id)
            if chat_id_str.startswith('-100'):
                chat_id_str = chat_id_str[4:]
            else:
                chat_id_str = chat_id_str[1:]  # Remove just the minus
            return f"tg://privatepost?channel={chat_id_str}&post={message_id}"
        else:
            return f"tg://privatepost?channel={chat_id}&post={message_id}"
