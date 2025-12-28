# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram auto-responder bot that:
- Authenticates users via Telegram using Telethon client
- Automatically responds to incoming private messages based on emoji status
- Supports custom emoji-based message templates stored in SQLite
- Notifies when urgency keyword "ASAP" is detected
- Runs a Quart web server for authentication alongside the Telethon event loop

## Architecture

The application runs two async services concurrently:
1. **Quart web server** (port 8000): Handles Telegram authentication flow via web UI
2. **Telethon client**: Monitors incoming messages and sends auto-replies

Key components:
- `main.py`: Entry point, Quart routes, Telethon event handlers
- `models.py`: SQLite ORM model for storing emoji-to-message mappings
- `templates/`: HTML templates for authentication flow (phone, code, 2FA, success)
- `./storage/`: Persistent data directory (session file, database)

## Common Commands

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python main.py
```

### Docker
```bash
# Build image
docker build -t telegram-assistant:0.0.1 .

# Run with Docker Compose
docker-compose up -d

# View logs
docker logs -f tg-helper
```

## Environment Variables

Required environment variables (set before running):
- `API_ID`: Telegram API ID (from my.telegram.org)
- `API_HASH`: Telegram API hash
- `PERSONAL_TG_LOGIN`: Your personal Telegram username/ID for notifications
- `AVAILABLE_EMOJI_ID` (optional): Emoji status ID that disables auto-reply (default: 5810051751654460532)
- `ASAP_WEBHOOK_URL` (optional): Webhook URL to call when ASAP message is detected (POST request with JSON payload: `{sender_username, sender_id, message}`)

## Event Handlers

Main Telethon event handlers in main.py:

1. **select_settings_chat**: Triggered by `/autoreply-settings` command (outgoing)
   - Saves current chat as the settings chat for autoreply configuration
   - Enables the autoreply bot functionality
   - Deletes the command message after processing

2. **disable_autoreply**: Triggered by `/autoreply-off` command (outgoing, only in settings chat)
   - Disables the autoreply bot by clearing the settings chat
   - Deletes the command message after processing

3. **setup_response**: Triggered by `/set_for` command (outgoing, only in settings chat)
   - Creates/updates emoji-to-message mapping in database
   - Expects exactly one custom emoji entity in the message
   - Must be a reply to the message to use as auto-reply template

4. **setup_response_current_status**: Triggered by `/set` command (outgoing, only in settings chat)
   - Creates/updates emoji-to-message mapping for the current account emoji status
   - Uses the user's current emoji status instead of requiring an emoji in the command
   - Must be a reply to the message to use as auto-reply template

5. **ASAP handler**: Detects urgent messages containing "asap" (case-insensitive)
   - Only processes private messages
   - Checks if user is available (emoji status != available_emoji_id)
   - Forwards urgent notification to personal account
   - Calls webhook if `ASAP_WEBHOOK_URL` is configured

6. **Auto-reply handler**: Sends pre-configured responses
   - Only processes private messages
   - Looks up message template based on current emoji status
   - Rate limits: Only sends if 15+ minutes since last message to that user

## Data Persistence

- Session file: `./storage/session` (Telethon auth token)
- Database: `./storage/database.db` (SQLite with Reply and Settings tables)
- Reply table schema: `emoji` (TEXT), `_message` (serialized Telethon Message object)
- Settings table schema: `key` (TEXT), `value` (TEXT) - stores `settings_chat_id` for the active settings chat

## Authentication Flow

Web routes for Telegram auth:
1. `/` - Phone number input
2. `/code` - Verification code input
3. `/2fa` - Two-factor authentication password (if enabled)
4. Success page displayed after authorization

Session data stored in Quart's encrypted session cookie (phone, phone_code_hash).
