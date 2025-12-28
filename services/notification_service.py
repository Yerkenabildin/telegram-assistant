"""
Notification service for handling urgent message alerts.
"""
from typing import Optional, Any
import aiohttp

from logging_config import get_logger

logger = get_logger('notification')


class NotificationService:
    """
    Service for managing notifications (ASAP alerts, webhooks).

    Handles:
    - Detecting urgent messages
    - Sending notifications to personal account
    - Calling external webhooks
    """

    def __init__(
        self,
        personal_tg_login: str,
        available_emoji_id: int,
        webhook_url: Optional[str] = None,
        webhook_timeout: int = 10,
        webhook_method: str = 'POST'
    ):
        """
        Initialize the notification service.

        Args:
            personal_tg_login: Telegram username/ID to send notifications to
            available_emoji_id: Emoji ID that indicates "available" status
            webhook_url: Optional URL to call for ASAP alerts
            webhook_timeout: Timeout for webhook calls in seconds
            webhook_method: HTTP method for webhook calls (POST or GET)
        """
        self.personal_tg_login = personal_tg_login
        self.available_emoji_id = available_emoji_id
        self.webhook_url = webhook_url
        self.webhook_timeout = webhook_timeout
        self.webhook_method = webhook_method.upper()

    def should_notify_asap(
        self,
        message_text: str,
        is_private: bool,
        emoji_status_id: Optional[int]
    ) -> bool:
        """
        Check if message should trigger an ASAP notification.

        Args:
            message_text: The message content
            is_private: Whether the message is in a private chat
            emoji_status_id: Current user's emoji status ID

        Returns:
            True if ASAP notification should be sent
        """
        # Only private messages
        if not is_private:
            return False

        # Check for ASAP keyword (case-insensitive)
        if 'asap' not in message_text.lower():
            return False

        # User must not be "available"
        if emoji_status_id is None:
            return False

        if emoji_status_id == self.available_emoji_id:
            logger.debug("User is available, not sending ASAP notification")
            return False

        return True

    def format_asap_message(self, sender_username: Optional[str], sender_id: int) -> str:
        """
        Format the ASAP notification message.

        Args:
            sender_username: Sender's username (may be None)
            sender_id: Sender's numeric ID

        Returns:
            Formatted notification message
        """
        if sender_username:
            return f'❗️Срочный призыв от @{sender_username}'
        else:
            return f'❗️Срочный призыв от пользователя {sender_id}'

    async def call_webhook(
        self,
        sender_username: Optional[str],
        sender_id: int,
        message_text: str
    ) -> bool:
        """
        Call the configured webhook with notification data.

        Args:
            sender_username: Sender's username
            sender_id: Sender's numeric ID
            message_text: The message content

        Returns:
            True if webhook call succeeded
        """
        if not self.webhook_url:
            return False

        payload = {
            'sender_username': sender_username,
            'sender_id': sender_id,
            'message': message_text,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=self.webhook_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if self.webhook_method == 'GET':
                    # For GET, pass data as query parameters
                    async with session.get(self.webhook_url, params=payload) as response:
                        success = response.status == 200
                        logger.info(
                            f"Webhook GET to {self.webhook_url}: "
                            f"status={response.status}, success={success}"
                        )
                        return success
                else:
                    # Default to POST with JSON body
                    async with session.post(self.webhook_url, json=payload) as response:
                        success = response.status == 200
                        logger.info(
                            f"Webhook POST to {self.webhook_url}: "
                            f"status={response.status}, success={success}"
                        )
                        return success
        except asyncio.TimeoutError:
            logger.error(f"Webhook timeout after {self.webhook_timeout}s: {self.webhook_url}")
            return False
        except Exception as e:
            logger.error(f"Webhook call failed: {e}")
            return False


# Need to import asyncio for TimeoutError
import asyncio
