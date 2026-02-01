# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram auto-responder bot that:
- Authenticates users via Telegram bot interface
- Automatically responds to incoming private messages based on emoji status
- Supports custom emoji-based message templates stored in SQLite
- Notifies when urgency keyword "ASAP" is detected
- Runs a Quart web server for API endpoints alongside the Telethon event loop

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
│     API SERVER (Quart/Hypercorn)      │
│         Port 5050 (default)           │
│  - Health Check Endpoint              │
│  - Meeting API                        │
└───────────────────────────────────────┘
```

The application runs up to three async services concurrently via `asyncio.gather()`:
1. **Hypercorn/Quart web server** (port 5050): Provides health check and meeting API
2. **Telethon user client**: Monitors incoming/outgoing messages and sends auto-replies
3. **Telethon bot client** (required): Provides authentication and control interface

### Key Components

| File | Purpose |
|------|---------|
| `main.py` | Entry point, orchestrates all services via asyncio.gather() |
| `config.py` | Centralized configuration from environment variables |
| `logging_config.py` | Structured logging setup |
| `handlers.py` | User client event handlers (commands, auto-reply, mentions) |
| `bot_handlers.py` | Bot client handlers with inline keyboards and auth |
| `routes.py` | API routes (health, meeting) |
| `models.py` | SQLite ORM models (Reply, Settings, Schedule) |
| `services/autoreply_service.py` | Auto-reply logic and rate limiting |
| `services/notification_service.py` | ASAP alerts and webhook calls |
| `services/context_extraction_service.py` | Anchor-based context extraction for mentions |
| `services/mention_service.py` | Mention notification logic and formatting |
| `services/yandex_gpt_service.py` | AI summarization with chunking support |
| `services/productivity_service.py` | Daily productivity summary collection and generation |
| `services/caldav_service.py` | CalDAV calendar integration for automatic meeting status |
| `./storage/` | Persistent data directory (session file, database) |

### Module Dependencies

```
main.py
├── config.py (Config singleton)
├── logging_config.py (structured logging)
├── handlers.py (user client handlers)
├── bot_handlers.py (bot client handlers)
├── routes.py (Quart routes)
├── models.py (Reply, Settings, Schedule)
├── Telethon (TelegramClient, events, types)
├── Quart (web framework)
├── Hypercorn (ASGI server)
└── aiohttp (webhook calls)

handlers.py
├── services/autoreply_service.py
├── services/notification_service.py
└── services/mention_service.py

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
| `AVAILABLE_EMOJI_ID` | NO | - | Emoji status ID that means user is "online" (disables auto-reply and mention notifications) |
| `ASAP_WEBHOOK_URL` | NO | - | Webhook URL for urgent message notifications |
| `SECRET_KEY` | NO | `os.urandom(24)` | Session encryption key |
| `SCRIPT_NAME` | NO | - | Reverse proxy path prefix |
| `TIMEZONE` | NO | `Europe/Moscow` | Timezone for schedule (e.g., `Europe/Moscow`, `UTC`) |
| `MEETING_API_TOKEN` | NO | - | API token for `/api/meeting` endpoint (if not set, no auth required) |
| `BOT_TOKEN` | NO | - | Telegram bot token from @BotFather for control interface |
| `ALLOWED_USERNAME` | NO | - | Restrict bot authentication to this username only |
| `MENTION_MESSAGE_LIMIT` | NO | `50` | Maximum messages to fetch for mention context |
| `MENTION_TIME_LIMIT_MINUTES` | NO | `30` | Maximum age (in minutes) of messages to include in context |
| `YANDEX_API_KEY` | NO | - | Yandex Cloud API key or IAM token for AI summarization |
| `YANDEX_FOLDER_ID` | NO | - | Yandex Cloud folder ID (required if using Yandex GPT) |
| `YANDEX_GPT_MODEL` | NO | `yandexgpt` | Model name (`yandexgpt` for quality, `yandexgpt-lite` for speed) |
| `VIP_USERNAMES` | NO | - | Comma-separated usernames whose mentions are always urgent |
| `ONLINE_MENTION_DELAY_MINUTES` | NO | `10` | Delay before sending online notifications (skipped if message read) |
| `PRODUCTIVITY_SUMMARY_TIME` | NO | - | Time for daily productivity summary (HH:MM format, e.g., `19:00`) |
| `CALDAV_CHECK_INTERVAL` | NO | `60` | How often to check calendar (in seconds) |

