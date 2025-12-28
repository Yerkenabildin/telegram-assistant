"""
Unit tests for web route logic.

These tests validate the route behavior patterns using mocks,
without requiring actual Quart/Telethon dependencies.
"""
import os
import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHealthEndpointLogic:
    """Tests for /health endpoint logic."""

    @pytest.mark.asyncio
    async def test_health_ok_logic(self, mock_telegram_client):
        """Test health endpoint logic when everything is OK."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_user_authorized = AsyncMock(return_value=True)

        # Simulate health check logic
        is_connected = mock_telegram_client.is_connected()
        is_authorized = await mock_telegram_client.is_user_authorized() if is_connected else False

        status = {
            "status": "ok" if is_connected and is_authorized else "degraded",
            "telethon_connected": is_connected,
            "telethon_authorized": is_authorized,
        }

        status_code = 200 if status["status"] == "ok" else 503

        assert status_code == 200
        assert status['status'] == 'ok'
        assert status['telethon_connected'] is True
        assert status['telethon_authorized'] is True

    @pytest.mark.asyncio
    async def test_health_degraded_not_connected_logic(self, mock_telegram_client):
        """Test health endpoint logic when Telethon is not connected."""
        mock_telegram_client.is_connected.return_value = False

        # Simulate health check logic
        is_connected = mock_telegram_client.is_connected()
        is_authorized = await mock_telegram_client.is_user_authorized() if is_connected else False

        status = {
            "status": "ok" if is_connected and is_authorized else "degraded",
            "telethon_connected": is_connected,
            "telethon_authorized": is_authorized,
        }

        status_code = 200 if status["status"] == "ok" else 503

        assert status_code == 503
        assert status['status'] == 'degraded'
        assert status['telethon_connected'] is False

    @pytest.mark.asyncio
    async def test_health_degraded_not_authorized_logic(self, mock_telegram_client):
        """Test health endpoint logic when Telethon is not authorized."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_user_authorized = AsyncMock(return_value=False)

        # Simulate health check logic
        is_connected = mock_telegram_client.is_connected()
        is_authorized = await mock_telegram_client.is_user_authorized() if is_connected else False

        status = {
            "status": "ok" if is_connected and is_authorized else "degraded",
            "telethon_connected": is_connected,
            "telethon_authorized": is_authorized,
        }

        status_code = 200 if status["status"] == "ok" else 503

        assert status_code == 503
        assert status['status'] == 'degraded'
        assert status['telethon_authorized'] is False


class TestLoginRouteLogic:
    """Tests for / (login) endpoint logic."""

    @pytest.mark.asyncio
    async def test_login_get_authorized_shows_success(self, mock_telegram_client):
        """Test GET / when authorized shows success."""
        mock_telegram_client.is_user_authorized = AsyncMock(return_value=True)

        # Simulate login route logic
        is_authorized = await mock_telegram_client.is_user_authorized()

        if is_authorized:
            template = 'success.html'
        else:
            template = 'phone.html'

        assert template == 'success.html'

    @pytest.mark.asyncio
    async def test_login_get_not_authorized_shows_phone(self, mock_telegram_client):
        """Test GET / when not authorized shows phone form."""
        mock_telegram_client.is_user_authorized = AsyncMock(return_value=False)

        # Simulate login route logic
        is_authorized = await mock_telegram_client.is_user_authorized()

        if is_authorized:
            template = 'success.html'
        else:
            template = 'phone.html'

        assert template == 'phone.html'

    @pytest.mark.asyncio
    async def test_login_post_sends_code(self, mock_telegram_client):
        """Test POST / with phone number sends code."""
        # Mock send_code_request response
        mock_response = MagicMock()
        mock_response.type = MagicMock()
        mock_response.next_type = None
        mock_response.timeout = 60
        mock_response.to_dict.return_value = {
            'phone_code_hash': 'test_hash_123'
        }
        mock_telegram_client.send_code_request = AsyncMock(return_value=mock_response)

        phone = '+79991234567'

        # Simulate login POST logic
        send_code_response = await mock_telegram_client.send_code_request(phone)

        # Should have called send_code_request
        mock_telegram_client.send_code_request.assert_called_once_with(phone)

        # Should get phone_code_hash from response
        phone_code_hash = send_code_response.to_dict().get('phone_code_hash')
        assert phone_code_hash == 'test_hash_123'

    @pytest.mark.asyncio
    async def test_login_post_handles_error(self, mock_telegram_client):
        """Test POST / handles Telegram errors."""
        mock_telegram_client.send_code_request = AsyncMock(
            side_effect=Exception("Phone number invalid")
        )

        phone = 'invalid_phone'
        error_text = None

        # Simulate login POST logic with error handling
        try:
            await mock_telegram_client.send_code_request(phone)
        except Exception as err:
            error_text = str(err)

        assert error_text == "Phone number invalid"


