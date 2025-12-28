"""
Web routes for Telegram authentication.

Handles the authentication flow via web UI.
"""
from quart import Blueprint, render_template, request, redirect, url_for, session
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.auth import ResendCodeRequest

from logging_config import logger

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
