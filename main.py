"""
Telegram auto-responder bot.

Main entry point that runs:
- Quart web server for authentication
- Telethon client for message handling
"""
from __future__ import annotations

import asyncio

import hypercorn
from hypercorn.config import Config as HypercornConfig
from quart import Quart
from telethon.sync import TelegramClient
from telethon.errors import AuthKeyUnregisteredError

from config import config
from logging_config import logger
from models import Reply, Settings, Schedule
from routes import register_routes
from handlers import register_handlers
from bot_handlers import register_bot_handlers, set_owner_id, set_owner_username, set_bot_username
from telethon.tl.functions.account import UpdateEmojiStatusRequest
from telethon.tl.types import EmojiStatus


# =============================================================================
# Application Setup
# =============================================================================

def create_app() -> Quart:
    """Create and configure the Quart application."""
    app = Quart(__name__)
    app.secret_key = config.secret_key

    # Apply prefix middleware if configured
    if config.script_name:
        app.asgi_app = PrefixMiddleware(app.asgi_app, config.script_name)

    return app


def create_client() -> TelegramClient:
    """Create the Telethon client."""
    return TelegramClient(config.session_path, config.api_id, config.api_hash)


def create_bot() -> TelegramClient | None:
    """Create the Telethon bot client if BOT_TOKEN is configured."""
    if not config.bot_token:
        return None
    return TelegramClient('bot', config.api_id, config.api_hash)


class PrefixMiddleware:
    """ASGI middleware to handle SCRIPT_NAME for reverse proxy."""

    def __init__(self, asgi_app, prefix: str = ''):
        self.app = asgi_app
        self.prefix = prefix.rstrip('/')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and self.prefix:
            scope['root_path'] = self.prefix
        return await self.app(scope, receive, send)


# =============================================================================
# Application Instances
# =============================================================================

app = create_app()
client = create_client()
bot = create_bot()

# Register routes and handlers
register_routes(app, client)
register_handlers(client)

# Register bot handlers if bot is configured
if bot:
    register_bot_handlers(bot, client)


# =============================================================================
# Lifecycle Hooks
# =============================================================================

@app.before_serving
async def startup():
    """Initialize database tables on startup."""
    Reply().createTable()
    Settings().createTable()
    Schedule().createTable()
    logger.info("Database tables initialized")


@app.after_serving
async def cleanup():
    """Disconnect Telethon clients on shutdown."""
    await client.disconnect()
    if bot:
        await bot.disconnect()
    logger.info("Telethon clients disconnected")


# =============================================================================
# Schedule Checker
# =============================================================================

async def schedule_checker():
    """Background task that checks schedule and updates emoji status."""
    logger.info("Starting schedule checker...")

    # Wait for client to be authorized
    while not await client.is_user_authorized():
        await asyncio.sleep(5)

    logger.info("Schedule checker active")

    check_count = 0

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            check_count += 1

            if not Schedule.is_scheduling_enabled():
                continue

            # Clean up expired overrides once a day
            if check_count % 1440 == 0:
                deleted = Schedule.delete_expired()
                if deleted > 0:
                    logger.info(f"Deleted {deleted} expired override(s)")

            scheduled_emoji_id = Schedule.get_current_emoji_id()
            if scheduled_emoji_id is None:
                continue

            # Get current actual status
            me = await client.get_me()
            current_emoji_id = me.emoji_status.document_id if me.emoji_status else None

            # Only update if different from what schedule says it should be
            if current_emoji_id != scheduled_emoji_id:
                logger.info(f"Changing emoji status: {current_emoji_id} -> {scheduled_emoji_id}")
                try:
                    await client(UpdateEmojiStatusRequest(
                        emoji_status=EmojiStatus(document_id=scheduled_emoji_id)
                    ))
                    logger.info(f"Emoji status updated to {scheduled_emoji_id}")
                except Exception as e:
                    logger.error(f"Failed to update emoji status: {e}")

        except asyncio.CancelledError:
            logger.info("Schedule checker stopped")
            break
        except Exception as e:
            logger.error(f"Schedule checker error: {e}")
            await asyncio.sleep(60)  # Wait before retrying on error


# =============================================================================
# Main Entry Point
# =============================================================================

