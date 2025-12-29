"""
Notification service for handling urgent message alerts.
"""
from typing import Optional, Any
import aiohttp

from logging_config import get_logger
from models import Schedule

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
        webhook_url: Optional[str] = None,
        webhook_timeout: int = 10
    ):
        """
        Initialize the notification service.

        Args:
            personal_tg_login: Telegram username/ID to send notifications to
            webhook_url: Optional URL to call for ASAP alerts
            webhook_timeout: Timeout for webhook calls in seconds
        """
        self.personal_tg_login = personal_tg_login
        self.webhook_url = webhook_url
        self.webhook_timeout = webhook_timeout

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

        # User must have emoji status set
        if emoji_status_id is None:
            return False

        # Get work emoji from schedule - if not set, ASAP always works
        work_emoji_id = Schedule.get_work_emoji_id()
        if work_emoji_id is None:
            # No work schedule configured - ASAP notifications always work
            return True

        # User is "available" (has work emoji status)
        if emoji_status_id == work_emoji_id:
            logger.debug("User is available (work emoji), not sending ASAP notification")
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

        # Format sender name
        if sender_username:
            sender_name = f"@{sender_username}"
        else:
            sender_name = f"ID:{sender_id}"

        payload = {
            'sender_username': sender_username,
            'sender_id': sender_id,
            'sender_name': sender_name,
            'message': message_text,
            'formatted_message': f"Срочный призыв от {sender_name}: {message_text}",
            'title': f"❗ Срочное сообщение от {sender_name}",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=self.webhook_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
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
