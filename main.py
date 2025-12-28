"""
Telegram auto-responder bot.

Main entry point that runs:
- Quart web server for authentication
- Telethon client for message handling
"""
import asyncio
from datetime import timedelta

import hypercorn
from hypercorn.config import Config as HypercornConfig
from quart import Quart, render_template, request, redirect, url_for, session
from telethon.errors import SessionPasswordNeededError, ReactionInvalidError
from telethon.sync import TelegramClient, events
from telethon.tl import types
from telethon.tl.functions.auth import ResendCodeRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import MessageEntityCustomEmoji

from config import config
from logging_config import logger
from models import Reply, Settings
from services.autoreply_service import AutoReplyService
from services.notification_service import NotificationService

# Initialize Quart app
app = Quart(__name__)
app.secret_key = config.secret_key


# Middleware for reverse proxy support
class PrefixMiddleware:
    """ASGI middleware to handle SCRIPT_NAME for reverse proxy."""

    def __init__(self, asgi_app, prefix: str = ''):
        self.app = asgi_app
        self.prefix = prefix.rstrip('/')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and self.prefix:
            scope['root_path'] = self.prefix
        return await self.app(scope, receive, send)


if config.script_name:
    app.asgi_app = PrefixMiddleware(app.asgi_app, config.script_name)

# Initialize Telethon client
client = TelegramClient(config.session_path, config.api_id, config.api_hash)

# Initialize services
autoreply_service = AutoReplyService(cooldown_minutes=config.autoreply_cooldown_minutes)
notification_service = NotificationService(
    personal_tg_login=config.personal_tg_login,
    available_emoji_id=config.available_emoji_id,
    webhook_url=config.asap_webhook_url,
    webhook_timeout=config.webhook_timeout_seconds
)


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
# Web Routes
# =============================================================================

@app.route("/health")
async def health():
    """Health check endpoint for Docker/Kubernetes."""
    is_connected = client.is_connected()
    is_authorized = await client.is_user_authorized() if is_connected else False

    status = {
        "status": "ok" if is_connected and is_authorized else "degraded",
        "telethon_connected": is_connected,
        "telethon_authorized": is_authorized,
    }

    status_code = 200 if status["status"] == "ok" else 503
    return status, status_code


@app.route("/", methods=["GET", "POST"])
async def login():
    """Handle phone number submission for authentication."""
    if await client.is_user_authorized():
        return await render_template('success.html')

    if request.method == 'GET':
        return await render_template('phone.html')

    form = await request.form
    phone = form['phone']

    # Check if code was already sent for this phone
    if session.get('phone') == phone and session.get('phone_code_hash'):
        logger.info(f"Code already sent to {phone}, redirecting to code page")
        return redirect(url_for('code'))

    logger.info(f"Sending code to: {phone}")
    try:
        send_code_response = await client.send_code_request(phone)
        logger.info(f"Code sent successfully, type: {type(send_code_response.type).__name__}")

        session['phone'] = phone
        session['phone_code_hash'] = send_code_response.to_dict().get('phone_code_hash')
        session['code_type'] = type(send_code_response.type).__name__
        session['code_length'] = getattr(send_code_response.type, 'length', 5)

        return redirect(url_for('code'))
    except Exception as err:
        logger.error(f"Failed to send code: {err}")
        return await render_template('phone.html', error_text=str(err))


@app.route("/code", methods=["GET", "POST"])
async def code():
    """Handle verification code submission."""
    if request.method == 'GET':
        code_type = session.get('code_type', 'SentCodeTypeApp')
        code_length = session.get('code_length', 5)
        return await render_template('code.html', code_type=code_type, code_length=code_length)

    form = await request.form
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')
    verification_code = form.get('code')

    try:
        await client.sign_in(phone, code=verification_code, phone_code_hash=phone_code_hash)
        logger.info(f"User signed in successfully: {phone}")
        return await render_template('success.html')
    except SessionPasswordNeededError:
        logger.info("2FA required, redirecting")
        return redirect(url_for('two_factor'))
    except Exception as err:
        logger.error(f"Sign in failed: {err}")
        return await render_template('code.html', error_text=str(err))