async def run_telethon():
    """Run the Telethon client event loop."""
    logger.info("Connecting Telethon client...")
    await client.connect()
    logger.info("Telethon client connected")

    # Check if already authorized
    if await client.is_user_authorized():
        # Set owner ID and username for bot access control
        me = await client.get_me()
        set_owner_id(me.id)
        if me.username:
            set_owner_username(me.username)
        logger.info(f"Telethon client authorized as {me.id} (@{me.username})")

        # Send welcome message via bot if configured
        await _send_welcome_message()
    else:
        logger.info("Telethon client not authorized. Waiting for authentication via bot...")

    # Start schedule checker as a background task
    asyncio.create_task(schedule_checker())

    # Start background task to detect when auth is complete
    asyncio.create_task(_wait_for_auth())

    # Run client with reconnection on auth errors (e.g., after logout)
    while True:
        try:
            # Only run event loop if authorized, otherwise just wait
            if await client.is_user_authorized():
                await client.run_until_disconnected()
                break  # Normal exit
            else:
                # Not authorized - wait for bot-based auth
                await asyncio.sleep(5)
        except AuthKeyUnregisteredError:
            # Session invalidated (e.g., after logout) - delete session and reconnect
            logger.info("Session invalidated. Cleaning up and waiting for new authentication...")

            # Delete invalid session file
            import os
            session_file = config.session_path + '.session'
            if os.path.exists(session_file):
                try:
                    os.remove(session_file)
                    logger.info(f"Invalid session file deleted: {session_file}")
                except Exception as e:
                    logger.warning(f"Failed to delete session file: {e}")

            # Reconnect with fresh session
            try:
                await client.disconnect()
            except Exception:
                pass
            await client.connect()
            await asyncio.sleep(2)


async def _wait_for_auth():
    """Background task that waits for authorization and sends welcome message."""
    # Only run if not already authorized
    if await client.is_user_authorized():
        return

    while True:
        await asyncio.sleep(2)
        if await client.is_user_authorized():
            me = await client.get_me()
            logger.info(f"Telethon client now authorized as {me.id} (@{me.username})")
            await _send_welcome_message()
            break


async def _send_welcome_message():
    """Send welcome message via bot if configured."""
    if not bot:
        return

    # Wait for bot to be ready (max 10 seconds)
    for _ in range(20):
        if bot.is_connected() and await bot.is_user_authorized():
            break
        await asyncio.sleep(0.5)

    if not (bot.is_connected() and await bot.is_user_authorized()):
        return

    try:
        # Set bot username for user client to send messages
        bot_me = await bot.get_me()
        if bot_me.username:
            set_bot_username(bot_me.username)

        me = await client.get_me()
        from bot_handlers import get_main_menu_keyboard
        await bot.send_message(
            me.id,
            "🤖 **Панель управления автоответчиком**\n\n"
            "Бот готов к работе! Выберите раздел:",
            buttons=get_main_menu_keyboard()
        )
        logger.info("Welcome message sent to owner")
    except Exception as e:
        logger.warning(f"Failed to send welcome message: {e}")


async def run_bot():
    """Run the Telegram bot client."""
    if not bot:
        return

    logger.info("Starting bot client...")
    await bot.start(bot_token=config.bot_token)
    logger.info("Bot client started")

    await bot.run_until_disconnected()


async def main():
    """Run web server, Telethon client, and bot concurrently."""
    try:
        logger.info("Starting application...")

        hypercorn_config = HypercornConfig()
        hypercorn_config.bind = [f"{config.host}:{config.port}"]

        tasks = [
            hypercorn.asyncio.serve(app, hypercorn_config),
            run_telethon(),
        ]

        # Add bot if configured
        if bot:
            tasks.append(run_bot())

        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Application shutting down...")
    finally:
        await client.disconnect()
        if bot:
            await bot.disconnect()
        logger.info("Cleanup complete")


if __name__ == '__main__':
    # Validate configuration
    errors = config.validate()
    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        exit(1)

    logger.info("=== TELEGRAM ASSISTANT ===")
    logger.info(f"API_ID: {config.api_id}")
    logger.info(f"Port: {config.port}")
    logger.info(f"Script name: {config.script_name or '(none)'}")
    logger.info(f"Bot: {'enabled' if config.bot_token else 'disabled'}")
    if config.allowed_username:
        logger.info(f"Allowed username: @{config.allowed_username}")
    logger.info("==========================")

    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
