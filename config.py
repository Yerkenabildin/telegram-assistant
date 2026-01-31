"""
Centralized configuration for telegram-assistant.

All configuration values are loaded from environment variables with sensible defaults.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Telegram API credentials (required)
    api_id: int = field(default_factory=lambda: int(os.environ.get('API_ID', 0)))
    api_hash: str = field(default_factory=lambda: os.environ.get('API_HASH', ''))

    # Personal account for notifications
    personal_tg_login: str = field(default_factory=lambda: os.environ.get('PERSONAL_TG_LOGIN', ''))

    # Optional webhook URL for ASAP notifications
    asap_webhook_url: Optional[str] = field(
        default_factory=lambda: os.environ.get('ASAP_WEBHOOK_URL') or None
    )

    # Web server settings
    host: str = field(default_factory=lambda: os.environ.get('HOST', '0.0.0.0'))
    port: int = field(default_factory=lambda: int(os.environ.get('PORT', 5050)))
    secret_key: str = field(
        default_factory=lambda: os.environ.get('SECRET_KEY', os.urandom(24).hex())
    )
    script_name: str = field(
        default_factory=lambda: os.environ.get('SCRIPT_NAME', '').rstrip('/')
    )

    # Rate limiting
    autoreply_cooldown_minutes: int = field(
        default_factory=lambda: int(os.environ.get('AUTOREPLY_COOLDOWN_MINUTES', 30))
    )

    # Timeouts
    webhook_timeout_seconds: int = field(
        default_factory=lambda: int(os.environ.get('WEBHOOK_TIMEOUT_SECONDS', 10))
    )

    # Storage paths
    db_path: str = field(default_factory=lambda: os.environ.get('DB_PATH', './storage/database.db'))
    session_path: str = field(default_factory=lambda: os.environ.get('SESSION_PATH', './storage/session'))

    # Timezone for schedule (e.g., 'Europe/Moscow', 'UTC')
    timezone: str = field(default_factory=lambda: os.environ.get('TIMEZONE', 'Europe/Moscow'))

    # API token for meeting endpoint (optional, if not set - no auth required)
    meeting_api_token: Optional[str] = field(
        default_factory=lambda: os.environ.get('MEETING_API_TOKEN') or None
    )

    # Bot token for control interface (optional, get from @BotFather)
    bot_token: Optional[str] = field(
        default_factory=lambda: os.environ.get('BOT_TOKEN') or None
    )

    # Allowed username for bot authentication (optional, if not set - no restriction)
    # Only this username can authenticate via bot
    allowed_username: Optional[str] = field(
        default_factory=lambda: os.environ.get('ALLOWED_USERNAME') or None
    )

    # Mention notifications settings
    # Emoji ID that indicates user is "available/online" (won't get mention notifications)
    available_emoji_id: Optional[int] = field(
        default_factory=lambda: int(os.environ.get('AVAILABLE_EMOJI_ID', 0)) or None
    )

    # Maximum number of messages to fetch for context
    mention_message_limit: int = field(
        default_factory=lambda: int(os.environ.get('MENTION_MESSAGE_LIMIT', 50))
    )

    # Maximum age of messages to include in context (in minutes)
    mention_time_limit_minutes: int = field(
        default_factory=lambda: int(os.environ.get('MENTION_TIME_LIMIT_MINUTES', 30))
    )

    def validate(self) -> list[str]:
        """Validate required configuration. Returns list of error messages."""
        errors = []
        if not self.api_id:
            errors.append("API_ID is required")
        if not self.api_hash:
            errors.append("API_HASH is required")
        if not self.personal_tg_login:
            errors.append("PERSONAL_TG_LOGIN is required")
        return errors

    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        return len(self.validate()) == 0


# Global configuration instance
config = Config()