## Event Handlers

Main Telethon event handlers in `handlers.py`:

| Handler | Pattern | Direction | Location | Purpose |
|---------|---------|-----------|----------|---------|
| `debug_outgoing` | All | Outgoing | Any | Logging |
| `select_settings_chat` | `/autoreply-settings` | Outgoing | Any | Configure settings chat |
| `disable_autoreply` | `/autoreply-off` | Outgoing | Settings chat | Disable bot |
| `setup_response` | `/set_for <emoji>` | Outgoing | Settings chat | Bind emoji to reply |
| `setup_response_current_status` | `/set` | Outgoing | Settings chat | Bind current status to reply |
| `asap_handler` | `.*ASAP.*` | Incoming | Private | Urgent notification |
| `group_mention_handler` | All | Incoming | Groups | Mention notifications |
| `private_message_context_handler` | All | Incoming | Private | Private message context notifications |
| `new_messages` | All | Incoming | Private | Auto-reply logic |

Bot handlers in `bot_handlers.py` provide inline keyboard interface for the same functionality.

## API Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/health` | GET | Health check (returns telethon connection/auth status) |
| `/api/meeting` | POST | Meeting status control (Zoom integration) |

### Meeting API

Control emoji status during meetings (e.g., Zoom calls):

**Setup (in Telegram settings chat):**
- `/meeting <emoji>` — set default meeting emoji
- `/meeting` — show current settings
- `/meeting clear` — clear default emoji

**API calls:**
```bash
# Start meeting - uses saved emoji (set via /meeting command)
curl -X POST "http://localhost:5050/api/meeting?action=start"

# Start meeting - with explicit emoji
curl -X POST "http://localhost:5050/api/meeting?action=start&emoji_id=5368324170671202286"

# End meeting - restore scheduled emoji
curl -X POST "http://localhost:5050/api/meeting?action=end"

# With authentication (if MEETING_API_TOKEN is set)
curl -X POST "http://localhost:5050/api/meeting?action=start&token=your-token"
```

Priority: Meeting (50) is above Work (10) but below Override (100), so vacation status won't be overwritten.

## CalDAV Calendar Integration

Automatically set meeting status based on calendar events. All configuration is done via bot interface.

### Setup

1. Open bot → **📆 Календарь** → **⚙️ Настроить CalDAV**

2. Configure connection:
   - **🌐 URL сервера** — CalDAV server URL
   - **👤 Логин** — username (usually email)
   - **🔑 Пароль** — password or app-specific password

3. Set meeting emoji (used for both calendar and Meeting API):
   - Bot → **📅 Расписание** → configure meeting emoji

4. Test connection:
   - Bot → **📆 Календарь** → **🔗 Проверить подключение**

### How it works

```
Calendar event starts:
├─ calendar_checker detects active event (checks every 60s)
├─ Creates Schedule rule with PRIORITY_MEETING (50)
├─ Updates Telegram emoji status immediately
└─ Meeting status is active

Calendar event ends:
├─ calendar_checker detects no active event
├─ Removes meeting Schedule rule
├─ Restores scheduled emoji (work/weekend/rest)
└─ Normal schedule resumes
```

### Features

- **Bot configuration**: All settings are done via bot interface, no environment variables needed
- **All-day events**: Supported, treated as 00:00-23:59
- **Priority**: Calendar meetings use PRIORITY_MEETING (50)
  - Higher than work schedule (10)
  - Lower than manual overrides (100)
- **Shared emoji**: Uses the same meeting emoji as Meeting API

### Supported CalDAV servers

- Yandex Calendar: `https://caldav.yandex.ru`
- Google Calendar: `https://apidata.googleusercontent.com/caldav/v2` (requires app password)
- iCloud: `https://caldav.icloud.com`
- Nextcloud: `https://your-server.com/remote.php/dav/calendars/`
- Any standard CalDAV server

