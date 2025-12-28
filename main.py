import asyncio
import json
import os

import aiohttp
import requests
from datetime import timedelta

import hypercorn
from quart import Quart, render_template, request, redirect, url_for, session
from hypercorn.config import Config
from telethon.errors import SessionPasswordNeededError
from telethon.sync import TelegramClient, events
from telethon.tl import types
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.functions.auth import ResendCodeRequest
from telethon.tl.types import MessageEntityCustomEmoji

from models import Reply

app = Quart(__name__)

environ = os.environ
app.secret_key = environ.get('SECRET_KEY', os.urandom(24))

# Middleware to handle SCRIPT_NAME for reverse proxy
class PrefixMiddleware:
    def __init__(self, app, prefix=''):
        self.app = app
        self.prefix = prefix.rstrip('/')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and self.prefix:
            scope['root_path'] = self.prefix
        return await self.app(scope, receive, send)

script_name = environ.get('SCRIPT_NAME', '').rstrip('/')
if script_name:
    app.asgi_app = PrefixMiddleware(app.asgi_app, script_name)

api_id = int(environ.get('API_ID'))
available_emoji_id = int(environ.get('AVAILABLE_EMOJI_ID', 5810051751654460532))
api_hash = environ.get('API_HASH')
personal_tg_login = environ.get('PERSONAL_TG_LOGIN')
work_tg_login = environ.get('WORK_TG_LOGIN')
asap_webhook_url = environ.get('ASAP_WEBHOOK_URL')
# Chat ID for separate auto-reply settings (e.g., -1005136892854 for supergroups)
chat_auto_reply_id = environ.get('CHAT_AUTO_REPLY_ID')
if chat_auto_reply_id:
    chat_auto_reply_id = int(chat_auto_reply_id)

client = TelegramClient("./storage/session", api_id, api_hash)


@app.before_serving
async def startup():
    reply = Reply()
    reply.createTable()


@app.after_serving
async def cleanup():
    await client.disconnect()


@app.route("/health")
async def health():
    """Healthcheck endpoint for Docker/Kubernetes"""
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
    if await client.is_user_authorized():
        return await render_template('success.html')

    if request.method == 'GET':
        return await render_template('phone.html')

    form = await request.form
    phone = form['phone']

    # Check if code was already sent for this phone in current session
    if session.get('phone') == phone and session.get('phone_code_hash'):
        print(f"[LOGIN] Code already sent to {phone}, redirecting to code page")
        return redirect(url_for('code'))

    print(f"[LOGIN] Attempting to send code to: {phone}")
    try:
        send_code_response = await client.send_code_request(phone)
        print(f"[LOGIN] Code sent successfully!")
        print(f"  Type: {send_code_response.type}")
        print(f"  Next type: {send_code_response.next_type}")
        print(f"  Timeout: {send_code_response.timeout}")
        print(f"  Full response: {send_code_response.to_dict()}")

        session['phone'] = phone
        session['phone_code_hash'] = send_code_response.to_dict().get('phone_code_hash')
        session['code_type'] = type(send_code_response.type).__name__
        session['code_length'] = getattr(send_code_response.type, 'length', 5)

        return redirect(url_for('code'))
    except Exception as err:
        print(f"[LOGIN ERROR] Failed to send code: {err}")
        return await render_template('phone.html', error_text=str(err))


@app.route("/code", methods=["GET", "POST"])
async def code():
    if request.method == 'GET':
        code_type = session.get('code_type', 'SentCodeTypeApp')
        code_length = session.get('code_length', 5)
        return await render_template('code.html', code_type=code_type, code_length=code_length)

    form = await request.form
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')
    code = form.get('code')

    try:
        await client.sign_in(phone, code=code, phone_code_hash=phone_code_hash)
        return await render_template('success.html')
    except SessionPasswordNeededError:
        return redirect(url_for('two_factor'))
    except Exception as err:
        return await render_template('code.html', error_text=str(err))


