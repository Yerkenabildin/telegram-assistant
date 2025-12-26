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
- `WORK_TG_LOGIN`: Work Telegram username/ID allowed to set auto-replies
- `AVAILABLE_EMOJI_ID` (optional): Emoji status ID that disables auto-reply (default: 5810051751654460532)

## Event Handlers

Three main Telethon event handlers in main.py:

1. **setup_response** (line 101): Triggered by `/set_for` command from work account
   - Creates/updates emoji-to-message mapping in database
   - Expects exactly one custom emoji entity in the message

2. **ASAP handler** (line 128): Detects urgent messages containing "asap" (case-insensitive)
   - Only processes private messages
   - Checks if user is available (emoji status != available_emoji_id)
   - Forwards urgent notification to personal account

3. **Auto-reply handler** (line 153): Sends pre-configured responses
   - Only processes private messages
   - Looks up message template based on current emoji status
   - Rate limits: Only sends if 15+ minutes since last message to that user

## Data Persistence

- Session file: `./storage/session` (Telethon auth token)
- Database: `./storage/database.db` (SQLite with Reply table)
- Table schema: `emoji` (TEXT), `_message` (serialized Telethon Message object)

## Authentication Flow

Web routes for Telegram auth:
1. `/` - Phone number input
2. `/code` - Verification code input
3. `/2fa` - Two-factor authentication password (if enabled)
4. Success page displayed after authorization

Session data stored in Quart's encrypted session cookie (phone, phone_code_hash).