## Bot Control Interface

Optional Telegram bot with inline keyboard interface. Requires `BOT_TOKEN` environment variable.

### Setup
1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get the bot token
3. Set `BOT_TOKEN` environment variable
4. Start the application - bot will run alongside the user client

### Features

**Authentication** (`/start` when not authorized):
- Shows authentication flow if user client is not authorized
- If `ALLOWED_USERNAME` is set, only that user can authenticate
- Guides through phone → code → 2FA (if needed) → success

**Main Menu** (`/start` when authorized):
The bot responds only to the authorized user (owner of the user client session).
- 📊 **Статус** - View current status (schedule, replies count, meeting)
- 📝 **Автоответы** - Manage auto-replies (list, add via emoji + text)
- 📅 **Расписание** - Schedule management (list, enable/disable, clear)
- 📞 **Встречи** - Meeting control (start/end call)
- ⚙️ **Настройки** - Settings (disable autoreply)

### Adding Auto-Reply via Bot
1. Send a custom emoji to the bot
2. Bot asks for reply text
3. Send the reply message
4. Auto-reply is saved for that emoji status

### Text Commands (in settings chat)

**Meeting commands** (Zoom/calls integration):
- `/meeting` - Show current meeting emoji settings
- `/meeting <emoji>` - Set default emoji for meetings
- `/meeting clear` - Clear meeting emoji setting

**Schedule commands** (emoji status scheduling):
   - `/schedule` - Show help for schedule commands
   - `/schedule work <emoji>` - Set work hours (Mon-Fri 12:00-20:00, priority 10)
   - `/schedule weekends <emoji>` - Set weekends (Fri 20:00 - Sun 23:59, priority 8)
   - `/schedule rest <emoji>` - Set rest time (all other time, priority 1)
   - `/schedule override <dates> <emoji>` - Add temporary override (priority 100, e.g., vacation)
     - Date formats: `25.12-05.01`, `25.12.2024-05.01.2025`
   - `/schedule list` - Show all schedule rules (grouped by type)
   - `/schedule del <ID>` - Delete rule by ID
   - `/schedule clear` - Delete all rules
   - `/schedule on/off` - Enable/disable scheduling
   - `/schedule status` - Show current status

**Schedule checker** (background task, runs every minute):
   - Checks if scheduling is enabled
   - Gets the emoji that should be active based on current time and date
   - Updates Telegram emoji status if it differs from scheduled
   - Automatically deletes expired override rules (every hour)

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
- Database: `./storage/database.db` (SQLite with Reply, Settings, and Schedule tables)
- Reply table schema: `emoji` (TEXT), `_message` (serialized Telethon Message object)
- Settings table schema: `key` (TEXT), `value` (TEXT) - stores `settings_chat_id` and `schedule_enabled`
- Schedule table schema: `emoji_id` (TEXT), `days` (TEXT), `time_start` (TEXT), `time_end` (TEXT), `priority` (INT), `name` (TEXT), `date_start` (TEXT), `date_end` (TEXT)

## Authentication Flow

Authentication is handled through the Telegram bot interface:

```
1. User sends /start to bot → Bot shows auth button (if not authorized)
2. User clicks "Авторизоваться" → Bot shows phone request button
3. User shares phone or types it → Telegram sends code → Bot asks for code
4. User sends code (with dashes: 1-2-3-4-5-6) → Success OR 2FA prompt
5. [Optional] User sends 2FA password → Success
```

Access control:
- If `ALLOWED_USERNAME` is set, only that user can authenticate via bot
- If not set, anyone who can message the bot can authenticate

Settings menu includes "Выйти из аккаунта" to logout and re-authenticate.

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

## Group Mention Notifications

The bot sends notifications about mentions in group chats both when user is online and offline:
- **Offline**: Notification sent immediately via user client to PERSONAL_TG_LOGIN
- **Online + VIP sender**: Notification sent immediately via bot (always urgent)
- **Online + regular sender**: Notification delayed by ONLINE_MENTION_DELAY_MINUTES, skipped if message read