@app.route("/resend", methods=["POST"])
async def resend_code():
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')

    if not phone or not phone_code_hash:
        return redirect(url_for('login'))

    print(f"[RESEND] Requesting code resend for: {phone}")
    try:
        resend_response = await client(ResendCodeRequest(
            phone_number=phone,
            phone_code_hash=phone_code_hash
        ))
        print(f"[RESEND] Code resent successfully!")
        print(f"  Type: {resend_response.type}")
        print(f"  Next type: {resend_response.next_type}")
        print(f"  Full response: {resend_response.to_dict()}")

        # Update session with new code type
        session['phone_code_hash'] = resend_response.to_dict().get('phone_code_hash')
        session['code_type'] = type(resend_response.type).__name__
        session['code_length'] = getattr(resend_response.type, 'length', 5)

        return redirect(url_for('code'))
    except Exception as err:
        print(f"[RESEND ERROR] Failed to resend code: {err}")
        import traceback
        traceback.print_exc()
        code_type = session.get('code_type', 'SentCodeTypeApp')
        code_length = session.get('code_length', 5)
        return await render_template('code.html', code_type=code_type, code_length=code_length, error_text=str(err))


@app.route("/2fa", methods=["GET", "POST"])
async def two_factor():
    if request.method == 'GET':
        return await render_template('2fa.html')

    form = await request.form
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')
    password = form.get('password')

    try:
        await client.sign_in(phone, password=password, phone_code_hash=phone_code_hash)
        return await render_template('success.html')
    except SessionPasswordNeededError:
        return redirect(url_for('code'))
    except Exception as err:
        return await render_template('2fa.html', error_text=str(err))


@client.on(events.NewMessage(from_users=work_tg_login, pattern="/set_for.*"))
async def setup_response(event):
    chat_id = event.chat.id

    if not event.reply_to:
        await client.send_message(
            entity=chat_id,
            message="Команда должна быть ответом на сообщение"
        )
        return

    msg_id = event.reply_to.reply_to_msg_id
    message = await client.get_messages(chat_id, ids=msg_id)

    entities = event.message.entities or []
    # Filter only custom emojis (premium Telegram emojis with document_id)
    custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

    if len(custom_emojis) != 1:
        await client.send_message(
            entity=chat_id,
            reply_to=msg_id,
            message=f"Нужен 1 кастомный эмодзи Telegram (премиум), найдено: {len(custom_emojis)}. Обычные эмодзи (🎄) не поддерживаются — используйте эмодзи из панели премиум-стикеров."
        )
        return

    emoji = custom_emojis[0]
    Reply.create(emoji.document_id, message)

    await client(SendReactionRequest(
        peer=chat_id,
        msg_id=event.message.id,
        reaction=[types.ReactionEmoji(
            emoticon=u'\U0001fae1'
        )]
    ))


@client.on(events.NewMessage(from_users=work_tg_login, pattern="/set_for_chat.*"))
async def setup_chat_response(event):
    """Set auto-reply for specific chat (configured via CHAT_AUTO_REPLY_ID)"""
    chat_id = event.chat.id

    if not chat_auto_reply_id:
        await client.send_message(
            entity=chat_id,
            message="CHAT_AUTO_REPLY_ID не настроен в переменных окружения"
        )
        return

    if not event.reply_to:
        await client.send_message(
            entity=chat_id,
            message="Команда должна быть ответом на сообщение"
        )
        return

    msg_id = event.reply_to.reply_to_msg_id
    message = await client.get_messages(chat_id, ids=msg_id)

    entities = event.message.entities or []
    custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

    if len(custom_emojis) != 1:
        await client.send_message(
            entity=chat_id,
            reply_to=msg_id,
            message=f"Нужен 1 кастомный эмодзи Telegram (премиум), найдено: {len(custom_emojis)}. Обычные эмодзи (🎄) не поддерживаются — используйте эмодзи из панели премиум-стикеров."
        )
        return

    emoji = custom_emojis[0]
    Reply.create(emoji.document_id, message, chat_id=chat_auto_reply_id)

    await client(SendReactionRequest(
        peer=chat_id,
        msg_id=event.message.id,
        reaction=[types.ReactionEmoji(
            emoticon=u'\U0001f4ac'  # 💬 emoji to indicate chat-specific setting
        )]
    ))