@app.route("/resend", methods=["POST"])
async def resend_code():
    """Resend verification code."""
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')

    if not phone or not phone_code_hash:
        return redirect(url_for('login'))

    logger.info(f"Resending code to: {phone}")
    try:
        resend_response = await client(ResendCodeRequest(
            phone_number=phone,
            phone_code_hash=phone_code_hash
        ))
        logger.info(f"Code resent, new type: {type(resend_response.type).__name__}")

        session['phone_code_hash'] = resend_response.to_dict().get('phone_code_hash')
        session['code_type'] = type(resend_response.type).__name__
        session['code_length'] = getattr(resend_response.type, 'length', 5)

        return redirect(url_for('code'))
    except Exception as err:
        logger.error(f"Failed to resend code: {err}")
        code_type = session.get('code_type', 'SentCodeTypeApp')
        code_length = session.get('code_length', 5)
        return await render_template('code.html', code_type=code_type, code_length=code_length, error_text=str(err))


@app.route("/2fa", methods=["GET", "POST"])
async def two_factor():
    """Handle two-factor authentication."""
    if request.method == 'GET':
        return await render_template('2fa.html')

    form = await request.form
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')
    password = form.get('password')

    try:
        await client.sign_in(phone, password=password, phone_code_hash=phone_code_hash)
        logger.info(f"2FA successful for: {phone}")
        return await render_template('success.html')
    except SessionPasswordNeededError:
        return redirect(url_for('code'))
    except Exception as err:
        logger.error(f"2FA failed: {err}")
        return await render_template('2fa.html', error_text=str(err))


# =============================================================================
# Telethon Event Handlers
# =============================================================================

@client.on(events.NewMessage(outgoing=True))
async def debug_outgoing(event):
    """Log all outgoing messages for debugging."""
    logger.debug(f"Outgoing: '{event.message.text}' in chat {event.chat_id}")


@client.on(events.NewMessage(outgoing=True, pattern=r"^/autoreply-settings\s*$"))
async def select_settings_chat(event):
    """Handle /autoreply-settings command to set the settings chat."""
    chat_id = event.chat.id
    Settings.set_settings_chat_id(chat_id)
    logger.info(f"Settings chat set to: {chat_id}")

    await _send_reaction(event, '\u2705')  # ✅

    await client.send_message(
        entity=event.input_chat,
        message=(
            "✅ Этот чат выбран для настройки автоответчика.\n\n"
            "Доступные команды:\n"
            "• /set — ответом на сообщение, чтобы задать автоответ для текущего статуса\n"
            "• /set_for <эмодзи> — ответом на сообщение, чтобы задать автоответ для указанного эмодзи\n"
            "• /autoreply-off — отключить автоответчик"
        )
    )


@client.on(events.NewMessage(outgoing=True, pattern=r"^/autoreply-off\s*$"))
async def disable_autoreply(event):
    """Handle /autoreply-off command to disable autoreply."""
    settings_chat_id = Settings.get_settings_chat_id()
    chat_id = event.chat.id

    if not autoreply_service.is_settings_chat(chat_id, settings_chat_id):
        return

    Settings.set_settings_chat_id(None)
    logger.info("Autoreply disabled")

    await _send_reaction(event, '\u274c')  # ❌

    await client.send_message(
        entity=event.input_chat,
        message="❌ Автоответчик отключен. Используйте /autoreply-settings в любом чате, чтобы снова включить."
    )


@client.on(events.NewMessage(outgoing=True, pattern=r"^/set_for\s+.*"))
async def setup_response(event):
    """Handle /set_for command to set reply for specific emoji."""
    settings_chat_id = Settings.get_settings_chat_id()
    chat_id = event.chat.id

    if not autoreply_service.is_settings_chat(chat_id, settings_chat_id):
        return

    if not event.reply_to:
        await client.send_message(
            entity=event.input_chat,
            message="Команда должна быть ответом на сообщение"
        )
        return

    msg_id = event.reply_to.reply_to_msg_id
    message = await client.get_messages(event.input_chat, ids=msg_id)

    entities = event.message.entities or []
    custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

    if len(custom_emojis) != 1:
        await client.send_message(
            entity=event.input_chat,
            reply_to=msg_id,
            message=(
                f"Нужен 1 кастомный эмодзи Telegram (премиум), найдено: {len(custom_emojis)}. "
                "Обычные эмодзи (🎄) не поддерживаются — используйте эмодзи из панели премиум-стикеров."
            )
        )
        return

    emoji = custom_emojis[0]
    Reply.create(emoji.document_id, message)
    logger.info(f"Reply set for emoji: {emoji.document_id}")

    await _send_reaction(event, '\U0001fae1')  # 🫡