### Flow
```
Incoming group message with @mention:
├─ Check: Is this a group chat (not private)?
│  └─ No → Exit
├─ Check: Does message mention the current user?
│  └─ No → Exit
├─ Determine online status (has work/available emoji?)
├─ Extract context using anchor-based logic:
│  ├─ Find anchor (root of reply chain)
│  ├─ If anchor exists: fetch 30min before anchor + all until mention
│  └─ If no reply chain: fetch last 1 hour of messages
├─ Generate context summary (with chunking for large contexts)
├─ Check urgency:
│  ├─ VIP sender (VIP_USERNAMES) → Always urgent
│  ├─ AI detection (if Yandex GPT configured)
│  └─ Keyword-based detection
└─ Send notification:
   ├─ Offline → immediately via user client to PERSONAL_TG_LOGIN
   ├─ Online + VIP → immediately via bot (urgent)
   └─ Online + non-VIP → schedule with delay:
      ├─ Wait ONLINE_MENTION_DELAY_MINUTES (default: 10)
      ├─ Check if message was read
      ├─ If read → skip notification
      └─ If not read → send via bot
```

### Context Extraction (Anchor-Based)

The bot uses smart context extraction based on reply chains:

1. **With reply chain**: Find the anchor message (root of the thread)
   - Extract 30 min of messages before the anchor
   - Include all messages from anchor to the mention
   - This captures the full discussion context

2. **Without reply chain**: Fallback to time-based extraction
   - Fetch the last 1 hour of messages
   - Filter by time relevance

3. **Chunked summarization**: For large contexts
   - Split messages into chunks (15 messages each)
   - Summarize each chunk with AI
   - Combine chunk summaries into final summary

**Key files:**
- `services/context_extraction_service.py` - Anchor-based context extraction
- `services/yandex_gpt_service.py` - AI summarization with chunking support

### Notification Format
```
🚨 Срочное упоминание в группе!  (or 📢 Упоминание в группе)
🚨 Срочное упоминание (вы онлайн)!  (when online)

📍 Чат: <chat_title>
👤 Призвал: @username (Name)

Контекст:
  > Previous message 1
  > Previous message 2

Сообщение с упоминанием:
  @you can you help with this?
```

### Urgent Keywords
Messages are considered urgent if:
1. Sender is in VIP_USERNAMES list (always urgent)
2. AI detection marks as urgent (if Yandex GPT configured)
3. Any message in context contains urgent keywords:
   - `asap`, `urgent`, `emergency`, `critical`
   - `срочно`, `помогите`, `важно`, `блокер`
   - `blocker`, `prod`, `падает`, `упал`, `авария`, `incident`, `горит`

### Configuration
- `VIP_USERNAMES` - Comma-separated usernames whose mentions are always urgent
- `AVAILABLE_EMOJI_ID` - If set, this emoji means user is "online"
- `MENTION_MESSAGE_LIMIT` - Max messages to fetch for context (default: 50)
- `MENTION_TIME_LIMIT_MINUTES` - Max age of messages in context (default: 30)
- `ONLINE_MENTION_DELAY_MINUTES` - Delay before sending online notifications (default: 10)

Note: If a work schedule emoji is configured, having that emoji also means "online".

### AI Summarization (Yandex GPT)

If `YANDEX_API_KEY` and `YANDEX_FOLDER_ID` are configured, the bot uses Yandex GPT for:
- **Smart summarization** - analyzes context and explains why user was mentioned
- **Urgency detection** - AI determines if the situation requires immediate attention

Without Yandex GPT, the bot falls back to keyword-based topic detection and urgency keywords.

