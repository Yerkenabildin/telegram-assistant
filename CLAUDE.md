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

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TELEGRAM USER CLIENT                      │
└────────────────────┬────────────────────────────────────────┘
                     │ (via Telegram Protocol)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  TELETHON CLIENT (TelegramClient)            │
│                   - Session: ./storage/session              │
│                   - Event handlers for commands & messages  │
└────┬────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────┬──────────────┐
│  Settings DB   │   Reply DB   │
│  (models.py)   │  (models.py) │
└────────────────┴──────────────┘
          │
          ▼
   [SQLite Database]
  ./storage/database.db

┌───────────────────────────────────────┐
│     WEB INTERFACE (Quart Server)      │
│         Port 5050 (default)           │
│  - Authentication Flow                │
│  - Health Check Endpoint              │
└───────────────────────────────────────┘
```

The application runs two async services concurrently via `asyncio.gather()`:
1. **Hypercorn/Quart web server** (port 5050): Handles Telegram authentication flow via web UI
2. **Telethon client**: Monitors incoming/outgoing messages and sends auto-replies

### Key Components

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | ~461 | Entry point, Quart routes, Telethon event handlers |
| `models.py` | ~99 | SQLite ORM models (Reply, Settings) using sqlitemodel |
| `templates/` | 4 files | HTML templates for auth flow (phone, code, 2fa, success) |
| `./storage/` | - | Persistent data directory (session file, database) |

### Module Dependencies

```
main.py
├── models.py (Reply, Settings)
├── Telethon (TelegramClient, events, types)
├── Quart (web framework)
├── Hypercorn (ASGI server)
└── aiohttp (webhook calls)

models.py
├── sqlitemodel (ORM)
└── telethon.extensions.BinaryReader (message deserialization)
```

## Common Commands

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python main.py

# Run tests
pytest tests/ -v --cov=. --cov-report=term-missing

# Run specific test file
pytest tests/test_models.py -v
```

### Docker
```bash
# Build image
docker build -t telegram-assistant:0.0.1 .

# Run with Docker Compose
docker-compose up -d

# View logs
docker logs -f telegram-assistant
```

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `API_ID` | YES | - | Telegram API ID (from my.telegram.org) |
| `API_HASH` | YES | - | Telegram API hash |
| `PERSONAL_TG_LOGIN` | YES | - | Username/ID for ASAP notifications |
| `AVAILABLE_EMOJI_ID` | NO | `5810051751654460532` | Emoji status ID that disables auto-reply |
| `ASAP_WEBHOOK_URL` | NO | - | Webhook URL for urgent message notifications |
| `SECRET_KEY` | NO | `os.urandom(24)` | Session encryption key |
| `SCRIPT_NAME` | NO | - | Reverse proxy path prefix |

## Event Handlers

Main Telethon event handlers in `main.py`:

| Handler | Pattern | Direction | Location | Purpose |
|---------|---------|-----------|----------|---------|
| `debug_outgoing` | All | Outgoing | Any | Logging (line 190-192) |
| `select_settings_chat` | `/autoreply-settings` | Outgoing | Any | Configure settings chat (line 195-216) |
| `disable_autoreply` | `/autoreply-off` | Outgoing | Settings chat | Disable bot (line 219-244) |
| `setup_response` | `/set_for <emoji>` | Outgoing | Settings chat | Bind emoji to reply (line 247-290) |
| `setup_response_current_status` | `/set` | Outgoing | Settings chat | Bind current status to reply (line 293-339) |
| `asap_handler` | `.*ASAP.*` | Incoming | Private | Urgent notification (line 342-381) |
| `new_messages` | All | Incoming | Private | Auto-reply logic (line 384-414) |

## Web Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/health` | GET | Health check (returns telethon connection/auth status) |
| `/` | GET/POST | Phone number input for authentication |
| `/code` | GET/POST | Verification code input |
| `/resend` | POST | Request code re-delivery |
| `/2fa` | GET/POST | Two-factor authentication password |

## Data Persistence

### Database Schema

**Table: `replays`** (Note: historical typo in table name)
```sql
CREATE TABLE replays (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  emoji TEXT,           -- Custom emoji document ID
  _message TEXT         -- Serialized Telethon Message object (binary)
);
```

**Table: `settings`**
```sql
CREATE TABLE settings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT,             -- Setting identifier
  value TEXT            -- Setting value
);
```

### Files
- Session file: `./storage/session` (Telethon auth token)
- Database: `./storage/database.db` (SQLite)

## Authentication Flow

```
1. User visits / → phone.html (if not authorized)
2. User submits phone → Telegram sends code → /code
3. User submits code → Success OR /2fa (if 2FA enabled)
4. [Optional] User submits 2FA password → Success
```

Session data stored in Quart's encrypted session cookie (phone, phone_code_hash, code_type, code_length).

## Auto-Reply Flow

```
Incoming private message:
├─ Check: User has emoji_status set?
│  └─ No → Exit
├─ Check: Template exists for current emoji_status in Reply table?
│  └─ No → Exit
├─ Check: Rate limit (15+ minutes since last message to this sender)?
│  └─ No → Exit
└─ Send templated reply to sender
```

## Testing

### Test Structure
```
tests/
├── __init__.py
├── conftest.py          # Shared fixtures
├── test_models.py       # Reply and Settings model tests
├── test_routes.py       # Quart web route tests
└── test_handlers.py     # Telethon event handler tests
```

### Running Tests
```bash
# All tests with coverage
pytest tests/ -v --cov=. --cov-report=html

# Unit tests only (no integration)
pytest tests/ -v -m "not integration"

# Specific test
pytest tests/test_models.py::TestReply::test_create_new_reply -v
```

## Known Issues / Technical Debt

1. **Table name typo**: `replays` instead of `replies` in models.py:15
2. **Unused dependencies**: `requests`, `aiofiles`, `pyhumps`, `Flask` in requirements.txt
3. **Hardcoded port**: 5050 in main.py:433 (should be env variable)
4. **No input validation**: Phone number format not validated server-side
5. **No rate limiting**: Web routes lack rate limiting protection
6. **Print-based logging**: Should use Python's logging module with levels

## Code Style

- Use type hints for function parameters and return values
- Follow PEP 8 conventions
- Russian language for user-facing messages (Telegram replies, web UI)
- English for code comments and logging
