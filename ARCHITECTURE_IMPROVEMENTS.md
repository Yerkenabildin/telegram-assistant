# Architecture Improvements Recommendations

This document outlines recommended architectural improvements for the telegram-assistant project, categorized by priority and effort.

## Critical Priority (Security & Reliability)

### 1. Input Validation Layer

**Problem**: No server-side validation for user inputs (phone numbers, verification codes).

**Solution**:
```python
# Create validators.py
import re
from typing import Optional

def validate_phone(phone: str) -> tuple[bool, Optional[str]]:
    """Validate phone number format."""
    pattern = r'^\+?[1-9]\d{6,14}$'
    if not re.match(pattern, phone.replace(' ', '').replace('-', '')):
        return False, "Invalid phone number format"
    return True, None

def validate_code(code: str, expected_length: int = 5) -> tuple[bool, Optional[str]]:
    """Validate verification code."""
    if not code.isdigit():
        return False, "Code must contain only digits"
    if len(code) != expected_length:
        return False, f"Code must be {expected_length} digits"
    return True, None
```

**Effort**: Low (2-3 hours)

---

### 2. Error Handling Improvements

**Problem**: Many places lack try-except blocks, leading to potential crashes.

**Critical locations**:
- `main.py:403-405` - `get_messages()` can fail if username is None
- `main.py:354` - `sender.username` can be None
- `models.py:19-21` - BinaryReader deserialization can fail

**Solution**:
```python
# Wrap critical operations
async def new_messages(event):
    try:
        sender = await event.get_sender()
        username = getattr(sender, 'username', None)
        if not username:
            print(f"[WARN] Sender has no username, using ID: {sender.id}")
            username = sender.id
        # ... rest of handler
    except Exception as e:
        print(f"[ERROR] Failed to process message: {e}")
```

**Effort**: Medium (4-6 hours)

---

### 3. Structured Logging

**Problem**: Uses `print()` statements instead of proper logging.

**Solution**:
```python
# Create logging_config.py
import logging
import sys

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger('telegram-assistant')

logger = setup_logging()

# Usage in main.py:
logger.info("Connecting Telethon client...")
logger.error(f"Failed to send code: {err}", exc_info=True)
```

**Effort**: Low (2-3 hours)

---

## High Priority (Maintainability)

### 4. Configuration Management

**Problem**: Hardcoded values scattered across code (port 5050, emoji IDs, timeouts).

**Solution**: Create centralized configuration:
```python
# config.py
from dataclasses import dataclass
from os import environ

@dataclass
class Config:
    api_id: int = int(environ.get('API_ID', 0))
    api_hash: str = environ.get('API_HASH', '')
    personal_tg_login: str = environ.get('PERSONAL_TG_LOGIN', '')
    available_emoji_id: int = int(environ.get('AVAILABLE_EMOJI_ID', 5810051751654460532))
    asap_webhook_url: str = environ.get('ASAP_WEBHOOK_URL', '')
    secret_key: str = environ.get('SECRET_KEY', '')

    # Server settings
    host: str = environ.get('HOST', '0.0.0.0')
    port: int = int(environ.get('PORT', 5050))

    # Rate limiting
    autoreply_cooldown_minutes: int = int(environ.get('AUTOREPLY_COOLDOWN', 15))
    webhook_timeout: int = int(environ.get('WEBHOOK_TIMEOUT', 10))

    # Database
    db_path: str = environ.get('DB_PATH', './storage/database.db')
    session_path: str = environ.get('SESSION_PATH', './storage/session')

config = Config()
```

**Effort**: Medium (3-4 hours)

---

### 5. Dependency Injection for Telethon Client

**Problem**: Global `client` object makes testing difficult.

**Solution**: Wrap in a class or use dependency injection:
```python
# telegram_service.py
from telethon import TelegramClient, events

class TelegramService:
    def __init__(self, session_path: str, api_id: int, api_hash: str):
        self.client = TelegramClient(session_path, api_id, api_hash)
        self._setup_handlers()

    def _setup_handlers(self):
        @self.client.on(events.NewMessage(incoming=True))
        async def handle_incoming(event):
            await self._process_incoming(event)

    async def _process_incoming(self, event):
        # Logic extracted for testability
        pass

    async def connect(self):
        await self.client.connect()

    async def disconnect(self):
        await self.client.disconnect()
```

**Effort**: High (1-2 days)

---

### 6. Separate Handler Logic

**Problem**: Event handlers in `main.py` mix business logic with Telegram API calls.