**Setup:**
1. Create a service account in [Yandex Cloud Console](https://console.cloud.yandex.ru/)
2. Get an API key or IAM token
3. Note your folder ID
4. Set environment variables:
   ```
   YANDEX_API_KEY=your-api-key-or-iam-token
   YANDEX_FOLDER_ID=your-folder-id
   YANDEX_GPT_MODEL=yandexgpt  # or yandexgpt-lite for faster/cheaper responses
   ```

## Private Message Notifications

The bot can send notifications about incoming private messages when user is offline.

### Flow
```
Incoming private message:
├─ Check: Is private notification enabled?
│  └─ No → Exit
├─ Check: Is sender a bot?
│  └─ Yes → Exit
├─ Check: Is message empty (sticker, media only)?
│  └─ Yes → Exit
├─ Determine online status (has work/available emoji?)
├─ If online → Skip notification
├─ Fetch recent messages from conversation for context
├─ Generate summary (AI or keyword-based)
├─ Check urgency:
│  ├─ VIP sender → Always urgent
│  ├─ AI detection (if Yandex GPT configured)
│  └─ Keyword-based detection
└─ Send notification via user client to PERSONAL_TG_LOGIN
```

### Notification Format
```
🚨 Срочное личное сообщение!  (or 💬 Личное сообщение)

👤 От: @username (Name)

📌 Тема:
  🆘 Нужна помощь

💬 Контекст разговора:
  «Previous message 1»
  «Previous message 2»

✉️ Сообщение:
  «Can you help me with this?»

🔗 Открыть диалог: https://t.me/username
```

### Configuration

**Via Bot Interface:**
1. Open bot menu → 🔔 Контекст призыва → 💬 Личные сообщения
2. Enable/disable private message notifications

**Database setting:**
- `private_notification_enabled` - Enable/disable private message notifications (default: false)

**Webhook integration:**
- If `ASAP_WEBHOOK_URL` is configured, it will be called when a private message notification is sent
- Uses the same webhook format as ASAP notifications

Note: Same urgency detection and VIP sender logic applies as for group mentions.

## Daily Productivity Summary

The bot can generate daily productivity summaries analyzing all your outgoing messages.

### Features
- **Message collection**: Efficiently scans dialogs and collects only YOUR outgoing messages
- **Per-chat summaries**: Generates brief summary for each chat (what you discussed)
- **Overall insights**: AI-generated highlights of your day (if Yandex GPT configured)
- **Keyword detection**: Falls back to keyword-based summaries without AI

### Flow
```
End of day (configured time):
├─ Iterate through dialogs with today's activity
├─ For each dialog, fetch outgoing messages (from_user=me filter)
├─ Skip dialogs with no outgoing messages
├─ Group by chat and generate per-chat summary
├─ Generate overall daily insights (AI or keyword-based)
└─ Send summary via bot (preferred) or user client
```

### Configuration

**Via Bot Interface:**
1. Open bot menu → 📊 Продуктивность
2. Set time for daily summary (e.g., 19:00)
3. Enable automatic sending

**Settings:**
- `PRODUCTIVITY_SUMMARY_TIME` (env var) - Time for daily summary (HH:MM format)
- Database settings:
  - `productivity_summary_enabled` - Enable/disable automatic sending
  - `productivity_summary_time` - Time for daily summary

### Output Format
```
📊 **Продуктивность за 31.01.2026**

📨 Всего сообщений: **42**
💬 Активных чатов: **5**

**Главное за день:**
- Обсудил архитектуру с командой backend
- Провёл ревью 3 PR
- Помог коллегам с вопросами по API

**По чатам:**
👥 **Backend Team** (15 сообщ.)
   └ Обсуждал: ревью кода, деплой
👤 **Вася Пупкин** (10 сообщ.)
   └ Помогал с настройкой окружения
...
```

### Key Files
- `services/productivity_service.py` - Core service for message collection and summarization
- `bot_handlers.py` - Bot interface for productivity menu
- `main.py` - Background scheduler for automatic sending

## Testing

### Test Structure
```
tests/
├── __init__.py
├── conftest.py               # Shared fixtures
├── test_models.py            # Reply and Settings model tests
├── test_routes.py            # Quart web route tests
├── test_handlers.py          # Telethon event handler tests
├── test_services.py          # Service layer tests
└── test_context_extraction.py # Context extraction service tests
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

1. **Table name typo**: `replays` instead of `replies` in models.py
2. **Unused dependencies**: `requests`, `aiofiles`, `pyhumps`, `Flask` in requirements.txt
3. **No input validation**: Phone number format not validated server-side
4. **No rate limiting**: Web routes lack rate limiting protection

## Code Style

- Use type hints for function parameters and return values
- Follow PEP 8 conventions
- Russian language for user-facing messages (Telegram replies, web UI)
- English for code comments and logging
