"""
Notification service for handling urgent message alerts.
"""
from typing import Optional, Any
from datetime import datetime, timedelta
import aiohttp

from logging_config import get_logger
from models import Schedule, Settings

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
        # Track last ASAP notification time per sender_id
        self._last_asap_notification: dict[int, datetime] = {}

    def check_asap_cooldown(self, sender_id: int) -> bool:
        """
        Check if enough time has passed since last ASAP notification from this sender.

        Args:
            sender_id: Sender's numeric ID

        Returns:
            True if notification can be sent (cooldown passed or first notification)
        """
        cooldown_minutes = Settings.get_asap_cooldown_minutes()
        now = datetime.now()

        last_time = self._last_asap_notification.get(sender_id)
        if last_time is None:
            return True

        time_diff = now - last_time
        if time_diff < timedelta(minutes=cooldown_minutes):
            logger.debug(
                f"ASAP cooldown active for sender {sender_id}: "
                f"{time_diff.total_seconds():.0f}s < {cooldown_minutes * 60}s"
            )
            return False

        return True

    def record_asap_notification(self, sender_id: int) -> None:
        """
        Record that an ASAP notification was sent for this sender.

        Args:
            sender_id: Sender's numeric ID
        """
        self._last_asap_notification[sender_id] = datetime.now()
        logger.debug(f"Recorded ASAP notification for sender {sender_id}")

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

        # Get work emoji from schedule - if user has work emoji, they are "available"
        work_emoji_id = Schedule.get_work_emoji_id()
        if work_emoji_id and emoji_status_id == work_emoji_id:
            logger.debug("User is available (work emoji), not sending ASAP notification")
            return False

        # Check if user is in a meeting
        active_meeting = Schedule.get_active_meeting()
        if active_meeting and emoji_status_id == int(active_meeting.emoji_id):
            logger.debug("User is in a meeting, not sending ASAP notification")
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
        message_text: str,
        webhook_url: Optional[str] = None
    ) -> bool:
        """
        Call the configured webhook with notification data.

        Args:
            sender_username: Sender's username
            sender_id: Sender's numeric ID
            message_text: The message content
            webhook_url: Optional webhook URL to use (overrides instance default)

        Returns:
            True if webhook call succeeded
        """
        url = webhook_url or self.webhook_url
        if not url:
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
                async with session.post(url, json=payload) as response:
                    success = response.status == 200
                    logger.info(
                        f"Webhook POST to {url}: "
                        f"status={response.status}, success={success}"
                    )
                    return success
        except asyncio.TimeoutError:
            logger.error(f"Webhook timeout after {self.webhook_timeout}s: {url}")
            return False
        except Exception as e:
            logger.error(f"Webhook call failed: {e}")
            return False


# Need to import asyncio for TimeoutError
import asyncio
