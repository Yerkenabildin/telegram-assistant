"""
Telegram auto-responder bot.

Main entry point that runs:
- Quart web server for authentication
- Telethon client for message handling
"""
import asyncio

import hypercorn
from hypercorn.config import Config as HypercornConfig
from quart import Quart
from telethon.sync import TelegramClient

from config import config
from logging_config import logger
from models import Reply, Settings
from routes import register_routes
from handlers import register_handlers


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

# Register routes and handlers
register_routes(app, client)
register_handlers(client)


# =============================================================================
# Lifecycle Hooks
# =============================================================================

@app.before_serving
async def startup():
    """Initialize database tables on startup."""
    Reply().createTable()
    Settings().createTable()
    logger.info("Database tables initialized")


@app.after_serving
async def cleanup():
    """Disconnect Telethon client on shutdown."""
    await client.disconnect()
    logger.info("Telethon client disconnected")


# =============================================================================
# Main Entry Point
# =============================================================================

async def run_telethon():
    """Run the Telethon client event loop."""
    logger.info("Connecting Telethon client...")
    await client.connect()
    logger.info("Telethon client connected")

    while not await client.is_user_authorized():
        logger.info("Waiting for authorization...")
        await asyncio.sleep(3)

    logger.info("Telethon client authorized, starting event loop")
    await client.run_until_disconnected()


async def main():
    """Run both web server and Telethon client concurrently."""
    try:
        logger.info("Starting application...")

        hypercorn_config = HypercornConfig()
        hypercorn_config.bind = [f"{config.host}:{config.port}"]

        await asyncio.gather(
            hypercorn.asyncio.serve(app, hypercorn_config),
            run_telethon()
        )
    except asyncio.CancelledError:
        logger.info("Application shutting down...")
    finally:
        await client.disconnect()
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
    logger.info("==========================")

    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
