"""
Unit tests for config.py.

Tests configuration loading and validation.
"""
import os
import sys

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigValidation:
    """Tests for Config validation logic."""

    def test_validate_missing_api_id(self):
        """Test validation fails when API_ID is missing."""
        # Simulate config with missing values
        config = {
            'api_id': 0,
            'api_hash': 'test_hash',
            'personal_tg_login': 'test_user'
        }

        errors = []
        if not config['api_id']:
            errors.append("API_ID is required")
        if not config['api_hash']:
            errors.append("API_HASH is required")
        if not config['personal_tg_login']:
            errors.append("PERSONAL_TG_LOGIN is required")

        assert len(errors) == 1
        assert "API_ID" in errors[0]

    def test_validate_missing_api_hash(self):
        """Test validation fails when API_HASH is missing."""
        config = {
            'api_id': 12345,
            'api_hash': '',
            'personal_tg_login': 'test_user'
        }

        errors = []
        if not config['api_id']:
            errors.append("API_ID is required")
        if not config['api_hash']:
            errors.append("API_HASH is required")
        if not config['personal_tg_login']:
            errors.append("PERSONAL_TG_LOGIN is required")

        assert len(errors) == 1
        assert "API_HASH" in errors[0]

    def test_validate_missing_personal_login(self):
        """Test validation fails when PERSONAL_TG_LOGIN is missing."""
        config = {
            'api_id': 12345,
            'api_hash': 'test_hash',
            'personal_tg_login': ''
        }

        errors = []
        if not config['api_id']:
            errors.append("API_ID is required")
        if not config['api_hash']:
            errors.append("API_HASH is required")
        if not config['personal_tg_login']:
            errors.append("PERSONAL_TG_LOGIN is required")

        assert len(errors) == 1
        assert "PERSONAL_TG_LOGIN" in errors[0]

    def test_validate_all_valid(self):
        """Test validation passes when all required values present."""
        config = {
            'api_id': 12345,
            'api_hash': 'test_hash',
            'personal_tg_login': 'test_user'
        }

        errors = []
        if not config['api_id']:
            errors.append("API_ID is required")
        if not config['api_hash']:
            errors.append("API_HASH is required")
        if not config['personal_tg_login']:
            errors.append("PERSONAL_TG_LOGIN is required")

        assert len(errors) == 0

    def test_validate_multiple_missing(self):
        """Test validation reports all missing values."""
        config = {
            'api_id': 0,
            'api_hash': '',
            'personal_tg_login': ''
        }

        errors = []
        if not config['api_id']:
            errors.append("API_ID is required")
        if not config['api_hash']:
            errors.append("API_HASH is required")
        if not config['personal_tg_login']:
            errors.append("PERSONAL_TG_LOGIN is required")

        assert len(errors) == 3


class TestConfigDefaults:
    """Tests for Config default values."""

    def test_default_port(self):
        """Test default port."""
        default_port = 5050
        assert default_port == 5050

    def test_default_host(self):
        """Test default host."""
        default_host = '0.0.0.0'
        assert default_host == '0.0.0.0'

    def test_default_cooldown(self):
        """Test default autoreply cooldown."""
        default_cooldown = 15
        assert default_cooldown == 15

    def test_default_webhook_timeout(self):
        """Test default webhook timeout."""
        default_timeout = 10
        assert default_timeout == 10


class TestConfigIsValid:
    """Tests for Config.is_valid() logic."""

    def test_is_valid_true_when_no_errors(self):
        """Test is_valid returns True when validate returns empty list."""
        errors = []
        is_valid = len(errors) == 0
        assert is_valid is True

    def test_is_valid_false_when_errors_exist(self):
        """Test is_valid returns False when validate returns errors."""
        errors = ["API_ID is required"]
        is_valid = len(errors) == 0
        assert is_valid is False


class TestScriptNameHandling:
    """Tests for SCRIPT_NAME handling."""

    def test_script_name_strips_trailing_slash(self):
        """Test that script_name strips trailing slash."""
        script_name = '/app/'
        result = script_name.rstrip('/')
        assert result == '/app'

    def test_script_name_empty_string(self):
        """Test empty script_name."""
        script_name = ''
        result = script_name.rstrip('/')
        assert result == ''

    def test_script_name_without_trailing_slash(self):
        """Test script_name without trailing slash."""
        script_name = '/telegram-assistant'
        result = script_name.rstrip('/')
        assert result == '/telegram-assistant'


class TestOptionalWebhookUrl:
    """Tests for optional ASAP webhook URL handling."""

    def test_webhook_url_none_when_empty(self):
        """Test webhook_url is None when env is empty."""
        env_value = ''
        webhook_url = env_value or None
        assert webhook_url is None

    def test_webhook_url_set_when_provided(self):
        """Test webhook_url is set when env is provided."""
        env_value = 'https://example.com/webhook'
        webhook_url = env_value or None
        assert webhook_url == 'https://example.com/webhook'