@client.on(events.NewMessage(outgoing=True, pattern=r"^/set\s*$"))
async def setup_response_current_status(event):
    """Handle /set command to set reply for current emoji status."""
    settings_chat_id = Settings.get_settings_chat_id()
    chat_id = event.chat.id

    if not autoreply_service.is_settings_chat(chat_id, settings_chat_id):
        return

    if not event.reply_to:
        await client.send_message(
            entity=event.input_chat,
            message="Команда должна быть ответом на сообщение"
        )
        return

    me = await client.get_me()
    if not me.emoji_status:
        await client.send_message(
            entity=event.input_chat,
            message="❌ У вас не установлен эмодзи-статус. Установите статус в настройках Telegram и попробуйте снова."
        )
        return

    msg_id = event.reply_to.reply_to_msg_id
    message = await client.get_messages(event.input_chat, ids=msg_id)

    emoji_id = me.emoji_status.document_id
    Reply.create(emoji_id, message)
    logger.info(f"Reply set for current status emoji: {emoji_id}")

    await _send_reaction(event, '\U0001fae1')  # 🫡

    await client.send_message(
        entity=event.input_chat,
        message=f"✅ Автоответ установлен для текущего статуса (ID: {emoji_id})"
    )


@client.on(events.NewMessage(incoming=True, pattern=".*[Aa][Ss][Aa][Pp].*"))
async def asap_handler(event):
    """Handle incoming messages with ASAP keyword."""
    if not event.is_private:
        return

    me = await client.get_me()
    emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

    if not notification_service.should_notify_asap(
        message_text=event.message.text or '',
        is_private=event.is_private,
        emoji_status_id=emoji_status_id
    ):
        return

    sender = await event.get_sender()
    sender_username = getattr(sender, 'username', None)
    sender_id = getattr(sender, 'id', 0)

    # Send notification to personal account
    notification_message = notification_service.format_asap_message(sender_username, sender_id)
    await client.send_message(
        config.personal_tg_login,
        notification_message,
        formatting_entities=[MessageEntityCustomEmoji(offset=0, length=2, document_id=5379748062124056162)]
    )
    logger.info(f"ASAP notification sent for message from {sender_username or sender_id}")

    # Call webhook if configured
    if config.asap_webhook_url:
        await notification_service.call_webhook(
            sender_username=sender_username,
            sender_id=sender_id,
            message_text=event.message.text or ''
        )

    await _send_reaction(event, '\U0001fae1')  # 🫡


@client.on(events.NewMessage(incoming=True))
async def new_messages(event):
    """Handle incoming messages for auto-reply."""
    if not event.is_private:
        return

    me = await client.get_me()
    emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

    reply = Reply.get_by_emoji(emoji_status_id) if emoji_status_id else None

    sender = await event.get_sender()
    sender_username = getattr(sender, 'username', None)
    sender_id = getattr(sender, 'id', 0)

    # Use username or ID for message lookup
    user_identifier = sender_username or sender_id
    if not user_identifier:
        logger.warning("Could not identify sender, skipping auto-reply")
        return

    # Get last messages for rate limiting
    try:
        messages = await client.get_messages(user_identifier, limit=2)
    except Exception as e:
        logger.warning(f"Could not get messages for rate limiting: {e}")
        messages = []

    if not autoreply_service.should_send_reply(
        emoji_status_id=emoji_status_id,
        available_emoji_id=config.available_emoji_id,
        reply_exists=reply is not None,
        last_two_messages=messages
    ):
        return

    message = reply.message if reply else None
    if message is None:
        return

    await client.send_message(user_identifier, message=message)
    logger.info(f"Auto-reply sent to {user_identifier}")


# =============================================================================
# Helper Functions
# =============================================================================

async def _send_reaction(event, emoticon: str) -> None:
    """Send a reaction to a message, handling errors gracefully."""
    try:
        await client(SendReactionRequest(
            peer=event.input_chat,
            msg_id=event.message.id,
            reaction=[types.ReactionEmoji(emoticon=emoticon)]
        ))
    except ReactionInvalidError:
        logger.debug(f"Reaction not allowed in chat {event.chat_id}")
    except Exception as e:
        logger.warning(f"Failed to send reaction: {e}")


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
