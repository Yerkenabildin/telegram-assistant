"""
Web routes for Telegram authentication.

Handles the authentication flow via web UI.
"""
from quart import Blueprint, render_template, request, redirect, url_for, session, jsonify
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.auth import ResendCodeRequest
from telethon.tl.functions.account import UpdateEmojiStatusRequest
from telethon.tl.types import EmojiStatus

from logging_config import logger
from models import Schedule
from config import config

# Create blueprint for auth routes
auth_bp = Blueprint('auth', __name__)

# Client will be set by register_routes()
_client = None


def register_routes(app, client):
    """
    Register auth routes on the Quart app.

    Args:
        app: Quart application instance
        client: Telethon client instance
    """
    global _client
    _client = client
    app.register_blueprint(auth_bp)


@auth_bp.route("/health")
async def health():
    """Health check endpoint for Docker/Kubernetes."""
    is_connected = _client.is_connected()
    is_authorized = await _client.is_user_authorized() if is_connected else False

    status = {
        "status": "ok" if is_connected and is_authorized else "degraded",
        "telethon_connected": is_connected,
        "telethon_authorized": is_authorized,
    }

    status_code = 200 if status["status"] == "ok" else 503
    return status, status_code


@auth_bp.route("/", methods=["GET", "POST"])
async def login():
    """Handle phone number submission for authentication."""
    if await _client.is_user_authorized():
        return await render_template('success.html')

    if request.method == 'GET':
        return await render_template('phone.html')

    form = await request.form
    phone = form['phone']

    # Check if code was already sent for this phone
    if session.get('phone') == phone and session.get('phone_code_hash'):
        logger.info(f"Code already sent to {phone}, redirecting to code page")
        return redirect(url_for('auth.code'))

    logger.info(f"Sending code to: {phone}")
    try:
        send_code_response = await _client.send_code_request(phone)
        logger.info(f"Code sent successfully, type: {type(send_code_response.type).__name__}")

        session['phone'] = phone
        session['phone_code_hash'] = send_code_response.to_dict().get('phone_code_hash')
        session['code_type'] = type(send_code_response.type).__name__
        session['code_length'] = getattr(send_code_response.type, 'length', 5)

        return redirect(url_for('auth.code'))
    except Exception as err:
        logger.error(f"Failed to send code: {err}")
        return await render_template('phone.html', error_text=str(err))


@auth_bp.route("/code", methods=["GET", "POST"])
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
        await _client.sign_in(phone, code=verification_code, phone_code_hash=phone_code_hash)
        logger.info(f"User signed in successfully: {phone}")
        return await render_template('success.html')
    except SessionPasswordNeededError:
        logger.info("2FA required, redirecting")
        return redirect(url_for('auth.two_factor'))
    except Exception as err:
        logger.error(f"Sign in failed: {err}")
        return await render_template('code.html', error_text=str(err))


@auth_bp.route("/resend", methods=["POST"])
async def resend_code():
    """Resend verification code."""
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')

    if not phone or not phone_code_hash:
        return redirect(url_for('auth.login'))

    logger.info(f"Resending code to: {phone}")
    try:
        resend_response = await _client(ResendCodeRequest(
            phone_number=phone,
            phone_code_hash=phone_code_hash
        ))
        logger.info(f"Code resent, new type: {type(resend_response.type).__name__}")

        session['phone_code_hash'] = resend_response.to_dict().get('phone_code_hash')
        session['code_type'] = type(resend_response.type).__name__
        session['code_length'] = getattr(resend_response.type, 'length', 5)

        return redirect(url_for('auth.code'))
    except Exception as err:
        logger.error(f"Failed to resend code: {err}")
        code_type = session.get('code_type', 'SentCodeTypeApp')
        code_length = session.get('code_length', 5)
        return await render_template('code.html', code_type=code_type, code_length=code_length, error_text=str(err))


@auth_bp.route("/2fa", methods=["GET", "POST"])
async def two_factor():
    """Handle two-factor authentication."""
    if request.method == 'GET':
        return await render_template('2fa.html')

    form = await request.form
    phone = session.get('phone')
    phone_code_hash = session.get('phone_code_hash')
    password = form.get('password')

    try:
        await _client.sign_in(phone, password=password, phone_code_hash=phone_code_hash)
        logger.info(f"2FA successful for: {phone}")
        return await render_template('success.html')
    except SessionPasswordNeededError:
        return redirect(url_for('auth.code'))
    except Exception as err:
        logger.error(f"2FA failed: {err}")
        return await render_template('2fa.html', error_text=str(err))


@auth_bp.route("/api/meeting", methods=["POST"])
async def meeting():
    """
    API endpoint for meeting status control (e.g., Zoom integration).

    Query parameters:
        action: 'start' or 'end'
        emoji_id: (required for start) emoji document ID to set during meeting
        token: (optional) API token for authentication

    Examples:
        POST /api/meeting?action=start&emoji_id=5368324170671202286
        POST /api/meeting?action=end
    """
    # Check token if configured
    if config.meeting_api_token:
        token = request.args.get('token') or request.headers.get('X-API-Token')
        if token != config.meeting_api_token:
            return jsonify({"error": "Invalid or missing API token"}), 401

    action = request.args.get('action')

    if action not in ('start', 'end'):
        return jsonify({"error": "Invalid action. Use 'start' or 'end'"}), 400

    if action == 'start':
        emoji_id = request.args.get('emoji_id')
        if not emoji_id:
            return jsonify({"error": "emoji_id is required for start action"}), 400

        try:
            emoji_id = int(emoji_id)
        except ValueError:
            return jsonify({"error": "emoji_id must be a number"}), 400

        # Create meeting schedule rule
        Schedule.start_meeting(emoji_id)
        logger.info(f"Meeting started with emoji_id: {emoji_id}")

        # Immediately update emoji status
        try:
            await _client(UpdateEmojiStatusRequest(
                emoji_status=EmojiStatus(document_id=emoji_id)
            ))
            logger.info(f"Emoji status updated to {emoji_id}")
        except Exception as e:
            logger.error(f"Failed to update emoji status: {e}")
            return jsonify({
                "status": "partial",
                "message": "Meeting rule created but failed to update emoji immediately",
                "error": str(e)
            }), 500

        return jsonify({
            "status": "ok",
            "action": "start",
            "emoji_id": emoji_id,
            "message": "Meeting started, emoji status updated"
        })

    else:  # action == 'end'
        was_active = Schedule.end_meeting()

        if was_active:
            logger.info("Meeting ended, rule removed")

            # Get scheduled emoji and apply it immediately
            scheduled_emoji_id = Schedule.get_current_emoji_id()
            if scheduled_emoji_id:
                try:
                    await _client(UpdateEmojiStatusRequest(
                        emoji_status=EmojiStatus(document_id=scheduled_emoji_id)
                    ))
                    logger.info(f"Emoji status restored to scheduled: {scheduled_emoji_id}")
                except Exception as e:
                    logger.error(f"Failed to restore emoji status: {e}")

            return jsonify({
                "status": "ok",
                "action": "end",
                "message": "Meeting ended, emoji status restored",
                "scheduled_emoji_id": scheduled_emoji_id
            })
        else:
            return jsonify({
                "status": "ok",
                "action": "end",
                "message": "No active meeting found"
            })