**Solution**: Extract business logic into service classes:
```python
# services/autoreply_service.py
from datetime import timedelta
from models import Reply, Settings

class AutoReplyService:
    def __init__(self, cooldown_minutes: int = 15):
        self.cooldown = timedelta(minutes=cooldown_minutes)

    def should_send_reply(self, emoji_status_id: int, last_message_time, current_time) -> bool:
        """Determine if auto-reply should be sent."""
        reply = Reply.get_by_emoji(emoji_status_id)
        if reply is None:
            return False

        if last_message_time and (current_time - last_message_time) < self.cooldown:
            return False

        return True

    def get_reply_message(self, emoji_status_id: int):
        """Get the reply message for given emoji status."""
        reply = Reply.get_by_emoji(emoji_status_id)
        return reply.message if reply else None
```

**Effort**: Medium (4-6 hours)

---

## Medium Priority (Code Quality)

### 7. Type Hints Throughout

**Problem**: Missing type hints make code harder to understand and maintain.

**Solution**:
```python
# models.py with type hints
from typing import Optional
from telethon.tl.types import Message

class Reply(Model):
    emoji: str
    _message: bytes

    @property
    def message(self) -> Optional[Message]:
        ...

    @staticmethod
    def create(emoji: str, msg: Message) -> None:
        ...

    @staticmethod
    def get_by_emoji(emoji: int) -> Optional['Reply']:
        ...
```

**Effort**: Low (2-3 hours)

---

### 8. Async Context Managers

**Problem**: Manual resource management (aiohttp sessions, db connections).

**Solution**:
```python
# Use context managers
async def call_webhook(url: str, payload: dict) -> bool:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(url, json=payload) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Webhook failed: {e}")
            return False
```

**Effort**: Low (1-2 hours)

---

### 9. Clean Up Dependencies

**Problem**: Unused packages in requirements.txt bloat the image.

**Remove**:
- `requests` (using aiohttp instead)
- `aiofiles` (not used)
- `pyhumps` (not used)
- `Flask` (using Quart)
- `pyuwsgi` (using Hypercorn)

**Effort**: Low (30 minutes)

---

## Low Priority (Nice to Have)

### 10. Metrics & Monitoring

**Problem**: No visibility into bot usage/performance.

**Solution**: Add Prometheus metrics:
```python
from prometheus_client import Counter, Histogram

AUTOREPLY_SENT = Counter('autoreply_sent_total', 'Total auto-replies sent')
ASAP_ALERTS = Counter('asap_alerts_total', 'Total ASAP alerts triggered')
MESSAGE_PROCESSING_TIME = Histogram('message_processing_seconds', 'Time to process messages')
```

**Effort**: Medium (4-6 hours)

---

### 11. Database Migrations

**Problem**: Schema changes require manual intervention.

**Solution**: Use Alembic for migrations:
```bash
pip install alembic
alembic init migrations
```

**Effort**: Medium (3-4 hours)

---

### 12. Health Check Enhancements

**Problem**: Basic health check doesn't verify database connectivity.

**Solution**:
```python
@app.route("/health")
async def health():
    checks = {
        "telethon_connected": client.is_connected(),
        "telethon_authorized": await client.is_user_authorized() if client.is_connected() else False,
        "database_accessible": check_database(),
    }

    all_healthy = all(checks.values())
    return {
        "status": "ok" if all_healthy else "degraded",
        **checks
    }, 200 if all_healthy else 503

def check_database() -> bool:
    try:
        Settings.get('health_check')
        return True
    except Exception:
        return False
```

**Effort**: Low (1 hour)

---

## Recommended Implementation Order

1. **Phase 1 (Week 1)**: Critical items
   - Input validation
   - Error handling improvements
   - Structured logging

2. **Phase 2 (Week 2)**: High priority
   - Configuration management
   - Clean up dependencies
   - Type hints

3. **Phase 3 (Week 3)**: Medium priority
   - Separate handler logic
   - Async context managers
   - Health check enhancements

4. **Phase 4 (Future)**: Nice to have
   - Dependency injection for Telethon
   - Metrics & monitoring
   - Database migrations

---

## Architecture Diagram (Target State)

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│                    (Entry point only)                            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
│  WebController  │ │ TgService   │ │    Config       │
│  (Quart routes) │ │ (Telethon)  │ │  (Settings)     │
└────────┬────────┘ └──────┬──────┘ └─────────────────┘
         │                 │
         ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Services Layer                              │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │ AuthService     │  │ AutoReply    │  │ NotificationSvc │    │
│  │ (login flow)    │  │ Service      │  │ (ASAP, webhook) │    │
│  └─────────────────┘  └──────────────┘  └─────────────────┘    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                  │
│  ┌─────────────────┐  ┌──────────────┐                          │
│  │ ReplyRepository │  │ SettingsRepo │                          │
│  └─────────────────┘  └──────────────┘                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   SQLite DB     │
                    └─────────────────┘
```

This layered architecture provides:
- **Separation of concerns**: Each layer has a single responsibility
- **Testability**: Services can be unit tested with mocked dependencies
- **Maintainability**: Changes to one layer don't affect others
- **Scalability**: Easy to add new features or swap implementations
