"""
Auto-reply service for handling automatic message responses.
"""
from datetime import datetime, timedelta
from typing import Optional, Any

from logging_config import get_logger

logger = get_logger('autoreply')


class AutoReplyService:
    """
    Service for managing auto-reply logic.

    Handles:
    - Checking if auto-reply should be sent (rate limiting)
    - Retrieving reply templates
    - Managing settings chat
    """

    def __init__(self, cooldown_minutes: int = 15):
        """
        Initialize the auto-reply service.

        Args:
            cooldown_minutes: Minimum minutes between replies to same user
        """
        self.cooldown = timedelta(minutes=cooldown_minutes)

    def should_send_reply(
        self,
        emoji_status_id: Optional[int],
        available_emoji_id: int,
        reply_exists: bool,
        last_outgoing_message: Optional[Any]
    ) -> bool:
        """
        Determine if an auto-reply should be sent.

        Args:
            emoji_status_id: Current user's emoji status ID (None if not set)
            available_emoji_id: Emoji ID that indicates "available" status
            reply_exists: Whether a reply template exists for this emoji
            last_outgoing_message: Last outgoing message in conversation (for rate limiting)

        Returns:
            True if auto-reply should be sent
        """
        # No emoji status set
        if emoji_status_id is None:
            logger.debug("No emoji status set, skipping auto-reply")
            return False

        # User is "available" (special emoji)
        if emoji_status_id == available_emoji_id:
            logger.debug("User is available (emoji matches available_emoji_id)")
            return False

        # No reply template configured
        if not reply_exists:
            logger.debug(f"No reply template for emoji {emoji_status_id}")
            return False

        # Rate limiting check
        if not self._check_rate_limit(last_outgoing_message):
            logger.debug("Rate limit not met, skipping auto-reply")
            return False

        return True

    def _check_rate_limit(self, last_outgoing_message: Optional[Any]) -> bool:
        """
        Check if enough time has passed since last outgoing message.

        Args:
            last_outgoing_message: Last outgoing message in conversation

        Returns:
            True if rate limit allows sending (no recent outgoing message)
        """
        if last_outgoing_message is None:
            return True

        try:
            now = datetime.now(last_outgoing_message.date.tzinfo)
            time_diff = now - last_outgoing_message.date
            if time_diff < self.cooldown:
                logger.debug(f"Rate limit: {time_diff} < {self.cooldown}")
                return False
        except (AttributeError, TypeError) as e:
            logger.warning(f"Could not check rate limit: {e}")
            return True

        return True

    def is_settings_chat(self, chat_id: int, settings_chat_id: Optional[int]) -> bool:
        """
        Check if given chat is the configured settings chat.

        Args:
            chat_id: Current chat ID
            settings_chat_id: Configured settings chat ID

        Returns:
            True if chat is the settings chat
        """
        if settings_chat_id is None:
            return False
        return chat_id == settings_chat_id