@client.on(events.NewMessage(incoming=True, pattern=".*[Aa][Ss][Aa][Pp].*"))
async def asap_handler(event):
    if not event.is_private:
        return

    me = await client.get_me()
    if me.emoji_status.document_id == available_emoji_id:
        return

    sender = await event.get_sender()
    await client.send_message(
        personal_tg_login,
        '❗️Срочный призыв от @' + sender.username,
        formatting_entities=[MessageEntityCustomEmoji(offset=0, length=2, document_id=5379748062124056162)]
    )

    # Call ASAP webhook if configured
    if asap_webhook_url:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    'sender_username': sender.username,
                    'sender_id': sender.id,
                    'message': event.message.text,
                }
                async with session.post(asap_webhook_url, json=payload, timeout=10) as response:
                    print(f"[ASAP WEBHOOK] Called {asap_webhook_url}, status: {response.status}")
        except Exception as e:
            print(f"[ASAP WEBHOOK ERROR] Failed to call webhook: {e}")

    await client(SendReactionRequest(
        peer=event.peer_id,
        msg_id=event.message.id,
        reaction=[types.ReactionEmoji(
            emoticon=u'\U0001fae1'
        )]
    ))


@client.on(events.NewMessage(incoming=True))
async def new_messages(event):
    me = await client.get_me()

    # Check if we have emoji status
    if not me.emoji_status or not hasattr(me.emoji_status, 'document_id'):
        return

    sender = await event.get_sender()
    if not sender:
        return

    # Determine which chat_id to use for lookup
    current_chat_id = event.chat.id if event.chat else None

    # Check if this is from the configured chat for separate settings
    if chat_auto_reply_id and current_chat_id == chat_auto_reply_id:
        # Use chat-specific settings with fallback to global
        reply = Reply.get_reply_for_context(me.emoji_status.document_id, chat_auto_reply_id)
    elif event.is_private:
        # Private messages use global settings only
        reply = Reply.get_by_emoji(me.emoji_status.document_id)
    else:
        # Other group chats - ignore
        return

    if reply is None:
        return

    message = reply.message
    if message is None:
        return

    username = sender.username

    # Rate limiting: only for private chats
    if event.is_private and username:
        messages = await client.get_messages(username, limit=2)
        if len(messages) > 1:
            difference = messages[0].date - messages[1].date
            if difference < timedelta(minutes=15):
                return

    # Send reply
    if event.is_private and username:
        await client.send_message(
            username,
            message=message
        )
    else:
        # For group chats, reply to the message
        await client.send_message(
            current_chat_id,
            message=message,
            reply_to=event.message.id
        )


async def run_telethon():
    print("Connecting Telethon client...")
    await client.connect()
    print("Connected Telethon client...")

    while not await client.is_user_authorized():
        await asyncio.sleep(3)

    await client.run_until_disconnected()


async def main():
    try:
        print("Starting application...")

        config = Config()
        config.bind = ["0.0.0.0:5050"]

        await asyncio.gather(
            hypercorn.asyncio.serve(app, config),
            run_telethon()
        )
    except asyncio.CancelledError:
        print("CancelledError: Gracefully shutting down...")
    finally:
        print("Disconnecting Telethon client...")
        await client.disconnect()


if __name__ == '__main__':
    print("=== MAIN ENTRY POINT ===")
    print(f"API_ID: {api_id}")
    print(f"API_HASH: {'*' * len(api_hash) if api_hash else 'NOT SET'}")
    print(f"SCRIPT_NAME: {environ.get('SCRIPT_NAME', 'NOT SET')}")
    print("========================")
    try:
        print("Starting event loop...")
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Application interrupted.")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