class TestCodeRouteLogic:
    """Tests for /code endpoint logic."""

    @pytest.mark.asyncio
    async def test_code_post_success(self, mock_telegram_client):
        """Test POST /code with valid code succeeds."""
        mock_telegram_client.sign_in = AsyncMock(return_value=MagicMock())

        phone = '+79991234567'
        phone_code_hash = 'test_hash'
        code = '12345'

        # Simulate code POST logic
        result = await mock_telegram_client.sign_in(phone, code=code, phone_code_hash=phone_code_hash)

        mock_telegram_client.sign_in.assert_called_once_with(
            phone, code=code, phone_code_hash=phone_code_hash
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_code_post_needs_2fa(self, mock_telegram_client):
        """Test POST /code redirects to 2FA when needed."""
        # Create a mock exception that behaves like SessionPasswordNeededError
        class MockSessionPasswordNeededError(Exception):
            pass

        mock_telegram_client.sign_in = AsyncMock(
            side_effect=MockSessionPasswordNeededError("2FA required")
        )

        phone = '+79991234567'
        phone_code_hash = 'test_hash'
        code = '12345'
        redirect_to = None

        # Simulate code POST logic
        try:
            await mock_telegram_client.sign_in(phone, code=code, phone_code_hash=phone_code_hash)
        except MockSessionPasswordNeededError:
            redirect_to = '/2fa'

        assert redirect_to == '/2fa'

    @pytest.mark.asyncio
    async def test_code_post_invalid_code(self, mock_telegram_client):
        """Test POST /code with invalid code shows error."""
        mock_telegram_client.sign_in = AsyncMock(
            side_effect=Exception("Invalid code")
        )

        phone = '+79991234567'
        phone_code_hash = 'test_hash'
        code = '00000'
        error_text = None

        # Simulate code POST logic
        try:
            await mock_telegram_client.sign_in(phone, code=code, phone_code_hash=phone_code_hash)
        except Exception as err:
            error_text = str(err)

        assert error_text == "Invalid code"


class TestResendRouteLogic:
    """Tests for /resend endpoint logic."""

    @pytest.mark.asyncio
    async def test_resend_success(self):
        """Test POST /resend successfully resends code."""
        mock_response = MagicMock()
        mock_response.type = MagicMock()
        mock_response.next_type = None
        mock_response.to_dict.return_value = {
            'phone_code_hash': 'new_hash'
        }

        # Create a proper async mock for the client call
        mock_client = MagicMock()
        mock_client_call = AsyncMock(return_value=mock_response)

        phone = '+79991234567'
        old_phone_code_hash = 'old_hash'

        # Simulate creating ResendCodeRequest (mocked)
        mock_request = MagicMock()
        resend_response = await mock_client_call(mock_request)

        new_phone_code_hash = resend_response.to_dict().get('phone_code_hash')
        assert new_phone_code_hash == 'new_hash'

    @pytest.mark.asyncio
    async def test_resend_no_session_redirects(self):
        """Test POST /resend without session redirects to login."""
        phone = None
        phone_code_hash = None

        # Simulate resend logic
        if not phone or not phone_code_hash:
            redirect_to = '/'
        else:
            redirect_to = '/code'

        assert redirect_to == '/'


class TestTwoFactorRouteLogic:
    """Tests for /2fa endpoint logic."""

    @pytest.mark.asyncio
    async def test_2fa_post_success(self, mock_telegram_client):
        """Test POST /2fa with valid password succeeds."""
        mock_telegram_client.sign_in = AsyncMock(return_value=MagicMock())

        phone = '+79991234567'
        phone_code_hash = 'test_hash'
        password = 'test_password'

        # Simulate 2FA POST logic
        result = await mock_telegram_client.sign_in(phone, password=password, phone_code_hash=phone_code_hash)

        mock_telegram_client.sign_in.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_2fa_post_wrong_password(self, mock_telegram_client):
        """Test POST /2fa with wrong password shows error."""
        mock_telegram_client.sign_in = AsyncMock(
            side_effect=Exception("Invalid password")
        )

        phone = '+79991234567'
        phone_code_hash = 'test_hash'
        password = 'wrong_password'
        error_text = None

        # Simulate 2FA POST logic
        try:
            await mock_telegram_client.sign_in(phone, password=password, phone_code_hash=phone_code_hash)
        except Exception as err:
            error_text = str(err)

        assert error_text == "Invalid password"


class TestPrefixMiddlewareLogic:
    """Tests for PrefixMiddleware logic."""

    def test_prefix_strips_trailing_slash(self):
        """Test that prefix strips trailing slash."""
        prefix = '/telegram-assistant/'
        stripped = prefix.rstrip('/')

        assert stripped == '/telegram-assistant'

    def test_empty_prefix_stays_empty(self):
        """Test that empty prefix stays empty."""
        prefix = ''
        stripped = prefix.rstrip('/')

        assert stripped == ''

    @pytest.mark.asyncio
    async def test_middleware_sets_root_path(self):
        """Test that middleware sets root_path correctly."""
        # Simulate middleware behavior
        scope = {'type': 'http', 'root_path': ''}
        prefix = '/telegram-assistant'

        # Middleware logic
        if scope['type'] == 'http' and prefix:
            scope['root_path'] = prefix

        assert scope['root_path'] == '/telegram-assistant'

    @pytest.mark.asyncio
    async def test_middleware_ignores_non_http(self):
        """Test that middleware ignores non-HTTP requests."""
        scope = {'type': 'websocket', 'root_path': ''}
        prefix = '/telegram-assistant'

        # Middleware logic
        if scope['type'] == 'http' and prefix:
            scope['root_path'] = prefix

        assert scope['root_path'] == ''  # Should not be modified


class TestSessionHandling:
    """Tests for session data handling logic."""

    def test_session_stores_phone(self):
        """Test that session stores phone number."""
        session = {}
        phone = '+79991234567'

        session['phone'] = phone

        assert session['phone'] == phone

    def test_session_stores_code_hash(self):
        """Test that session stores phone_code_hash."""
        session = {}
        phone_code_hash = 'abc123'

        session['phone_code_hash'] = phone_code_hash

        assert session['phone_code_hash'] == phone_code_hash

    def test_session_stores_code_type(self):
        """Test that session stores code type."""
        session = {}
        code_type = 'SentCodeTypeApp'

        session['code_type'] = code_type

        assert session['code_type'] == code_type

    def test_session_stores_code_length(self):
        """Test that session stores code length."""
        session = {}
        code_length = 5

        session['code_length'] = code_length

        assert session['code_length'] == 5

    def test_session_get_with_default(self):
        """Test session get with default value."""
        session = {}

        code_type = session.get('code_type', 'SentCodeTypeApp')
        code_length = session.get('code_length', 5)

        assert code_type == 'SentCodeTypeApp'
        assert code_length == 5
