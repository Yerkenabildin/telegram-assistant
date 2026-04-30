"""
Telegram Bot interface for controlling the auto-responder.

Provides inline keyboard interface for managing:
- Auto-replies
- Schedule
- Meetings
- Settings
- Authentication (phone, code, 2FA)
"""
from __future__ import annotations

import re

from telethon import events, Button
from telethon.tl.types import MessageEntityCustomEmoji, DocumentAttributeCustomEmoji
from telethon.tl.functions.messages import GetCustomEmojiDocumentsRequest, DeleteHistoryRequest
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError

# Regex pattern for parsing time format like "09:00-18:00"
TIME_RANGE_PATTERN = re.compile(r'^(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})$')

# Date component pattern
_DATE_PART = r'(\d{1,2}\.\d{1,2}(?:\.\d{4})?)'
_TIME_PART = r'(\d{1,2}:\d{2})'
_SEP = r'\s*[-–—]\s*'


def parse_datetime_range(text: str) -> tuple[str, str, str, str] | None:
    """Parse flexible datetime range formats.

    Supported formats:
    - "06.01-07.01" → (06.01, 00:00, 07.01, 23:59)
    - "06.01 9:30-11:30" → (06.01, 09:30, 06.01, 11:30)
    - "06.01 12:00 - 07.01 15:00" → (06.01, 12:00, 07.01, 15:00)

    Returns:
        Tuple of (date_start, time_start, date_end, time_end) or None if no match
    """
    text = text.strip()

    # Pattern 1: "06.01 12:00 - 07.01 15:00" (full datetime range)
    match = re.match(
        rf'^{_DATE_PART}\s+{_TIME_PART}{_SEP}{_DATE_PART}\s+{_TIME_PART}$',
        text
    )
    if match:
        return (match.group(1), match.group(2), match.group(3), match.group(4))

    # Pattern 2: "06.01 9:30-11:30" (single day with time range)
    match = re.match(
        rf'^{_DATE_PART}\s+{_TIME_PART}{_SEP}{_TIME_PART}$',
        text
    )
    if match:
        date = match.group(1)
        return (date, match.group(2), date, match.group(3))

    # Pattern 3: "06.01-07.01" (date range, full days)
    match = re.match(
        rf'^{_DATE_PART}{_SEP}{_DATE_PART}$',
        text
    )
    if match:
        return (match.group(1), "00:00", match.group(2), "23:59")

    return None

from sqlitemodel import SQL

from config import config
from logging_config import logger
from models import DEFAULT_REPLY_EMOJI, Reply, Settings, Schedule, VipList, PRIORITY_REST, PRIORITY_MORNING, PRIORITY_EVENING, PRIORITY_WEEKENDS, PRIORITY_WORK, PRIORITY_MEETING, PRIORITY_OVERRIDE
from services.caldav_service import caldav_service


# =============================================================================
# Authentication State
# =============================================================================

# Store authentication state per user: {user_id: {phone, phone_code_hash, step}}
# step: 'phone', 'code', '2fa'
_auth_state: dict[int, dict] = {}


# Store owner user ID (set when user client is authorized)
_owner_id: int | None = None
_owner_username: str | None = None
_user_client = None  # User client for sending custom emojis
_bot_username: str | None = None  # Bot username for user client to send messages
_emoji_list_message_id: int | None = None  # Message ID of emoji list from user client
_schedule_list_message_id: int | None = None  # Message ID of schedule list from user client

# Store personal account ID (for notifications recipient who also has bot access)
_personal_id: int | None = None
_personal_username: str | None = None


def _utf16_len(text: str) -> int:
    """Calculate length in UTF-16 code units (what Telegram uses for offsets)."""
    return len(text.encode('utf-16-le')) // 2


def set_owner_id(user_id: int) -> None:
    """Set the owner user ID (from authorized user client)."""
    global _owner_id
    _owner_id = user_id
    logger.info(f"Bot owner set to user ID: {user_id}")


def set_owner_username(username: str) -> None:
    """Set the owner username as fallback."""
    global _owner_username
    _owner_username = username.lower().lstrip('@')
    logger.info(f"Bot owner username set to: {_owner_username}")


def set_bot_username(username: str) -> None:
    """Set the bot username for user client to send messages."""
    global _bot_username
    _bot_username = username
    logger.info(f"Bot username set to: {_bot_username}")


def get_owner_id() -> int | None:
    """Get the owner user ID."""
    return _owner_id


def set_personal_id(user_id: int) -> None:
    """Set the personal account user ID (PERSONAL_TG_LOGIN)."""
    global _personal_id
    _personal_id = user_id
    logger.info(f"Personal account set to user ID: {user_id}")


def set_personal_username(username: str) -> None:
    """Set the personal account username as fallback."""
    global _personal_username
    _personal_username = username.lower().lstrip('@')
    logger.info(f"Personal account username set to: {_personal_username}")


def get_personal_id() -> int | None:
    """Get the personal account user ID."""
    return _personal_id


def clear_personal_account() -> None:
    """Clear the personal account (used when settings are cleared)."""
    global _personal_id, _personal_username
    _personal_id = None
    _personal_username = None
    logger.info("Personal account cleared")


async def _is_owner(event) -> bool:
    """Check if user is the owner."""
    # Check by user ID first
    if _owner_id is not None and event.sender_id == _owner_id:
        return True

    # Fallback: check by username
    if _owner_username:
        sender = await event.get_sender()
        if sender and getattr(sender, 'username', None):
            return sender.username.lower() == _owner_username

    return False


async def _is_personal(event) -> bool:
    """Check if user is the personal account (PERSONAL_TG_LOGIN)."""
    # Check by user ID first
    if _personal_id is not None and event.sender_id == _personal_id:
        return True

    # Fallback: check by username
    if _personal_username:
        sender = await event.get_sender()
        if sender and getattr(sender, 'username', None):
            return sender.username.lower() == _personal_username

    return False


async def _has_access(event) -> bool:
    """Check if user has access to the bot (owner or personal account)."""
    return await _is_owner(event) or await _is_personal(event)


async def _can_authenticate(event) -> bool:
    """Check if user is allowed to authenticate via bot.

    If ALLOWED_USERNAME is set, only that user can authenticate.
    Otherwise, anyone can authenticate.
    """
    if not config.allowed_username:
        return True

    sender = await event.get_sender()
    if not sender or not getattr(sender, 'username', None):
        return False

    allowed = config.allowed_username.lower().lstrip('@')
    return sender.username.lower() == allowed


# =============================================================================
# Keyboard Layouts
# =============================================================================

def get_auth_keyboard():
    """Authentication keyboard."""
    return [
        [Button.inline("🔑 Авторизоваться", b"auth_start")],
    ]


def get_auth_cancel_keyboard():
    """Cancel authentication keyboard."""
    return [
        [Button.inline("❌ Отмена", b"auth_cancel")],
    ]


def get_main_menu_keyboard(is_personal: bool = False):
    """Main menu keyboard.

    Args:
        is_personal: If True, show limited menu for personal account
                    (features requiring user client are hidden)
    """
    if is_personal:
        # Limited menu for personal account - no user client features
        return [
            [Button.inline("🔔 Контекст призыва", b"mentions")],
            [Button.inline("💬 Приватные сообщения", b"private_messages")],
            [Button.inline("⚙️ Настройки", b"settings")],
        ]

    # Full menu for owner
    buttons = [
        [Button.inline("📅 Расписание статусов", b"schedule")],
        [Button.inline("📝 Автоответы", b"replies")],
        [Button.inline("🔔 Контекст призыва", b"mentions")],
        [Button.inline("💬 Приватные сообщения", b"private_messages")],
        [Button.inline("📊 Продуктивность", b"productivity")],
        [Button.inline("📆 Календарь", b"calendar")],
        [Button.inline("⚙️ Настройки", b"settings")],
    ]

    return buttons


def get_back_keyboard():
    """Back to main menu keyboard."""
    return [[Button.inline("« Назад", b"main")]]


def _get_priority_name(priority: int) -> str:
    """Get human-readable name for schedule priority."""
    names = {
        PRIORITY_REST: "отдых",
        PRIORITY_MORNING: "утро",
        PRIORITY_EVENING: "вечер",
        PRIORITY_WEEKENDS: "выходные",
        PRIORITY_WORK: "работа",
        PRIORITY_MEETING: "звонок",
        PRIORITY_OVERRIDE: "временное",
    }
    return names.get(priority, f"приоритет {priority}")


def _format_schedule_rule_text(s: Schedule) -> str:
    """Format schedule rule text (without emoji placeholder)."""
    parts = []

    # Time/date info
    if s.is_override():
        date_info = s.get_date_display()
        parts.append(date_info)
        if s.is_expired():
            parts.append("(истекло)")
    else:
        parts.append(f"{s.get_days_display()} {s.time_start}—{s.time_end}")
        # Priority/type name (only for regular rules, overrides are in separate section)
        type_name = _get_priority_name(s.priority)
        parts.append(f"• {type_name}")

    return " ".join(parts)


def _format_schedule_rule_fallback(s: Schedule) -> str:
    """Format schedule rule for fallback display (no custom emoji)."""
    emoji_short = s.emoji_id[-6:] if len(s.emoji_id) > 6 else s.emoji_id
    return f"`#{s.id}` […{emoji_short}] {_format_schedule_rule_text(s)}"


def get_schedule_keyboard():
    """Schedule management keyboard."""
    is_enabled = Schedule.is_scheduling_enabled()
    toggle_text = "🟢 Включен" if is_enabled else "🔴 Выключен"
    toggle_data = b"schedule_off" if is_enabled else b"schedule_on"

    buttons = [
        [Button.inline("📋 Список правил", b"schedule_list")],
    ]

    # Add work time edit button if work schedule exists
    work = Schedule.get_work_schedule()
    if work:
        buttons.append([Button.inline(f"✏️ Рабочее время ({work.time_start}—{work.time_end})", b"schedule_work_edit")])

        # Morning/evening emoji buttons
        morning = Schedule.get_morning_schedule()
        evening = Schedule.get_evening_schedule()
        morning_text = "🌅 Утро ✓" if morning else "🌅 Утро"
        evening_text = "🌙 Вечер ✓" if evening else "🌙 Вечер"
        buttons.append([
            Button.inline(morning_text, b"schedule_morning"),
            Button.inline(evening_text, b"schedule_evening"),
        ])

    # Weekend and rest emoji buttons
    weekend = Schedule.get_weekend_schedule()
    rest = Schedule.get_rest_schedule()
    weekend_text = "🎉 Выходные ✓" if weekend else "🎉 Выходные"
    rest_text = "💤 Остальное ✓" if rest else "💤 Остальное"
    buttons.append([
        Button.inline(weekend_text, b"schedule_weekend"),
        Button.inline(rest_text, b"schedule_rest"),
    ])

    # Add override button
    buttons.append([Button.inline("➕ Добавить временное", b"schedule_override_add")])

    buttons.extend([
        [Button.inline(toggle_text, toggle_data)],
        [Button.inline("🗑 Очистить всё", b"schedule_clear_confirm")],
        [Button.inline("« Назад", b"main")],
    ])

    return buttons


def get_schedule_list_keyboard():
    """Keyboard for schedule list view with delete buttons."""
    buttons = []

    # Delete buttons for overrides only
    overrides = [s for s in Schedule.get_all() if s.is_override()]
    if overrides:
        del_buttons = [Button.inline(f"🗑 #{s.id}", f"schedule_del_{s.id}".encode()) for s in overrides[:8]]
        for i in range(0, len(del_buttons), 4):
            buttons.append(del_buttons[i:i+4])

    buttons.append([Button.inline("« Назад", b"schedule")])
    return buttons


def get_meeting_keyboard():
    """Meeting control keyboard."""
    active = Schedule.get_active_meeting()

    if active:
        return [
            [Button.inline("🔴 Завершить звонок", b"meeting_end")],
            [Button.inline("« Назад", b"main")],
        ]
    else:
        return [
            [Button.inline("🟢 Начать звонок", b"meeting_start")],
            [Button.inline("« Назад", b"main")],
        ]


def get_settings_keyboard(is_personal: bool = False):
    """Settings keyboard.

    Args:
        is_personal: If True, show limited settings for personal account
    """
    if is_personal:
        # Personal account has no settings to configure
        return [
            [Button.inline("« Назад", b"main")],
        ]

    # Full settings for owner
    personal_chat_id = Settings.get_personal_chat_id()
    personal_text = "👤 Персональный чат ✓" if personal_chat_id else "👤 Персональный чат"

    return [
        [Button.inline(personal_text, b"pm_personal_chat")],
        [Button.inline("🚪 Выйти из аккаунта", b"logout_confirm")],
        [Button.inline("« Назад", b"main")],
    ]


def get_private_messages_keyboard():
    """Private messages settings keyboard."""
    is_asap_enabled = Settings.is_asap_enabled()
    asap_toggle_text = "🟢 ASAP включен" if is_asap_enabled else "🔴 ASAP выключен"
    asap_toggle_data = b"asap_off" if is_asap_enabled else b"asap_on"

    is_vip_as_asap = Settings.is_vip_as_asap_enabled()
    vip_toggle_text = "🟢 VIP как ASAP" if is_vip_as_asap else "🔴 VIP как ASAP"
    vip_toggle_data = b"vip_asap_off" if is_vip_as_asap else b"vip_asap_on"

    cooldown = Settings.get_asap_cooldown_minutes()
    cooldown_text = f"⏱ Кулдаун: {cooldown} мин"

    webhook_url = Settings.get_asap_webhook_url()
    webhook_text = "🔗 Webhook ✓" if webhook_url else "🔗 Webhook"

    return [
        [Button.inline(asap_toggle_text, asap_toggle_data)],
        [Button.inline(vip_toggle_text, vip_toggle_data)],
        [Button.inline(cooldown_text, b"asap_cooldown")],
        [Button.inline(webhook_text, b"pm_webhook")],
        [Button.inline("« Назад", b"main")],
    ]


def get_calendar_keyboard():
    """Calendar sync management keyboard."""
    is_configured = Settings.is_caldav_configured()
    is_enabled = Settings.is_calendar_sync_enabled()

    buttons = []

    if is_configured:
        toggle_text = "🟢 Синхронизация вкл" if is_enabled else "🔴 Синхронизация выкл"
        toggle_data = b"calendar_off" if is_enabled else b"calendar_on"
        buttons.append([Button.inline(toggle_text, toggle_data)])
        buttons.append([Button.inline("🔗 Проверить подключение", b"calendar_test")])
        buttons.append([Button.inline("🎨 Настроить emoji", b"calendar_emoji_setup")])

    buttons.append([Button.inline("⚙️ Настроить CalDAV", b"calendar_setup")])
    buttons.append([Button.inline("« Назад", b"main")])

    return buttons


def get_mentions_keyboard():
    """Mentions configuration main menu."""
    return [
        [Button.inline("📴 Во время отсутствия", b"mention_offline")],
        [Button.inline("📱 Во время онлайн", b"mention_online")],
        [Button.inline("⭐ Приоритетные", b"mention_vip")],
        [Button.inline("« Назад", b"main")],
    ]


def get_productivity_keyboard():
    """Productivity summary configuration keyboard."""
    is_enabled = Settings.is_productivity_summary_enabled()
    toggle_text = "🟢 Автоотправка включена" if is_enabled else "🔴 Автоотправка выключена"
    toggle_data = b"productivity_off" if is_enabled else b"productivity_on"

    summary_time = Settings.get_productivity_summary_time()
    time_text = f"⏰ Время: {summary_time}" if summary_time else "⏰ Время не настроено"

    extra_count = len(Settings.get_productivity_extra_chats())
    extra_text = f"➕ Доп. чаты ({extra_count})" if extra_count > 0 else "➕ Добавить чаты"

    return [
        [Button.inline("📊 Получить сводку сейчас", b"productivity_now")],
        [Button.inline(toggle_text, toggle_data)],
        [Button.inline(time_text, b"productivity_time")],
        [Button.inline(extra_text, b"productivity_chats")],
        [Button.inline("« Назад", b"main")],
    ]


def get_mention_offline_keyboard():
    """Offline mention settings keyboard."""
    is_enabled = Settings.is_offline_mention_enabled()
    toggle_text = "🟢 Включен" if is_enabled else "🔴 Выключен"
    toggle_data = b"offline_mention_off" if is_enabled else b"offline_mention_on"

    return [
        [Button.inline(toggle_text, toggle_data)],
        [Button.inline("« Назад", b"mentions")],
    ]


def get_mention_online_keyboard():
    """Online mention settings keyboard."""
    is_enabled = Settings.is_online_mention_enabled()
    delay = Settings.get_online_mention_delay()
    toggle_text = "🟢 Включен" if is_enabled else "🔴 Выключен"
    toggle_data = b"online_mention_off" if is_enabled else b"online_mention_on"

    if delay > 0:
        delay_text = f"⏱ Задержка: {delay} мин"
    else:
        delay_text = "⏱ Задержка: без задержки"

    return [
        [Button.inline(toggle_text, toggle_data)],
        [Button.inline(delay_text, b"online_delay_edit")],
        [Button.inline("« Назад", b"mentions")],
    ]


def get_vip_keyboard():
    """VIP management main keyboard."""
    return [
        [Button.inline("👤 Пользователи", b"vip_users")],
        [Button.inline("💬 Чаты", b"vip_chats")],
        [Button.inline("« Назад", b"mentions")],
    ]


def get_vip_users_keyboard():
    """VIP users list with add/delete buttons."""
    users = VipList().select(SQL().WHERE('item_type', '=', 'user')) or []

    buttons = []
    for u in users[:10]:
        display = u.display_name if u.display_name else f"@{u.item_id}"
        buttons.append([
            Button.inline(f"👤 {display}", f"vip_user_view:{u.id}".encode()),
            Button.inline("🗑", f"vip_del:{u.id}".encode())
        ])

    buttons.append([Button.inline("➕ Добавить", b"vip_add_user")])
    buttons.append([Button.inline("« Назад", b"mention_vip")])
    return buttons


def get_vip_chats_keyboard():
    """VIP chats list with add/delete buttons."""
    chats = VipList().select(SQL().WHERE('item_type', '=', 'chat')) or []

    buttons = []
    for c in chats[:10]:
        display = c.display_name if c.display_name else f"ID: {c.item_id}"
        buttons.append([
            Button.inline(f"💬 {display}", f"vip_chat_view:{c.id}".encode()),
            Button.inline("🗑", f"vip_del:{c.id}".encode())
        ])

    buttons.append([Button.inline("➕ Добавить", b"vip_add_chat")])
    buttons.append([Button.inline("« Назад", b"mention_vip")])
    return buttons


def get_confirm_keyboard(action: str):
    """Confirmation keyboard."""
    return [
        [Button.inline("✅ Да", f"confirm_{action}".encode()),
         Button.inline("❌ Нет", b"main")],
    ]


def get_replies_keyboard():
    """Replies management keyboard."""
    is_enabled = Settings.is_autoreply_enabled()
    toggle_text = "🟢 Включен" if is_enabled else "🔴 Выключен"
    toggle_data = b"autoreply_toggle_off" if is_enabled else b"autoreply_toggle_on"

    return [
        [Button.inline("📋 Список автоответов", b"replies_list")],
        [Button.inline("⭐ Дефолтный ответ", b"reply_default")],
        [Button.inline("➕ Добавить", b"reply_add")],
        [Button.inline(toggle_text, toggle_data)],
        [Button.inline("« Назад", b"main")],
    ]


def get_reply_view_keyboard(emoji_id: str):
    """Keyboard for viewing a specific reply."""
    return [
        [Button.inline("💾 Сохранить", f"reply_save:{emoji_id}".encode())],
        [Button.inline("🗑 Удалить", f"reply_del_confirm:{emoji_id}".encode())],
        [Button.inline("« Назад", b"replies_list")],
    ]


def get_reply_delete_confirm_keyboard(emoji_id: str):
    """Keyboard for confirming reply delete."""
    return [
        [Button.inline("✅ Да, удалить", f"reply_del:{emoji_id}".encode()),
         Button.inline("❌ Нет", f"reply_view:{emoji_id}".encode())],
    ]


# =============================================================================
# Handler Registration
# =============================================================================

def register_bot_handlers(bot, user_client=None):
    """
    Register all bot event handlers.

    Args:
        bot: Telethon bot client instance
        user_client: Telethon user client for sending custom emojis
    """
    global _user_client
    _user_client = user_client

    async def _delete_emoji_list_message():
        """Delete the emoji list message from user client."""
        global _emoji_list_message_id
        if _user_client and _bot_username and _emoji_list_message_id:
            try:
                await _user_client.delete_messages(_bot_username, _emoji_list_message_id)
            except Exception as e:
                logger.warning(f"Failed to delete emoji list message: {e}")
            _emoji_list_message_id = None

    async def _delete_schedule_list_message():
        """Delete the schedule list message from user client."""
        global _schedule_list_message_id
        if _user_client and _bot_username and _schedule_list_message_id:
            try:
                await _user_client.delete_messages(_bot_username, _schedule_list_message_id)
            except Exception as e:
                logger.warning(f"Failed to delete schedule list message: {e}")
            _schedule_list_message_id = None

    async def _clear_bot_chat_history():
        """Delete all messages in chat with bot to remove sensitive auth data."""
        if not _user_client or not _bot_username:
            return
        try:
            bot_entity = await _user_client.get_input_entity(_bot_username)
            await _user_client(DeleteHistoryRequest(
                peer=bot_entity,
                max_id=0,  # Delete all messages
                revoke=True  # Delete for both sides
            ))
            logger.info("Cleared bot chat history after auth")
        except Exception as e:
            logger.warning(f"Failed to clear bot chat history: {e}")

    async def _is_user_client_authorized() -> bool:
        """Check if user client is authorized."""
        if not _user_client:
            return False
        try:
            return await _user_client.is_user_authorized()
        except Exception:
            return False

    @bot.on(events.NewMessage(pattern=r"^/start"))
    async def start_handler(event):
        """Handle /start command - show main menu or auth flow."""
        # Check if user client is authorized
        is_authorized = await _is_user_client_authorized()

        if not is_authorized:
            # User client not authorized - show auth flow
            if not await _can_authenticate(event):
                await event.respond(
                    "⛔ **Доступ запрещён**\n\n"
                    "Авторизация разрешена только для определённого пользователя."
                )
                return

            await event.respond(
                "🔐 **Требуется авторизация**\n\n"
                "Для работы бота необходимо авторизовать Telegram-клиент.\n\n"
                "Нажмите кнопку ниже, чтобы начать процесс авторизации.",
                buttons=get_auth_keyboard()
            )
            return

        # User client authorized - check if owner
        if not await _has_access(event):
            return

        is_personal = await _is_personal(event)
        await event.respond(
            "🤖 **Ваш ассистент**\n\n"
            "Выберите раздел:",
            buttons=get_main_menu_keyboard(is_personal=is_personal)
        )

    @bot.on(events.CallbackQuery(data=b"main"))
    async def main_menu(event):
        """Return to main menu."""
        if not await _has_access(event):
            return

        # Delete user client messages when returning to main menu (only for owner)
        is_personal = await _is_personal(event)
        if not is_personal:
            await _delete_emoji_list_message()
            await _delete_schedule_list_message()

        await event.edit(
            "🤖 **Ваш ассистент**\n\n"
            "Выберите раздел:",
            buttons=get_main_menu_keyboard(is_personal=is_personal)
        )

    # =========================================================================
    # Authentication Flow
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"auth_start"))
    async def auth_start(event):
        """Start authentication flow - ask for phone number."""
        if not await _can_authenticate(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        # Initialize auth state
        _auth_state[event.sender_id] = {'step': 'phone'}

        # Edit current message
        await event.edit(
            "📱 **Авторизация - Шаг 1/3**\n\n"
            "Нажмите кнопку ниже, чтобы отправить номер телефона,\n"
            "или введите его вручную в формате: `+79001234567`"
        )

        # Send new message with phone request button (ReplyKeyboard)
        await event.respond(
            "👇 Нажмите кнопку для отправки номера:",
            buttons=[[Button.request_phone("📲 Отправить номер телефона")]]
        )

    @bot.on(events.CallbackQuery(data=b"auth_cancel"))
    async def auth_cancel(event):
        """Cancel authentication flow."""
        # Clear auth state
        if event.sender_id in _auth_state:
            del _auth_state[event.sender_id]

        await event.edit(
            "❌ **Авторизация отменена**\n\n"
            "Нажмите /start чтобы начать заново.",
            buttons=get_auth_keyboard()
        )

    @bot.on(events.CallbackQuery(data=b"auth_resend"))
    async def auth_resend(event):
        """Resend verification code."""
        if not await _can_authenticate(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        state = _auth_state.get(event.sender_id)
        if not state or 'phone' not in state:
            await event.answer("❌ Сначала введите номер телефона", alert=True)
            return

        try:
            result = await _user_client.send_code_request(state['phone'])
            state['phone_code_hash'] = result.phone_code_hash
            state['step'] = 'code'

            await event.answer("✅ Код отправлен повторно")
            await event.edit(
                "🔢 **Авторизация - Шаг 2/3**\n\n"
                f"Код отправлен на номер `{state['phone']}`\n\n"
                "Введите код через дефисы: `1-2-3-4-5-6`",
                buttons=[
                    [Button.inline("🔄 Отправить ещё раз", b"auth_resend")],
                    [Button.inline("❌ Отмена", b"auth_cancel")],
                ]
            )
        except Exception as e:
            logger.error(f"Failed to resend code: {e}")
            # Show short message in popup, full error in chat
            await event.answer("❌ Не удалось отправить код", alert=True)
            await event.edit(
                f"❌ **Ошибка отправки кода**\n\n"
                f"{str(e)[:200]}\n\n"
                "Подождите несколько минут и попробуйте снова.",
                buttons=[
                    [Button.inline("🔄 Попробовать снова", b"auth_resend")],
                    [Button.inline("❌ Отмена", b"auth_cancel")],
                ]
            )

    # =========================================================================
    # Status
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"status"))
    async def status_handler(event):
        """Show current status."""
        if not await _has_access(event):
            return

        # Get schedule status
        is_enabled = Schedule.is_scheduling_enabled()
        schedules_count = len(Schedule.get_all())
        current_emoji_id = Schedule.get_current_emoji_id()

        # Get replies count
        replies = Reply().select(SQL())
        replies_count = len(replies) if replies else 0

        # Get meeting status
        active_meeting = Schedule.get_active_meeting()

        status_emoji = "✅" if is_enabled else "❌"
        meeting_status = "🔴 Активен" if active_meeting else "⚪ Нет"

        text = (
            "📊 **Текущий статус**\n\n"
            f"**Расписание:** {status_emoji} {'включено' if is_enabled else 'выключено'}\n"
            f"**Правил расписания:** {schedules_count}\n"
            f"**Автоответов настроено:** {replies_count}\n"
            f"**Звонок:** {meeting_status}\n"
        )

        if current_emoji_id:
            text += f"\n**Текущий emoji по расписанию:**\n`{current_emoji_id}`"

        await event.edit(text, buttons=get_back_keyboard())

    # =========================================================================
    # Replies
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"replies"))
    async def replies_menu(event):
        """Show replies menu."""
        if not await _has_access(event):
            return

        # Personal account doesn't have access to replies (requires user client)
        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        # Clear add mode when returning to menu
        _pending_reply_add_mode.discard(event.sender_id)
        _pending_default_reply_setup.discard(event.sender_id)

        # Clean up user client messages when switching sections
        await _delete_emoji_list_message()
        await _delete_schedule_list_message()

        text = (
            "📝 **Автоответы**\n\n"
            "Для настройки автоответа отправьте боту:\n"
            "1. Сообщение с эмодзи-статусом\n"
            "2. Затем текст автоответа\n\n"
            "⭐ **Дефолтный ответ** — единый шаблон,\n"
            "который отправляется, когда эмодзи-статус не установлен.\n\n"
            "Или используйте список для просмотра."
        )

        await event.edit(text, buttons=get_replies_keyboard())

    @bot.on(events.CallbackQuery(data=b"replies_list"))
    async def replies_list(event):
        """List all configured replies as buttons."""
        if not await _has_access(event):
            return

        replies = [r for r in Reply().select(SQL()) if r.emoji != DEFAULT_REPLY_EMOJI]

        if not replies:
            await event.edit(
                "📝 **Автоответы**\n\n"
                "Нет настроенных автоответов.",
                buttons=get_replies_keyboard()
            )
            return

        buttons = []
        for i, r in enumerate(replies[:8], 1):
            buttons.append([Button.inline(f"{i}", f"reply_view:{r.emoji}".encode())])

        if len(replies) > 8:
            buttons.append([Button.inline(f"... ещё {len(replies) - 8}", b"replies_list")])

        buttons.append([Button.inline("« Назад", b"replies")])

        # Try to send/edit custom emojis via user client
        if _user_client and _bot_username:
            try:
                # Get emoji documents to find alt text
                emoji_ids = [int(r.emoji) for r in replies[:8]]
                docs = await _user_client(GetCustomEmojiDocumentsRequest(document_id=emoji_ids))

                # Map document_id -> alt emoji
                alt_map = {}
                for doc in docs:
                    for attr in doc.attributes:
                        if isinstance(attr, DocumentAttributeCustomEmoji):
                            alt_map[doc.id] = attr.alt
                            break

                # Build text with custom emojis
                text = "📝 Выберите автоответ:"
                entities = []

                for i, r in enumerate(replies[:8], 1):
                    emoji_id = int(r.emoji)
                    prefix = f"\n\n{i}. "
                    alt_emoji = alt_map.get(emoji_id, "⭐")

                    # Use UTF-16 length for Telegram offsets
                    emoji_offset = _utf16_len(text) + _utf16_len(prefix)
                    text += prefix + alt_emoji

                    entities.append(MessageEntityCustomEmoji(
                        offset=emoji_offset,
                        length=_utf16_len(alt_emoji),
                        document_id=emoji_id
                    ))

                global _emoji_list_message_id

                # Edit existing message or send new one
                if _emoji_list_message_id:
                    await _user_client.edit_message(
                        _bot_username,
                        _emoji_list_message_id,
                        text,
                        formatting_entities=entities
                    )
                else:
                    msg = await _user_client.send_message(
                        _bot_username,
                        text,
                        formatting_entities=entities
                    )
                    _emoji_list_message_id = msg.id

                # Bot edits its message to show only buttons
                await event.edit("Выберите номер:", buttons=buttons)
                return
            except Exception as e:
                logger.warning(f"Failed to send via user client: {e}")

        # Fallback: bot sends without custom emojis
        lines = ["📝 **Выберите автоответ:**\n"]
        for i, r in enumerate(replies[:8], 1):
            lines.append(f"{i}. ID: `{r.emoji}`")
        await event.edit("\n".join(lines), buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=b"reply_view:(.+)"))
    async def reply_view(event):
        """View a specific reply - show actual reply text via user client."""
        if not await _has_access(event):
            return

        emoji_id = event.pattern_match.group(1).decode()
        reply = Reply.get_by_emoji(emoji_id)

        if not reply:
            await event.answer("❌ Автоответ не найден", alert=True)
            return

        # Get stored message
        msg = reply.message

        # Show actual reply content via user client
        global _emoji_list_message_id
        if _user_client and _bot_username and _emoji_list_message_id and msg:
            try:
                # Send the actual reply text with its entities
                reply_text = msg.text or msg.message or "(пустое сообщение)"
                reply_entities = msg.entities or []

                await _user_client.edit_message(
                    _bot_username,
                    _emoji_list_message_id,
                    reply_text,
                    formatting_entities=reply_entities
                )
            except Exception as e:
                logger.warning(f"Failed to edit user client message: {e}")

        await event.edit(
            f"📝 **Автоответ для emoji** `{emoji_id}`\n\n"
            "⬆️ Отредактируйте сообщение выше и нажмите «Сохранить»",
            buttons=get_reply_view_keyboard(emoji_id)
        )

    @bot.on(events.CallbackQuery(pattern=b"reply_save:(.+)"))
    async def reply_save(event):
        """Save the edited reply from user client message."""
        if not await _has_access(event):
            return

        emoji_id = event.pattern_match.group(1).decode()

        # Fetch the user client message to get edited content
        if not _user_client or not _bot_username or not _emoji_list_message_id:
            await event.answer("❌ Ошибка: сообщение не найдено", alert=True)
            return

        try:
            # Get the message from the chat
            messages = await _user_client.get_messages(_bot_username, ids=_emoji_list_message_id)
            if not messages:
                await event.answer("❌ Сообщение не найдено", alert=True)
                return

            edited_msg = messages

            # Save the reply
            Reply.create(emoji_id, edited_msg)
            logger.info(f"Reply saved for emoji {emoji_id} via bot")

            await event.answer("✅ Автоответ сохранён!")

            # Stay on the same screen
            await event.edit(
                f"📝 **Автоответ для emoji** `{emoji_id}`\n\n"
                "✅ Сохранено!\n\n"
                "⬆️ Отредактируйте сообщение выше и нажмите «Сохранить»",
                buttons=get_reply_view_keyboard(emoji_id)
            )
        except Exception as e:
            logger.error(f"Failed to save reply: {e}")
            await event.answer(f"❌ Ошибка сохранения: {e}", alert=True)

    @bot.on(events.CallbackQuery(pattern=b"reply_del_confirm:(.+)"))
    async def reply_delete_confirm(event):
        """Ask for delete confirmation."""
        if not await _has_access(event):
            return

        emoji_id = event.pattern_match.group(1).decode()

        await event.edit(
            f"⚠️ **Удалить автоответ?**\n\n"
            f"**Emoji ID:** `{emoji_id}`\n\n"
            f"Это действие нельзя отменить.",
            buttons=get_reply_delete_confirm_keyboard(emoji_id)
        )

    @bot.on(events.CallbackQuery(pattern=b"reply_del:(.+)"))
    async def reply_delete(event):
        """Delete a reply."""
        if not await _has_access(event):
            return

        emoji_id = event.pattern_match.group(1).decode()
        reply = Reply.get_by_emoji(emoji_id)

        if reply:
            reply.delete()
            logger.info(f"Reply deleted for emoji {emoji_id} via bot")
            await event.answer("✅ Автоответ удалён")
        else:
            await event.answer("❌ Автоответ не найден", alert=True)

        # Return to list
        await replies_list(event)

    # =========================================================================
    # Schedule
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"schedule"))
    async def schedule_menu(event):
        """Show schedule menu."""
        if not await _has_access(event):
            return

        # Personal account doesn't have access to schedule (requires user client)
        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        # Clean up messages from other sections or list view
        await _delete_emoji_list_message()
        await _delete_schedule_list_message()

        text = (
            "📅 **Расписание эмодзи-статуса**\n\n"
            "Управление расписанием:"
        )

        await event.edit(text, buttons=get_schedule_keyboard())

    @bot.on(events.CallbackQuery(data=b"schedule_list"))
    async def schedule_list_handler(event):
        """List all schedule rules with custom emoji display."""
        if not await _has_access(event):
            return

        schedules = Schedule.get_all()

        if not schedules:
            await event.edit(
                "📅 **Расписание**\n\n"
                "Нет правил. Настройте через команды в настроечном чате.",
                buttons=get_schedule_keyboard()
            )
            return

        # Group by override vs regular, then sort by priority desc
        overrides = sorted([s for s in schedules if s.is_override()], key=lambda x: -x.priority)
        regular = sorted([s for s in schedules if not s.is_override()], key=lambda x: -x.priority)
        all_rules = overrides + regular

        # Try to display with custom emojis via user client
        if _user_client and _bot_username:
            try:
                # Get unique emoji IDs
                emoji_ids = list(set(int(s.emoji_id) for s in all_rules))
                docs = await _user_client(GetCustomEmojiDocumentsRequest(document_id=emoji_ids))

                # Map document_id -> alt emoji
                alt_map = {}
                for doc in docs:
                    for attr in doc.attributes:
                        if isinstance(attr, DocumentAttributeCustomEmoji):
                            alt_map[doc.id] = attr.alt
                            break

                # Build text with custom emojis
                text = "📅 Правила расписания\n"
                entities = []

                def add_section(title: str, rules: list):
                    nonlocal text
                    if not rules:
                        return
                    text += f"\n{title}"
                    for s in rules:
                        emoji_id = int(s.emoji_id)
                        alt_emoji = alt_map.get(emoji_id, "⭐")

                        # Format: "⭐ #1 ПН-ПТ 12:00—20:00 • работа"
                        line_start = f"\n"
                        emoji_offset = _utf16_len(text) + _utf16_len(line_start)
                        rule_text = f" #{s.id}  {_format_schedule_rule_text(s)}"

                        text += line_start + alt_emoji + rule_text

                        entities.append(MessageEntityCustomEmoji(
                            offset=emoji_offset,
                            length=_utf16_len(alt_emoji),
                            document_id=emoji_id
                        ))

                add_section("📆 Временные:", overrides)
                if overrides and regular:
                    text += "\n"  # Spacing between sections
                add_section("🔄 Постоянные:", regular)

                # Footer
                text += "\n\n────────────────────"
                text += "\n💡 Удаление через кнопки 🗑"

                global _schedule_list_message_id

                # Edit existing message or send new one
                if _schedule_list_message_id:
                    try:
                        await _user_client.edit_message(
                            _bot_username,
                            _schedule_list_message_id,
                            text,
                            formatting_entities=entities
                        )
                    except Exception:
                        # Message might be deleted, send new one
                        msg = await _user_client.send_message(
                            _bot_username,
                            text,
                            formatting_entities=entities
                        )
                        _schedule_list_message_id = msg.id
                else:
                    msg = await _user_client.send_message(
                        _bot_username,
                        text,
                        formatting_entities=entities
                    )
                    _schedule_list_message_id = msg.id

                # Bot shows only keyboard with delete buttons
                await event.edit("⬆️ Список правил выше", buttons=get_schedule_list_keyboard())
                return
            except Exception as e:
                logger.warning(f"Failed to send schedule via user client: {e}")

        # Fallback: bot sends without custom emojis
        lines = ["📅 **Правила расписания**\n"]

        if overrides:
            lines.append("**📆 Временные:**")
            for s in overrides:
                lines.append(_format_schedule_rule_fallback(s))
            lines.append("")

        if regular:
            lines.append("**🔄 Постоянные:**")
            for s in regular:
                lines.append(_format_schedule_rule_fallback(s))
            lines.append("")

        lines.append("─" * 20)
        lines.append("💡 Удаление через кнопки 🗑")

        await event.edit('\n'.join(lines), buttons=get_schedule_list_keyboard())

    @bot.on(events.CallbackQuery(data=b"schedule_on"))
    async def schedule_enable(event):
        """Enable scheduling."""
        if not await _has_access(event):
            return

        Schedule.set_scheduling_enabled(True)
        logger.info("Scheduling enabled via bot")
        await event.answer("✅ Расписание включено")

        # Refresh menu
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_off"))
    async def schedule_disable(event):
        """Disable scheduling."""
        if not await _has_access(event):
            return

        Schedule.set_scheduling_enabled(False)
        logger.info("Scheduling disabled via bot")
        await event.answer("❌ Расписание выключено")

        # Refresh menu
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_clear_confirm"))
    async def schedule_clear_confirm(event):
        """Confirm schedule clear."""
        if not await _has_access(event):
            return

        await event.edit(
            "⚠️ **Удалить все правила расписания?**\n\n"
            "Это действие нельзя отменить.",
            buttons=get_confirm_keyboard("schedule_clear")
        )

    @bot.on(events.CallbackQuery(data=b"confirm_schedule_clear"))
    async def schedule_clear(event):
        """Clear all schedule rules."""
        if not await _has_access(event):
            return

        Schedule.delete_all()
        Schedule.set_scheduling_enabled(False)
        logger.info("All schedules cleared via bot")

        await event.answer("✅ Все правила удалены")
        await event.edit(
            "📅 **Расписание**\n\n"
            "Все правила удалены.",
            buttons=get_schedule_keyboard()
        )

    @bot.on(events.CallbackQuery(pattern=rb"schedule_del_(\d+)"))
    async def schedule_delete_rule(event):
        """Delete a specific schedule rule by ID."""
        if not await _has_access(event):
            return

        match = event.pattern_match
        rule_id = int(match.group(1))

        if not Schedule.delete_by_id(rule_id):
            await event.answer("❌ Правило не найдено", alert=True)
            return

        logger.info(f"Schedule rule #{rule_id} deleted via bot")

        await event.answer(f"✅ Правило #{rule_id} удалено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_work_edit"))
    async def schedule_work_edit_start(event):
        """Start editing work schedule time."""
        if not await _has_access(event):
            return

        work = Schedule.get_work_schedule()
        if not work:
            await event.answer("❌ Рабочее расписание не найдено", alert=True)
            return

        _pending_work_time_edit.add(event.sender_id)

        await event.edit(
            f"✏️ **Настройка рабочего времени**\n\n"
            f"Текущее время: **{work.time_start}—{work.time_end}**\n"
            f"Текущий эмодзи: `{work.emoji_id}`\n\n"
            f"Отправьте:\n"
            f"• Время в формате `09:00-18:00`\n"
            f"• Или эмодзи для изменения статуса",
            buttons=[[Button.inline("❌ Отмена", b"schedule_work_edit_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"schedule_work_edit_cancel"))
    async def schedule_work_edit_cancel(event):
        """Cancel work schedule time editing."""
        if not await _has_access(event):
            return

        _pending_work_time_edit.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_morning"))
    async def schedule_morning_start(event):
        """Start setting morning emoji."""
        if not await _has_access(event):
            return

        work = Schedule.get_work_schedule()
        if not work:
            await event.answer("❌ Сначала настройте рабочее время", alert=True)
            return

        morning = Schedule.get_morning_schedule()
        current_info = f"\n\nТекущий эмодзи: `{morning.emoji_id}`" if morning else ""

        _pending_morning_emoji.add(event.sender_id)

        await event.edit(
            f"🌅 **Эмодзи для утра**\n\n"
            f"Время: **00:00—{work.time_start}** (ПН-ПТ){current_info}\n\n"
            f"Отправьте эмодзи для утреннего статуса:",
            buttons=[[Button.inline("❌ Отмена", b"schedule_morning_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"schedule_morning_cancel"))
    async def schedule_morning_cancel(event):
        """Cancel morning emoji setup."""
        if not await _has_access(event):
            return

        _pending_morning_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_evening"))
    async def schedule_evening_start(event):
        """Start setting evening emoji."""
        if not await _has_access(event):
            return

        work = Schedule.get_work_schedule()
        if not work:
            await event.answer("❌ Сначала настройте рабочее время", alert=True)
            return

        evening = Schedule.get_evening_schedule()
        current_info = f"\n\nТекущий эмодзи: `{evening.emoji_id}`" if evening else ""

        _pending_evening_emoji.add(event.sender_id)

        await event.edit(
            f"🌙 **Эмодзи для вечера**\n\n"
            f"Время: **{work.time_end}—23:59** (ПН-ПТ){current_info}\n\n"
            f"Отправьте эмодзи для вечернего статуса:",
            buttons=[[Button.inline("❌ Отмена", b"schedule_evening_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"schedule_evening_cancel"))
    async def schedule_evening_cancel(event):
        """Cancel evening emoji setup."""
        if not await _has_access(event):
            return

        _pending_evening_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_weekend"))
    async def schedule_weekend_start(event):
        """Start setting weekend emoji."""
        if not await _has_access(event):
            return

        weekend = Schedule.get_weekend_schedule()
        current_info = f"\n\nТекущий эмодзи: `{weekend.emoji_id}`" if weekend else ""

        _pending_weekend_emoji.add(event.sender_id)

        await event.edit(
            f"🎉 **Эмодзи для выходных**\n\n"
            f"ПТ вечер + СБ-ВС весь день{current_info}\n\n"
            f"Отправьте эмодзи для выходных:",
            buttons=[[Button.inline("❌ Отмена", b"schedule_weekend_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"schedule_weekend_cancel"))
    async def schedule_weekend_cancel(event):
        """Cancel weekend emoji setup."""
        if not await _has_access(event):
            return

        _pending_weekend_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_rest"))
    async def schedule_rest_start(event):
        """Start setting rest/fallback emoji."""
        if not await _has_access(event):
            return

        rest = Schedule.get_rest_schedule()
        current_info = f"\n\nТекущий эмодзи: `{rest.emoji_id}`" if rest else ""

        _pending_rest_emoji.add(event.sender_id)

        await event.edit(
            f"💤 **Эмодзи по умолчанию**\n\n"
            f"Используется когда нет других правил{current_info}\n\n"
            f"Отправьте эмодзи:",
            buttons=[[Button.inline("❌ Отмена", b"schedule_rest_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"schedule_rest_cancel"))
    async def schedule_rest_cancel(event):
        """Cancel rest emoji setup."""
        if not await _has_access(event):
            return

        _pending_rest_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_override_add"))
    async def schedule_override_add_start(event):
        """Start adding an override schedule."""
        if not await _has_access(event):
            return

        _pending_override_dates.add(event.sender_id)

        await event.edit(
            "➕ **Добавить временное правило**\n\n"
            "Используется для отпуска, больничного и т.д.\n\n"
            "Форматы:\n"
            "• `06.01-07.01` — весь день\n"
            "• `06.01 9:30-11:30` — время в один день\n"
            "• `06.01 12:00 - 07.01 15:00` — диапазон",
            buttons=[[Button.inline("❌ Отмена", b"schedule_override_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"schedule_override_cancel"))
    async def schedule_override_cancel(event):
        """Cancel override creation."""
        if not await _has_access(event):
            return

        _pending_override_dates.discard(event.sender_id)
        if event.sender_id in _pending_override_emoji:
            del _pending_override_emoji[event.sender_id]
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    # =========================================================================
    # Meeting
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"meeting"))
    async def meeting_menu(event):
        """Show meeting menu."""
        if not await _has_access(event):
            return

        active = Schedule.get_active_meeting()
        meeting_emoji_id = Settings.get('meeting_emoji_id')

        if active:
            text = (
                "📞 **Управление звонками**\n\n"
                f"🔴 **Звонок активен**\n"
                f"Emoji: `{active.emoji_id}`"
            )
        else:
            text = "📞 **Управление звонками**\n\n⚪ Нет активного звонка"
            if meeting_emoji_id:
                text += f"\n\nНастроенный emoji: `{meeting_emoji_id}`"

        await event.edit(text, buttons=get_meeting_keyboard())

    @bot.on(events.CallbackQuery(data=b"meeting_start"))
    async def meeting_start(event):
        """Start a meeting."""
        if not await _has_access(event):
            return

        meeting_emoji_id = Settings.get('meeting_emoji_id')

        if not meeting_emoji_id:
            await event.answer("❌ Не настроен emoji для звонков", alert=True)
            return

        Schedule.start_meeting(int(meeting_emoji_id))
        logger.info(f"Meeting started via bot with emoji {meeting_emoji_id}")

        await event.answer("🟢 Звонок начат")
        await meeting_menu(event)

    @bot.on(events.CallbackQuery(data=b"meeting_end"))
    async def meeting_end(event):
        """End a meeting."""
        if not await _has_access(event):
            return

        Schedule.end_meeting()
        logger.info("Meeting ended via bot")

        await event.answer("🔴 Звонок завершён")
        await meeting_menu(event)

    # =========================================================================
    # Calendar
    # =========================================================================

    # Pending CalDAV setup states
    _pending_caldav_url: set[int] = set()
    _pending_caldav_username: set[int] = set()
    _pending_caldav_password: set[int] = set()

    @bot.on(events.CallbackQuery(data=b"calendar"))
    async def calendar_menu(event):
        """Show calendar sync menu."""
        if not await _has_access(event):
            return

        # Personal account doesn't have access to calendar (requires user client)
        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        is_configured = Settings.is_caldav_configured()
        is_enabled = Settings.is_calendar_sync_enabled()
        meeting_emoji = Settings.get('meeting_emoji_id')
        absence_emoji = Settings.get_absence_emoji_id()

        if is_configured:
            url = Settings.get_caldav_url() or ""
            # Hide URL details for privacy
            url_display = url.split("//")[-1].split("/")[0] if url else "не указан"

            # Get calendar type counts
            meeting_cals = Settings.get_caldav_meeting_calendars()
            absence_cals = Settings.get_caldav_absence_calendars()

            status_icon = "🟢" if is_enabled else "🔴"
            meeting_emoji_status = f"`{meeting_emoji}`" if meeting_emoji else "❌"
            absence_emoji_status = f"`{absence_emoji}`" if absence_emoji else "❌"

            # Get calendar status with events
            cal_status = await caldav_service.get_calendar_status()

            text = (
                f"📆 **Календарь** {status_icon}\n\n"
                f"**Сервер:** {url_display}\n"
                f"**Календари:** 📅 {len(meeting_cals)} встреч, 🏖 {len(absence_cals)} отсутств.\n"
                f"**Emoji:** 📅 {meeting_emoji_status} | 🏖 {absence_emoji_status}\n"
            )

            # Show current event with type
            current = cal_status.get('current_event')
            if current:
                from services.caldav_service import CalendarEventType
                type_icon = "🏖" if current.event_type == CalendarEventType.ABSENCE else "📅"
                text += f"\n{type_icon} **Сейчас:** {current.summary}\n"
                text += f"   до {current.end.strftime('%H:%M')} ({current.calendar_name})\n"

            # Show upcoming events
            upcoming = cal_status.get('upcoming_events', [])
            if upcoming:
                text += "\n📋 **Ближайшие:**\n"
                for evt in upcoming[:3]:
                    time_str = evt.start.strftime('%H:%M')
                    text += f"• {time_str} — {evt.summary[:30]}\n"
            elif not current:
                text += "\n✅ Нет ближайших событий\n"

        else:
            text = (
                "📆 **Синхронизация с календарём**\n\n"
                "⚠️ CalDAV не настроен\n\n"
                "Настройте подключение к календарю для "
                "автоматического изменения статуса во время встреч и отсутствий."
            )

        await event.edit(text, buttons=get_calendar_keyboard())

    @bot.on(events.CallbackQuery(data=b"calendar_on"))
    async def calendar_enable(event):
        """Enable calendar sync."""
        if not await _has_access(event):
            return

        if not Settings.is_caldav_configured():
            await event.answer("❌ Сначала настройте CalDAV", alert=True)
            return

        Settings.set_calendar_sync_enabled(True)
        logger.info("Calendar sync enabled via bot")

        await event.answer("🟢 Синхронизация включена")
        await calendar_menu(event)

    @bot.on(events.CallbackQuery(data=b"calendar_off"))
    async def calendar_disable(event):
        """Disable calendar sync."""
        if not await _has_access(event):
            return

        Settings.set_calendar_sync_enabled(False)
        caldav_service.clear_state()
        logger.info("Calendar sync disabled via bot")

        await event.answer("🔴 Синхронизация выключена")
        await calendar_menu(event)

    # Pending emoji setup states
    _pending_meeting_emoji: set[int] = set()
    _pending_absence_emoji: set[int] = set()

    @bot.on(events.CallbackQuery(data=b"calendar_emoji_setup"))
    async def calendar_emoji_setup(event):
        """Show emoji setup menu for calendar events."""
        if not await _has_access(event):
            return

        meeting_emoji = Settings.get('meeting_emoji_id')
        absence_emoji = Settings.get_absence_emoji_id()

        meeting_status = f"`{meeting_emoji}`" if meeting_emoji else "не задан"
        absence_status = f"`{absence_emoji}`" if absence_emoji else "не задан"

        text = (
            "🎨 **Настройка emoji для календаря**\n\n"
            f"📅 **Встречи:** {meeting_status}\n"
            "   Устанавливается когда активно событие из календаря встреч\n\n"
            f"🏖 **Отсутствия:** {absence_status}\n"
            "   Устанавливается когда активно событие из календаря отсутствий\n"
            "   (приоритет выше чем у встреч)\n\n"
            "Отправьте кастомный emoji чтобы настроить."
        )

        buttons = [
            [Button.inline("📅 Emoji встречи", b"set_meeting_emoji")],
            [Button.inline("🏖 Emoji отсутствия", b"set_absence_emoji")],
            [Button.inline("« Назад", b"calendar")],
        ]

        await event.edit(text, buttons=buttons)

    @bot.on(events.CallbackQuery(data=b"set_meeting_emoji"))
    async def set_meeting_emoji_start(event):
        """Start setting meeting emoji."""
        if not await _has_access(event):
            return

        _pending_meeting_emoji.add(event.sender_id)
        _pending_absence_emoji.discard(event.sender_id)

        current = Settings.get('meeting_emoji_id')
        current_info = f"\n\nТекущий: `{current}`" if current else ""

        await event.edit(
            f"📅 **Emoji для встреч**\n\n"
            "Отправьте кастомный emoji для статуса во время встреч."
            f"{current_info}",
            buttons=[[Button.inline("❌ Отмена", b"calendar_emoji_setup")]]
        )

    @bot.on(events.CallbackQuery(data=b"set_absence_emoji"))
    async def set_absence_emoji_start(event):
        """Start setting absence emoji."""
        if not await _has_access(event):
            return

        _pending_absence_emoji.add(event.sender_id)
        _pending_meeting_emoji.discard(event.sender_id)

        current = Settings.get_absence_emoji_id()
        current_info = f"\n\nТекущий: `{current}`" if current else ""

        await event.edit(
            f"🏖 **Emoji для отсутствий**\n\n"
            "Отправьте кастомный emoji для статуса во время отсутствий.\n"
            "Отсутствия имеют приоритет выше чем встречи."
            f"{current_info}",
            buttons=[[Button.inline("❌ Отмена", b"calendar_emoji_setup")]]
        )

    @bot.on(events.CallbackQuery(data=b"calendar_test"))
    async def calendar_test(event):
        """Test CalDAV connection."""
        if not await _has_access(event):
            return

        await event.answer("🔄 Проверяю...")

        # Get detailed status
        status = await caldav_service.get_calendar_status()

        if status.get('connected'):
            cal_count = status.get('calendar_count', 0)
            active_count = status.get('active_calendar_count', 0)
            current = status.get('current_event')
            upcoming = status.get('upcoming_events', [])

            text = f"✅ **Подключение успешно**\n\n"
            text += f"📅 Календарей: {cal_count} (активных: {active_count})\n"

            if current:
                text += f"\n🔴 **Сейчас идёт:** {current.summary}\n"
                text += f"   {current.start.strftime('%H:%M')} - {current.end.strftime('%H:%M')}\n"
                text += f"   Календарь: {current.calendar_name}\n"

            if upcoming:
                text += f"\n📋 **Ближайшие события:**\n"
                for evt in upcoming[:5]:
                    text += f"• {evt.start.strftime('%H:%M')} — {evt.summary[:35]}\n"
            elif not current:
                text += "\n✅ Нет ближайших событий (8ч)\n"
        else:
            error = status.get('error', 'Неизвестная ошибка')
            text = f"❌ **Ошибка подключения**\n\n{error}"

        await event.edit(text, buttons=[[Button.inline("« Назад", b"calendar")]])

    @bot.on(events.CallbackQuery(data=b"calendar_setup"))
    async def calendar_setup_menu(event):
        """Show CalDAV setup menu."""
        if not await _has_access(event):
            return

        url = Settings.get_caldav_url()
        username = Settings.get_caldav_username()
        password = Settings.get_caldav_password()
        meeting_cals = Settings.get_caldav_meeting_calendars()
        absence_cals = Settings.get_caldav_absence_calendars()

        url_status = "✅" if url else "❌"
        user_status = "✅" if username else "❌"
        pass_status = "✅" if password else "❌"

        # Calendar info
        total_configured = len(meeting_cals) + len(absence_cals)
        if total_configured > 0:
            cal_info = f"{len(meeting_cals)} встреч, {len(absence_cals)} отсутств."
        else:
            cal_info = "не настроены"

        text = (
            "⚙️ **Настройка CalDAV**\n\n"
            f"{url_status} URL сервера: {url or 'не указан'}\n"
            f"{user_status} Логин: {username or 'не указан'}\n"
            f"{pass_status} Пароль: {'••••••' if password else 'не указан'}\n"
            f"📅 Календари: {cal_info}\n\n"
            "**Примеры серверов:**\n"
            "• Яндекс: `https://caldav.yandex.ru`\n"
            "• Google: `https://apidata.googleusercontent.com/caldav/v2`\n"
            "• iCloud: `https://caldav.icloud.com`"
        )

        buttons = [
            [Button.inline("🌐 URL сервера", b"caldav_url")],
            [Button.inline("👤 Логин", b"caldav_user")],
            [Button.inline("🔑 Пароль", b"caldav_pass")],
            [Button.inline("📅 Настроить календари", b"caldav_calendars")],
            [Button.inline("« Назад", b"calendar")],
        ]

        await event.edit(text, buttons=buttons)

    @bot.on(events.CallbackQuery(data=b"caldav_url"))
    async def caldav_url_start(event):
        """Start setting CalDAV URL."""
        if not await _has_access(event):
            return

        _pending_caldav_url.add(event.sender_id)

        current = Settings.get_caldav_url()
        current_info = f"\n\nТекущий: `{current}`" if current else ""

        await event.edit(
            "🌐 **URL CalDAV сервера**\n\n"
            "Отправьте URL вашего CalDAV сервера."
            f"{current_info}",
            buttons=[[Button.inline("❌ Отмена", b"caldav_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"caldav_user"))
    async def caldav_user_start(event):
        """Start setting CalDAV username."""
        if not await _has_access(event):
            return

        _pending_caldav_username.add(event.sender_id)

        current = Settings.get_caldav_username()
        current_info = f"\n\nТекущий: `{current}`" if current else ""

        await event.edit(
            "👤 **Логин CalDAV**\n\n"
            "Отправьте логин (обычно email)."
            f"{current_info}",
            buttons=[[Button.inline("❌ Отмена", b"caldav_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"caldav_pass"))
    async def caldav_pass_start(event):
        """Start setting CalDAV password."""
        if not await _has_access(event):
            return

        _pending_caldav_password.add(event.sender_id)

        await event.edit(
            "🔑 **Пароль CalDAV**\n\n"
            "Отправьте пароль или пароль приложения.\n\n"
            "⚠️ Для Google/Яндекс используйте пароль приложения.",
            buttons=[[Button.inline("❌ Отмена", b"caldav_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"caldav_calendars"))
    async def caldav_calendars_menu(event):
        """Show available calendars with type selection."""
        if not await _has_access(event):
            return

        if not Settings.is_caldav_configured():
            await event.answer("❌ Сначала настройте подключение", alert=True)
            return

        await event.answer("🔄 Загрузка календарей...")

        calendars = await caldav_service.get_available_calendars()

        if not calendars:
            await event.edit(
                "❌ **Календари не найдены**\n\n"
                "Не удалось получить список календарей.\n"
                "Проверьте настройки подключения.",
                buttons=[[Button.inline("« Назад", b"calendar_setup")]]
            )
            return

        meeting_cals = Settings.get_caldav_meeting_calendars()
        absence_cals = Settings.get_caldav_absence_calendars()
        total_configured = len(meeting_cals) + len(absence_cals)

        text = (
            "📅 **Настройка календарей**\n\n"
            "Нажмите на календарь чтобы изменить его тип:\n"
            "• ⬜ — не используется\n"
            "• 📅 — встречи (meeting)\n"
            "• 🏖 — отсутствие (absence)\n\n"
        )

        if total_configured > 0:
            text += f"Настроено: {total_configured} из {len(calendars)}\n"
            text += f"  📅 Встречи: {len(meeting_cals)}\n"
            text += f"  🏖 Отсутствия: {len(absence_cals)}"
        else:
            text += "Календари не настроены"

        buttons = []
        for cal in calendars:
            cal_name = cal.name.strip()
            cal_type = Settings.get_calendar_type(cal_name)

            if cal_type == 'meeting':
                icon = "📅"
                type_label = "встреча"
            elif cal_type == 'absence':
                icon = "🏖"
                type_label = "отсутствие"
            else:
                icon = "⬜"
                type_label = ""

            label = f"{icon} {cal.name}"
            if type_label:
                label += f" ({type_label})"

            callback_data = f"cal_type:{cal_name}".encode()
            buttons.append([Button.inline(label, callback_data)])

        buttons.append([Button.inline("🔄 Сбросить всё", b"caldav_calendars_reset")])
        buttons.append([Button.inline("« Назад", b"calendar_setup")])

        await event.edit(text, buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=rb"cal_type:(.+)"))
    async def caldav_calendar_cycle_type(event):
        """Cycle calendar type: none -> meeting -> absence -> none."""
        if not await _has_access(event):
            return

        calendar_name = event.pattern_match.group(1).decode().strip()
        current_type = Settings.get_calendar_type(calendar_name)

        # Cycle: none -> meeting -> absence -> none
        if current_type is None:
            new_type = 'meeting'
            await event.answer("📅 Встреча")
        elif current_type == 'meeting':
            new_type = 'absence'
            await event.answer("🏖 Отсутствие")
        else:  # absence
            new_type = None
            await event.answer("⬜ Не используется")

        Settings.set_calendar_type(calendar_name, new_type)
        caldav_service.clear_state()

        # Refresh the calendar list
        await caldav_calendars_menu(event)

    @bot.on(events.CallbackQuery(data=b"caldav_calendars_reset"))
    async def caldav_calendars_reset(event):
        """Reset all calendar type configurations."""
        if not await _has_access(event):
            return

        Settings.set_caldav_meeting_calendars([])
        Settings.set_caldav_absence_calendars([])
        caldav_service.clear_state()
        await event.answer("✅ Все настройки сброшены")

        # Refresh the calendar list
        await caldav_calendars_menu(event)

    @bot.on(events.CallbackQuery(data=b"caldav_cancel"))
    async def caldav_cancel(event):
        """Cancel CalDAV setup."""
        if not await _has_access(event):
            return

        _pending_caldav_url.discard(event.sender_id)
        _pending_caldav_username.discard(event.sender_id)
        _pending_caldav_password.discard(event.sender_id)

        await calendar_setup_menu(event)

    # =========================================================================
    # Settings
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"settings"))
    async def settings_menu(event):
        """Show settings menu."""
        if not await _has_access(event):
            return

        is_personal = await _is_personal(event)

        if is_personal:
            # Simplified settings for personal account
            text = "⚙️ **Настройки**\n\n_Вы используете бота как персональный аккаунт._"
            await event.edit(text, buttons=get_settings_keyboard(is_personal=True))
            return

        text = "⚙️ **Настройки**\n\n"

        # Personal chat status
        personal_chat_id = Settings.get_personal_chat_id()
        if personal_chat_id:
            try:
                entity = await _user_client.get_entity(personal_chat_id)
                name = getattr(entity, 'first_name', None) or getattr(entity, 'title', str(personal_chat_id))
                text += f"👤 Персональный чат: **{name}**\n"
            except Exception:
                text += f"👤 Персональный чат: `{personal_chat_id}`\n"
        else:
            text += "👤 Персональный чат: _не настроен_\n"

        text += "\n_Персональный чат используется для ASAP и других уведомлений._"

        await event.edit(text, buttons=get_settings_keyboard())

    @bot.on(events.CallbackQuery(data=b"logout_confirm"))
    async def logout_confirm(event):
        """Confirm logout."""
        if not await _has_access(event):
            return

        # Personal account cannot logout
        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        await event.edit(
            "⚠️ **Выйти из аккаунта?**\n\n"
            "Сессия Telegram-клиента будет завершена.\n"
            "Для повторного входа потребуется авторизация.",
            buttons=get_confirm_keyboard("logout")
        )

    @bot.on(events.CallbackQuery(data=b"confirm_logout"))
    async def logout(event):
        """Logout from user client."""
        if not await _has_access(event):
            return

        # Personal account cannot logout
        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        global _owner_id, _owner_username

        try:
            await _user_client.log_out()
            logger.info("User logged out via bot")
        except Exception as e:
            logger.warning(f"Logout error (may be expected): {e}")

        # Clear owner state
        _owner_id = None
        _owner_username = None

        # Disconnect client
        try:
            await _user_client.disconnect()
        except Exception as e:
            logger.warning(f"Disconnect error: {e}")

        # Delete session file to allow fresh authentication
        import os
        session_file = config.session_path + '.session'
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                logger.info(f"Session file deleted: {session_file}")
            except Exception as e:
                logger.warning(f"Failed to delete session file: {e}")

        # Reconnect client for future auth
        try:
            await _user_client.connect()
            logger.info("User client reconnected after logout")
        except Exception as e:
            logger.warning(f"Failed to reconnect after logout: {e}")

        await event.edit(
            "🚪 **Вы вышли из аккаунта**\n\n"
            "Сессия завершена. Для использования бота\n"
            "необходимо авторизоваться заново.",
            buttons=get_auth_keyboard()
        )

    # =========================================================================
    # Private Messages Settings
    # =========================================================================

    # Pending states for private messages settings
    _pending_personal_chat: set[int] = set()
    _pending_asap_webhook: set[int] = set()

    @bot.on(events.CallbackQuery(data=b"private_messages"))
    async def private_messages_menu(event):
        """Show private messages settings menu."""
        if not await _has_access(event):
            return

        webhook_url = Settings.get_asap_webhook_url()
        is_asap_enabled = Settings.is_asap_enabled()
        is_vip_as_asap = Settings.is_vip_as_asap_enabled()
        cooldown_minutes = Settings.get_asap_cooldown_minutes()

        text = "💬 **Приватные сообщения**\n\n"

        # ASAP status
        asap_status = "✅ включены" if is_asap_enabled else "❌ выключены"
        text += f"🚨 ASAP уведомления: {asap_status}\n"

        # VIP as ASAP status
        vip_status = "✅ включено" if is_vip_as_asap else "❌ выключено"
        text += f"👑 VIP как ASAP: {vip_status}\n"

        # Cooldown
        text += f"⏱ Кулдаун: {cooldown_minutes} мин\n"

        # Webhook status
        if webhook_url:
            # Show truncated URL for privacy
            url_display = webhook_url[:40] + "..." if len(webhook_url) > 40 else webhook_url
            text += f"🔗 Webhook: `{url_display}`\n"
        else:
            text += "🔗 Webhook: _не настроен_\n"

        text += "\n_ASAP уведомления отправляются когда кто-то пишет вам в личку со словом ASAP._\n"
        text += "_VIP как ASAP — уведомлять о любом сообщении от VIP-пользователей._\n"
        text += "_Кулдаун — минимальный интервал между уведомлениями от одного отправителя._"

        await event.edit(text, buttons=get_private_messages_keyboard())

    @bot.on(events.CallbackQuery(data=b"pm_personal_chat"))
    async def pm_personal_chat_start(event):
        """Start setting personal chat."""
        if not await _has_access(event):
            return

        # Personal account cannot configure personal chat
        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        _pending_personal_chat.add(event.sender_id)

        current = Settings.get_personal_chat_id()
        current_info = ""
        if current:
            try:
                entity = await _user_client.get_entity(current)
                name = getattr(entity, 'first_name', None) or getattr(entity, 'title', str(current))
                current_info = f"\n\nТекущий: **{name}**"
            except Exception:
                current_info = f"\n\nТекущий: `{current}`"

        buttons = []
        if current:
            buttons.append([Button.inline("🗑 Очистить", b"pm_personal_chat_clear")])
        buttons.append([Button.inline("❌ Отмена", b"pm_personal_chat_cancel")])

        await event.edit(
            "👤 **Персональный чат**\n\n"
            "Перешлите любое сообщение из чата,\n"
            "в который будут приходить ASAP уведомления.\n\n"
            "Или отправьте ID чата/username."
            f"{current_info}",
            buttons=buttons
        )

    @bot.on(events.CallbackQuery(data=b"pm_personal_chat_cancel"))
    async def pm_personal_chat_cancel(event):
        """Cancel personal chat setup."""
        if not await _has_access(event):
            return

        _pending_personal_chat.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await settings_menu(event)

    @bot.on(events.CallbackQuery(data=b"pm_personal_chat_clear"))
    async def pm_personal_chat_clear(event):
        """Clear personal chat setting."""
        if not await _has_access(event):
            return

        _pending_personal_chat.discard(event.sender_id)
        Settings.set_personal_chat_id(None)
        # Also clear personal account access (will fallback to env PERSONAL_TG_LOGIN)
        clear_personal_account()
        logger.info("Personal chat cleared")
        await event.answer("✅ Персональный чат очищен")
        await settings_menu(event)

    @bot.on(events.CallbackQuery(data=b"asap_on"))
    async def asap_enable(event):
        """Enable ASAP notifications."""
        if not await _has_access(event):
            return

        Settings.set_asap_enabled(True)
        logger.info("ASAP notifications enabled")
        await event.answer("✅ ASAP уведомления включены")
        await private_messages_menu(event)

    @bot.on(events.CallbackQuery(data=b"asap_off"))
    async def asap_disable(event):
        """Disable ASAP notifications."""
        if not await _has_access(event):
            return

        Settings.set_asap_enabled(False)
        logger.info("ASAP notifications disabled")
        await event.answer("❌ ASAP уведомления выключены")
        await private_messages_menu(event)

    @bot.on(events.CallbackQuery(data=b"vip_asap_on"))
    async def vip_asap_enable(event):
        """Enable VIP as ASAP notifications."""
        if not await _has_access(event):
            return

        Settings.set_vip_as_asap_enabled(True)
        logger.info("VIP as ASAP enabled")
        await event.answer("✅ VIP как ASAP включено")
        await private_messages_menu(event)

    @bot.on(events.CallbackQuery(data=b"vip_asap_off"))
    async def vip_asap_disable(event):
        """Disable VIP as ASAP notifications."""
        if not await _has_access(event):
            return

        Settings.set_vip_as_asap_enabled(False)
        logger.info("VIP as ASAP disabled")
        await event.answer("❌ VIP как ASAP выключено")
        await private_messages_menu(event)

    # Pending state for cooldown input
    _pending_asap_cooldown: set[int] = set()

    @bot.on(events.CallbackQuery(data=b"asap_cooldown"))
    async def asap_cooldown_start(event):
        """Start setting ASAP cooldown."""
        if not await _has_access(event):
            return

        _pending_asap_cooldown.add(event.sender_id)

        current = Settings.get_asap_cooldown_minutes()

        await event.edit(
            "⏱ **Кулдаун ASAP уведомлений**\n\n"
            f"Текущее значение: **{current} мин**\n\n"
            "Отправьте количество минут (1-1440).\n"
            "Это минимальный интервал между уведомлениями\n"
            "от одного отправителя.",
            buttons=[
                [Button.inline("❌ Отмена", b"asap_cooldown_cancel")]
            ]
        )

    @bot.on(events.CallbackQuery(data=b"asap_cooldown_cancel"))
    async def asap_cooldown_cancel(event):
        """Cancel cooldown setup."""
        if not await _has_access(event):
            return

        _pending_asap_cooldown.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await private_messages_menu(event)

    @bot.on(events.CallbackQuery(data=b"pm_webhook"))
    async def pm_webhook_start(event):
        """Start setting webhook URL."""
        if not await _has_access(event):
            return

        _pending_asap_webhook.add(event.sender_id)

        current = Settings.get_asap_webhook_url()
        current_info = ""
        if current:
            url_display = current[:50] + "..." if len(current) > 50 else current
            current_info = f"\n\nТекущий: `{url_display}`"

        buttons = []
        if current:
            buttons.append([Button.inline("🗑 Очистить", b"pm_webhook_clear")])
        buttons.append([Button.inline("❌ Отмена", b"pm_webhook_cancel")])

        await event.edit(
            "🔗 **Webhook URL**\n\n"
            "Отправьте URL, на который будут отправляться\n"
            "POST-запросы при ASAP уведомлениях.\n\n"
            "URL должен начинаться с http:// или https://"
            f"{current_info}",
            buttons=buttons
        )

    @bot.on(events.CallbackQuery(data=b"pm_webhook_cancel"))
    async def pm_webhook_cancel(event):
        """Cancel webhook setup."""
        if not await _has_access(event):
            return

        _pending_asap_webhook.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await private_messages_menu(event)

    @bot.on(events.CallbackQuery(data=b"pm_webhook_clear"))
    async def pm_webhook_clear(event):
        """Clear webhook URL."""
        if not await _has_access(event):
            return

        _pending_asap_webhook.discard(event.sender_id)
        Settings.set_asap_webhook_url(None)
        logger.info("ASAP webhook URL cleared")
        await event.answer("✅ Webhook очищен")
        await private_messages_menu(event)

    # =========================================================================
    # Text message handlers for setting replies and schedule
    # =========================================================================

    # Store pending reply setup: {user_id: emoji_id}
    _pending_reply_setup: dict[int, int] = {}
    # Store users in "add mode" waiting for emoji
    _pending_reply_add_mode: set[int] = set()
    # Store users waiting to input the default (no-emoji-status) reply text
    _pending_default_reply_setup: set[int] = set()
    # Store users waiting to input work schedule time
    _pending_work_time_edit: set[int] = set()
    # Store users waiting to input morning/evening emoji
    _pending_morning_emoji: set[int] = set()
    _pending_evening_emoji: set[int] = set()
    # Store users waiting to input weekend/rest emoji
    _pending_weekend_emoji: set[int] = set()
    _pending_rest_emoji: set[int] = set()
    # Store override creation state: {user_id: {"dates": (start, end)}} or {user_id: "dates"} for waiting dates
    _pending_override_dates: set[int] = set()
    _pending_override_emoji: dict[int, tuple[str, str]] = {}  # user_id -> (date_start, date_end)

    @bot.on(events.CallbackQuery(data=b"reply_add"))
    async def reply_add_start(event):
        """Start adding a new reply - wait for emoji."""
        if not await _has_access(event):
            return

        # Enable add mode for this user
        _pending_reply_add_mode.add(event.sender_id)

        await event.edit(
            "➕ **Добавить автоответ**\n\n"
            "Отправьте сообщение с эмодзи-статусом,\n"
            "для которого хотите настроить автоответ.",
            buttons=[[Button.inline("❌ Отмена", b"replies")]]
        )

    @bot.on(events.CallbackQuery(data=b"reply_default"))
    async def reply_default_view(event):
        """Show or set up the default (no-emoji-status) reply."""
        if not await _has_access(event):
            return

        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        reply = Reply.get_by_emoji(DEFAULT_REPLY_EMOJI)

        if reply is None:
            _pending_default_reply_setup.add(event.sender_id)
            await event.edit(
                "⭐ **Дефолтный автоответ**\n\n"
                "Срабатывает, когда у вас не установлен эмодзи-статус.\n\n"
                "Отправьте боту текст, который будет использоваться "
                "как дефолтный автоответ.",
                buttons=[[Button.inline("❌ Отмена", b"replies")]]
            )
            return

        msg = reply.message
        preview = (msg.text or msg.message or "(пустое сообщение)") if msg else "(пустое сообщение)"

        await event.edit(
            "⭐ **Дефолтный автоответ**\n\n"
            "Срабатывает, когда у вас не установлен эмодзи-статус.\n\n"
            f"Текущий текст:\n```\n{preview}\n```",
            buttons=[
                [Button.inline("✏️ Изменить", b"reply_default_edit")],
                [Button.inline("🗑 Удалить", b"reply_default_delete")],
                [Button.inline("« Назад", b"replies")],
            ]
        )

    @bot.on(events.CallbackQuery(data=b"reply_default_edit"))
    async def reply_default_edit(event):
        """Ask the user for a new default reply text."""
        if not await _has_access(event):
            return

        _pending_default_reply_setup.add(event.sender_id)
        await event.edit(
            "⭐ **Изменить дефолтный автоответ**\n\n"
            "Отправьте боту новый текст автоответа.",
            buttons=[[Button.inline("❌ Отмена", b"replies")]]
        )

    @bot.on(events.CallbackQuery(data=b"reply_default_delete"))
    async def reply_default_delete(event):
        """Delete the default reply."""
        if not await _has_access(event):
            return

        reply = Reply.get_by_emoji(DEFAULT_REPLY_EMOJI)
        if reply:
            reply.delete()
            logger.info("Default reply deleted via bot")
            await event.answer("✅ Дефолтный автоответ удалён")
        else:
            await event.answer("❌ Дефолтный автоответ не найден", alert=True)

        await reply_default_view(event)

    @bot.on(events.NewMessage(func=lambda e: e.is_private))
    async def handle_private_message(event):
        """Handle private messages for reply setup and authentication."""
        # Skip commands
        if event.message.text and event.message.text.startswith('/'):
            return

        # =====================================================================
        # Authentication Flow - handle phone, code, 2fa input
        # =====================================================================
        if event.sender_id in _auth_state:
            if not await _can_authenticate(event):
                return

            state = _auth_state[event.sender_id]
            text = event.message.text.strip() if event.message.text else ""

            # Handle cancel button
            if text == "❌ Отмена":
                del _auth_state[event.sender_id]
                await event.respond(
                    "❌ **Авторизация отменена**\n\n"
                    "Нажмите /start чтобы начать заново.",
                    buttons=Button.clear()
                )
                return

            # Step 1: Phone number input
            if state.get('step') == 'phone':
                # Check if contact was shared via button
                if event.message.contact:
                    phone = event.message.contact.phone_number
                    if not phone.startswith('+'):
                        phone = '+' + phone
                else:
                    phone = text
                    if not phone.startswith('+'):
                        phone = '+' + phone

                try:
                    result = await _user_client.send_code_request(phone)
                    state['phone'] = phone
                    state['phone_code_hash'] = result.phone_code_hash
                    state['step'] = 'code'

                    await event.respond(
                        "🔢 **Авторизация - Шаг 2/3**\n\n"
                        f"Код отправлен на номер `{phone}`\n\n"
                        "Введите код, разделив цифры дефисами:\n"
                        "`1-2-3-4-5-6`\n\n"
                        "Это нужно, чтобы Telegram не заблокировал код.",
                        buttons=Button.clear()
                    )
                    await event.respond(
                        "👆 Введите код через дефисы:",
                        buttons=[
                            [Button.inline("🔄 Отправить ещё раз", b"auth_resend")],
                            [Button.inline("❌ Отмена", b"auth_cancel")],
                        ]
                    )
                except Exception as e:
                    logger.error(f"Failed to send code: {e}")
                    await event.respond(
                        f"❌ **Ошибка**\n\n{e}\n\n"
                        "Попробуйте ещё раз:",
                        buttons=Button.clear()
                    )
                return

            # Step 2: Verification code input
            elif state.get('step') == 'code':
                # Try to extract code from message (handles copied or forwarded messages)
                import re

                # Get text from message (works for both regular and forwarded)
                msg_text = event.message.text or event.message.message or ""

                # Search for 5-6 digit code in the text
                code_match = re.search(r'\b(\d{5,6})\b', msg_text)
                if code_match:
                    code = code_match.group(1)
                    logger.info(f"Extracted auth code from message: {code[:2]}***")
                else:
                    # Fallback: treat entire input as code
                    code = msg_text.replace(' ', '').replace('-', '')

                try:
                    await _user_client.sign_in(
                        phone=state['phone'],
                        code=code,
                        phone_code_hash=state['phone_code_hash']
                    )

                    # Success! Clear auth state
                    del _auth_state[event.sender_id]

                    # Get user info and set as owner
                    me = await _user_client.get_me()
                    set_owner_id(me.id)
                    if me.username:
                        set_owner_username(me.username)

                    logger.info(f"User authorized via bot: {me.id} (@{me.username})")

                    # Clear chat history to remove sensitive auth data
                    await _clear_bot_chat_history()

                    await event.respond(
                        "✅ **Авторизация успешна!**\n\n"
                        f"Вы авторизованы как: @{me.username or me.id}\n\n"
                        "Теперь вы можете использовать бота.",
                        buttons=get_main_menu_keyboard()
                    )

                except SessionPasswordNeededError:
                    # 2FA required
                    state['step'] = '2fa'
                    await event.respond(
                        "🔒 **Авторизация - Шаг 3/3**\n\n"
                        "Ваш аккаунт защищён двухфакторной аутентификацией.\n\n"
                        "Введите пароль 2FA:",
                        buttons=get_auth_cancel_keyboard()
                    )

                except PhoneCodeInvalidError:
                    await event.respond(
                        "❌ **Неверный код**\n\n"
                        "Попробуйте ещё раз или запросите новый код:",
                        buttons=[
                            [Button.inline("🔄 Отправить ещё раз", b"auth_resend")],
                            [Button.inline("❌ Отмена", b"auth_cancel")],
                        ]
                    )

                except Exception as e:
                    logger.error(f"Sign in failed: {e}")
                    await event.respond(
                        f"❌ **Ошибка авторизации**\n\n{e}",
                        buttons=[
                            [Button.inline("🔄 Попробовать снова", b"auth_resend")],
                            [Button.inline("❌ Отмена", b"auth_cancel")],
                        ]
                    )
                return

            # Step 3: 2FA password input
            elif state.get('step') == '2fa':
                password = text

                try:
                    await _user_client.sign_in(
                        phone=state['phone'],
                        password=password,
                        phone_code_hash=state['phone_code_hash']
                    )

                    # Success! Clear auth state
                    del _auth_state[event.sender_id]

                    # Get user info and set as owner
                    me = await _user_client.get_me()
                    set_owner_id(me.id)
                    if me.username:
                        set_owner_username(me.username)

                    logger.info(f"User authorized via bot (2FA): {me.id} (@{me.username})")

                    # Clear chat history to remove sensitive auth data
                    await _clear_bot_chat_history()

                    await event.respond(
                        "✅ **Авторизация успешна!**\n\n"
                        f"Вы авторизованы как: @{me.username or me.id}\n\n"
                        "Теперь вы можете использовать бота.",
                        buttons=get_main_menu_keyboard()
                    )

                except PasswordHashInvalidError:
                    await event.respond(
                        "❌ **Неверный пароль**\n\n"
                        "Попробуйте ещё раз:",
                        buttons=get_auth_cancel_keyboard()
                    )

                except Exception as e:
                    logger.error(f"2FA sign in failed: {e}")
                    await event.respond(
                        f"❌ **Ошибка авторизации**\n\n{e}",
                        buttons=get_auth_cancel_keyboard()
                    )
                return

        # =====================================================================
        # Reply/Schedule setup flow (only for authorized users)
        # =====================================================================
        if not await _has_access(event):
            return

        # Check if user is editing online mention delay
        if event.sender_id in _pending_delay_edit:
            text = event.message.text.strip() if event.message.text else ""
            try:
                minutes = int(text)
                if 0 <= minutes <= 60:
                    Settings.set_online_mention_delay(minutes)
                    _pending_delay_edit.discard(event.sender_id)
                    logger.info(f"Online mention delay set to {minutes} minutes")

                    if minutes > 0:
                        await event.respond(
                            f"✅ Задержка установлена: {minutes} мин",
                            buttons=get_mention_online_keyboard()
                        )
                    else:
                        await event.respond(
                            "✅ Задержка отключена (уведомления сразу)",
                            buttons=get_mention_online_keyboard()
                        )
                else:
                    await event.respond(
                        "❌ Введите число от 0 до 60.",
                        buttons=[[Button.inline("❌ Отмена", b"online_delay_cancel")]]
                    )
            except ValueError:
                await event.respond(
                    "❌ Введите число от 0 до 60.",
                    buttons=[[Button.inline("❌ Отмена", b"online_delay_cancel")]]
                )
            return

        # Check if user is adding VIP user
        if event.sender_id in _pending_vip_user:
            text = event.message.text.strip() if event.message.text else ""
            if text:
                username = text.lower().lstrip('@')
                VipList.add_user(username)
                _pending_vip_user.discard(event.sender_id)
                logger.info(f"VIP user added: @{username}")

                await event.respond(
                    f"✅ Пользователь @{username} добавлен!",
                    buttons=get_vip_users_keyboard()
                )
            else:
                await event.respond(
                    "❌ Отправьте username пользователя.",
                    buttons=[[Button.inline("❌ Отмена", b"vip_add_user_cancel")]]
                )
            return

        # Check if user is adding VIP chat
        if event.sender_id in _pending_vip_chat:
            # Check if message is forwarded
            fwd = event.message.fwd_from
            if fwd and hasattr(fwd, 'from_id') and fwd.from_id:
                # Get chat ID from forwarded message
                from_id = fwd.from_id
                if hasattr(from_id, 'channel_id'):
                    chat_id = -100 * 10**10 + from_id.channel_id
                    chat_id = int(f"-100{from_id.channel_id}")
                elif hasattr(from_id, 'chat_id'):
                    chat_id = -from_id.chat_id
                else:
                    await event.respond(
                        "❌ Не удалось определить ID чата.\n"
                        "Попробуйте ввести ID вручную.",
                        buttons=[[Button.inline("❌ Отмена", b"vip_add_chat_cancel")]]
                    )
                    return

                # Try to get chat name
                try:
                    chat_entity = await _user_client.get_entity(chat_id)
                    chat_title = getattr(chat_entity, 'title', None) or str(chat_id)
                except Exception:
                    chat_title = str(chat_id)

                VipList.add_chat(chat_id, chat_title)
                _pending_vip_chat.discard(event.sender_id)
                logger.info(f"VIP chat added: {chat_id} ({chat_title})")

                await event.respond(
                    f"✅ Чат добавлен!\n\n{chat_title}",
                    buttons=get_vip_chats_keyboard()
                )
                return

            # Try to parse chat ID from text
            text = event.message.text.strip() if event.message.text else ""
            if text:
                try:
                    chat_id = int(text)
                    # Try to get chat name
                    try:
                        chat_entity = await _user_client.get_entity(chat_id)
                        chat_title = getattr(chat_entity, 'title', None) or str(chat_id)
                    except Exception:
                        chat_title = str(chat_id)

                    VipList.add_chat(chat_id, chat_title)
                    _pending_vip_chat.discard(event.sender_id)
                    logger.info(f"VIP chat added: {chat_id} ({chat_title})")

                    await event.respond(
                        f"✅ Чат добавлен!\n\n{chat_title}",
                        buttons=get_vip_chats_keyboard()
                    )
                except ValueError:
                    await event.respond(
                        "❌ Перешлите сообщение из чата\n"
                        "или введите числовой ID.",
                        buttons=[[Button.inline("❌ Отмена", b"vip_add_chat_cancel")]]
                    )
            else:
                await event.respond(
                    "❌ Перешлите сообщение из чата\n"
                    "или введите числовой ID.",
                    buttons=[[Button.inline("❌ Отмена", b"vip_add_chat_cancel")]]
                )
            return

        # Check if user is setting productivity summary time
        if event.sender_id in _pending_productivity_time:
            text = event.message.text.strip() if event.message.text else ""
            if text:
                # Validate time format HH:MM
                import re
                match = re.match(r'^(\d{1,2}):(\d{2})$', text)
                if match:
                    hour = int(match.group(1))
                    minute = int(match.group(2))
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        time_str = f"{hour:02d}:{minute:02d}"
                        Settings.set_productivity_summary_time(time_str)
                        _pending_productivity_time.discard(event.sender_id)
                        logger.info(f"Productivity summary time set to {time_str}")

                        await event.respond(
                            f"✅ Время сводки установлено: {time_str}",
                            buttons=get_productivity_keyboard()
                        )
                        return

                await event.respond(
                    "❌ Неверный формат времени.\n\n"
                    "Введите время в формате **ЧЧ:ММ**\n"
                    "Например: `19:00` или `9:30`",
                    buttons=[[Button.inline("❌ Отмена", b"productivity_time_cancel")]]
                )
            return

        # Check if user is adding productivity extra chat
        if event.sender_id in _pending_productivity_chat:
            # Check if message is forwarded
            fwd = event.message.fwd_from
            if fwd and hasattr(fwd, 'from_id') and fwd.from_id:
                # Get chat ID from forwarded message
                from_id = fwd.from_id
                if hasattr(from_id, 'channel_id'):
                    chat_id = int(f"-100{from_id.channel_id}")
                elif hasattr(from_id, 'chat_id'):
                    chat_id = -from_id.chat_id
                else:
                    await event.respond(
                        "❌ Не удалось определить ID чата.\n"
                        "Попробуйте ввести ID вручную.",
                        buttons=[[Button.inline("❌ Отмена", b"productivity_chat_add_cancel")]]
                    )
                    return

                # Try to get chat name
                try:
                    chat_entity = await _user_client.get_entity(chat_id)
                    chat_title = getattr(chat_entity, 'title', None) or str(chat_id)
                except Exception:
                    chat_title = str(chat_id)

                Settings.add_productivity_extra_chat(chat_id)
                _pending_productivity_chat.discard(event.sender_id)
                logger.info(f"Productivity extra chat added: {chat_id} ({chat_title})")

                await event.respond(
                    f"✅ Чат добавлен!\n\n{chat_title}",
                    buttons=get_productivity_keyboard()
                )
                return

            # Try to parse chat ID from text
            text = event.message.text.strip() if event.message.text else ""
            if text:
                try:
                    chat_id = int(text)
                    # Try to get chat name
                    try:
                        chat_entity = await _user_client.get_entity(chat_id)
                        chat_title = getattr(chat_entity, 'title', None) or str(chat_id)
                    except Exception:
                        chat_title = str(chat_id)

                    Settings.add_productivity_extra_chat(chat_id)
                    _pending_productivity_chat.discard(event.sender_id)
                    logger.info(f"Productivity extra chat added: {chat_id} ({chat_title})")

                    await event.respond(
                        f"✅ Чат добавлен!\n\n{chat_title}",
                        buttons=get_productivity_keyboard()
                    )
                except ValueError:
                    await event.respond(
                        "❌ Перешлите сообщение из чата\n"
                        "или введите числовой ID.",
                        buttons=[[Button.inline("❌ Отмена", b"productivity_chat_add_cancel")]]
                    )
            else:
                await event.respond(
                    "❌ Перешлите сообщение из чата\n"
                    "или введите числовой ID.",
                    buttons=[[Button.inline("❌ Отмена", b"productivity_chat_add_cancel")]]
                )
            return

        # Check if user is editing work schedule (time or emoji)
        if event.sender_id in _pending_work_time_edit:
            entities = event.message.entities or []
            custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]
            text = event.message.text.strip() if event.message.text else ""

            work = Schedule.get_work_schedule()
            if not work:
                _pending_work_time_edit.discard(event.sender_id)
                await event.respond(
                    "❌ Рабочее расписание не найдено.",
                    buttons=get_schedule_keyboard()
                )
                return

            # Check if user sent emoji
            if custom_emojis:
                emoji_id = custom_emojis[0].document_id
                work.emoji_id = str(emoji_id)
                work.save()
                _pending_work_time_edit.discard(event.sender_id)
                logger.info(f"Work emoji updated to {emoji_id}")

                await event.respond(
                    f"✅ Эмодзи для работы изменён!",
                    buttons=get_schedule_keyboard()
                )
                return

            # Parse time format: "09:00-18:00" or "09:00 - 18:00"
            match = TIME_RANGE_PATTERN.match(text)

            if not match:
                await event.respond(
                    "❌ Неверный формат.\n\n"
                    "Отправьте время `09:00-18:00` или эмодзи.",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_work_edit_cancel")]]
                )
                return

            time_start = match.group(1)
            time_end = match.group(2)

            # Normalize to HH:MM format
            time_start = ':'.join(p.zfill(2) for p in time_start.split(':'))
            time_end = ':'.join(p.zfill(2) for p in time_end.split(':'))

            # Update work schedule time
            work.time_start = time_start
            work.time_end = time_end
            work.save()
            logger.info(f"Work schedule time updated to {time_start}-{time_end}")

            # Update related schedules to match work time
            updates = []

            # Friday weekend starts when work ends
            friday_weekend = Schedule.get_friday_weekend_schedule()
            if friday_weekend and friday_weekend.time_start != time_end:
                friday_weekend.time_start = time_end
                friday_weekend.save()
                updates.append(f"📅 Выходные в ПТ с **{time_end}**")
                logger.info(f"Friday weekend start time updated to {time_end}")

            # Morning ends when work starts
            morning = Schedule.get_morning_schedule()
            if morning and morning.time_end != time_start:
                morning.time_end = time_start
                morning.save()
                updates.append(f"🌅 Утро до **{time_start}**")
                logger.info(f"Morning end time updated to {time_start}")

            # Evening starts when work ends
            evening = Schedule.get_evening_schedule()
            if evening and evening.time_start != time_end:
                evening.time_start = time_end
                evening.save()
                updates.append(f"🌙 Вечер с **{time_end}**")
                logger.info(f"Evening start time updated to {time_end}")

            _pending_work_time_edit.discard(event.sender_id)

            msg = f"✅ Рабочее время изменено!\n\nНовое время: **{time_start}—{time_end}**"
            if updates:
                msg += "\n\n" + "\n".join(updates)

            await event.respond(msg, buttons=get_schedule_keyboard())
            return

        # Check if user is setting morning emoji
        if event.sender_id in _pending_morning_emoji:
            entities = event.message.entities or []
            custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

            if not custom_emojis:
                await event.respond(
                    "❌ Отправьте сообщение с кастомным эмодзи.",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_morning_cancel")]]
                )
                return

            emoji_id = custom_emojis[0].document_id
            work = Schedule.get_work_schedule()
            work_start = work.time_start if work else "09:00"

            Schedule.set_morning_emoji(emoji_id, work_start)
            _pending_morning_emoji.discard(event.sender_id)
            logger.info(f"Morning emoji set to {emoji_id}")

            await event.respond(
                f"✅ Эмодзи для утра установлен!\n\n"
                f"Время: **00:00—{work_start}** (ПН-ПТ)",
                buttons=get_schedule_keyboard()
            )
            return

        # Check if user is setting evening emoji
        if event.sender_id in _pending_evening_emoji:
            entities = event.message.entities or []
            custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

            if not custom_emojis:
                await event.respond(
                    "❌ Отправьте сообщение с кастомным эмодзи.",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_evening_cancel")]]
                )
                return

            emoji_id = custom_emojis[0].document_id
            work = Schedule.get_work_schedule()
            work_end = work.time_end if work else "18:00"

            Schedule.set_evening_emoji(emoji_id, work_end)
            _pending_evening_emoji.discard(event.sender_id)
            logger.info(f"Evening emoji set to {emoji_id}")

            await event.respond(
                f"✅ Эмодзи для вечера установлен!\n\n"
                f"Время: **{work_end}—23:59** (ПН-ПТ)",
                buttons=get_schedule_keyboard()
            )
            return

        # Check if user is setting weekend emoji
        if event.sender_id in _pending_weekend_emoji:
            entities = event.message.entities or []
            custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

            if not custom_emojis:
                await event.respond(
                    "❌ Отправьте сообщение с кастомным эмодзи.",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_weekend_cancel")]]
                )
                return

            emoji_id = custom_emojis[0].document_id
            work = Schedule.get_work_schedule()
            work_end = work.time_end if work else "18:00"

            Schedule.set_weekend_emoji(emoji_id, work_end)
            _pending_weekend_emoji.discard(event.sender_id)
            logger.info(f"Weekend emoji set to {emoji_id}")

            await event.respond(
                f"✅ Эмодзи для выходных установлен!\n\n"
                f"ПТ с **{work_end}** + СБ-ВС весь день",
                buttons=get_schedule_keyboard()
            )
            return

        # Check if user is setting rest emoji
        if event.sender_id in _pending_rest_emoji:
            entities = event.message.entities or []
            custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

            if not custom_emojis:
                await event.respond(
                    "❌ Отправьте сообщение с кастомным эмодзи.",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_rest_cancel")]]
                )
                return

            emoji_id = custom_emojis[0].document_id

            Schedule.set_rest_emoji(emoji_id)
            _pending_rest_emoji.discard(event.sender_id)
            logger.info(f"Rest emoji set to {emoji_id}")

            await event.respond(
                f"✅ Эмодзи по умолчанию установлен!",
                buttons=get_schedule_keyboard()
            )
            return

        # Check if user is setting CalDAV URL
        if event.sender_id in _pending_caldav_url:
            text = event.message.text.strip() if event.message.text else ""

            if not text.startswith("http"):
                await event.respond(
                    "❌ URL должен начинаться с http:// или https://",
                    buttons=[[Button.inline("❌ Отмена", b"caldav_cancel")]]
                )
                return

            Settings.set_caldav_url(text)
            _pending_caldav_url.discard(event.sender_id)
            caldav_service.disconnect()  # Force reconnect with new settings
            logger.info(f"CalDAV URL set to {text}")

            await event.respond(
                "✅ URL сервера сохранён!",
                buttons=[[Button.inline("« К настройке CalDAV", b"calendar_setup")]]
            )
            return

        # Check if user is setting CalDAV username
        if event.sender_id in _pending_caldav_username:
            text = event.message.text.strip() if event.message.text else ""

            if not text:
                await event.respond(
                    "❌ Введите логин",
                    buttons=[[Button.inline("❌ Отмена", b"caldav_cancel")]]
                )
                return

            Settings.set_caldav_username(text)
            _pending_caldav_username.discard(event.sender_id)
            caldav_service.disconnect()
            logger.info(f"CalDAV username set")

            await event.respond(
                "✅ Логин сохранён!",
                buttons=[[Button.inline("« К настройке CalDAV", b"calendar_setup")]]
            )
            return

        # Check if user is setting CalDAV password
        if event.sender_id in _pending_caldav_password:
            text = event.message.text.strip() if event.message.text else ""

            if not text:
                await event.respond(
                    "❌ Введите пароль",
                    buttons=[[Button.inline("❌ Отмена", b"caldav_cancel")]]
                )
                return

            Settings.set_caldav_password(text)
            _pending_caldav_password.discard(event.sender_id)
            caldav_service.disconnect()
            logger.info("CalDAV password set")

            # Delete the message with password for security
            try:
                await event.message.delete()
            except Exception:
                pass

            await bot.send_message(
                event.sender_id,
                "✅ Пароль сохранён!",
                buttons=[[Button.inline("« К настройке CalDAV", b"calendar_setup")]]
            )
            return

        # Check if user is setting personal chat for ASAP notifications
        if event.sender_id in _pending_personal_chat:
            chat_id = None
            chat_name = None

            # Check if message was forwarded - get chat from forward
            if event.message.fwd_from:
                fwd = event.message.fwd_from
                if hasattr(fwd, 'from_id') and fwd.from_id:
                    from telethon.tl.types import PeerUser, PeerChat, PeerChannel
                    if isinstance(fwd.from_id, PeerUser):
                        chat_id = fwd.from_id.user_id
                    elif isinstance(fwd.from_id, PeerChat):
                        chat_id = fwd.from_id.chat_id
                    elif isinstance(fwd.from_id, PeerChannel):
                        chat_id = fwd.from_id.channel_id

            # If not forwarded, try to parse text as chat ID or username
            if not chat_id:
                text = event.message.text.strip() if event.message.text else ""
                if text:
                    # Try as numeric ID
                    try:
                        chat_id = int(text)
                    except ValueError:
                        # Try as username
                        try:
                            entity = await _user_client.get_entity(text)
                            chat_id = entity.id
                            chat_name = getattr(entity, 'first_name', None) or \
                                       getattr(entity, 'title', None) or str(chat_id)
                        except Exception as e:
                            await event.respond(
                                f"❌ Не удалось найти чат: {text}\n\n"
                                "Перешлите сообщение из нужного чата или введите корректный ID/username.",
                                buttons=[[Button.inline("❌ Отмена", b"pm_personal_chat_cancel")]]
                            )
                            return

            if not chat_id:
                await event.respond(
                    "❌ Не удалось определить чат.\n\n"
                    "Перешлите любое сообщение из чата или введите ID/username.",
                    buttons=[[Button.inline("❌ Отмена", b"pm_personal_chat_cancel")]]
                )
                return

            # Get chat name if not already set
            if not chat_name:
                try:
                    entity = await _user_client.get_entity(chat_id)
                    chat_name = getattr(entity, 'first_name', None) or \
                               getattr(entity, 'title', None) or str(chat_id)
                except Exception:
                    chat_name = str(chat_id)

            Settings.set_personal_chat_id(chat_id)
            _pending_personal_chat.discard(event.sender_id)

            # Also grant bot access to this user
            set_personal_id(chat_id)
            try:
                entity = await _user_client.get_entity(chat_id)
                if hasattr(entity, 'username') and entity.username:
                    set_personal_username(entity.username)
            except Exception:
                pass

            logger.info(f"Personal chat set to {chat_id} ({chat_name})")

            await event.respond(
                f"✅ Персональный чат установлен!\n\n**{chat_name}**\n\nASAP уведомления будут приходить в этот чат.\n\nЭтому пользователю также доступны настройки бота.",
                buttons=[[Button.inline("« Назад", b"settings")]]
            )
            return

        # Check if user is setting ASAP webhook URL
        if event.sender_id in _pending_asap_webhook:
            text = event.message.text.strip() if event.message.text else ""

            if not text.startswith("http"):
                await event.respond(
                    "❌ URL должен начинаться с http:// или https://",
                    buttons=[[Button.inline("❌ Отмена", b"pm_webhook_cancel")]]
                )
                return

            Settings.set_asap_webhook_url(text)
            _pending_asap_webhook.discard(event.sender_id)
            logger.info(f"ASAP webhook URL set")

            await event.respond(
                "✅ Webhook URL сохранён!",
                buttons=[[Button.inline("« Назад", b"private_messages")]]
            )
            return

        # Check if user is setting ASAP cooldown
        if event.sender_id in _pending_asap_cooldown:
            text = event.message.text.strip() if event.message.text else ""

            try:
                minutes = int(text)
                if minutes < 1 or minutes > 1440:
                    raise ValueError("Out of range")
            except ValueError:
                await event.respond(
                    "❌ Введите число от 1 до 1440",
                    buttons=[[Button.inline("❌ Отмена", b"asap_cooldown_cancel")]]
                )
                return

            Settings.set_asap_cooldown_minutes(minutes)
            _pending_asap_cooldown.discard(event.sender_id)
            logger.info(f"ASAP cooldown set to {minutes} minutes")

            await event.respond(
                f"✅ Кулдаун установлен: {minutes} мин",
                buttons=[[Button.inline("« Назад", b"private_messages")]]
            )
            return

        # Check if user is setting meeting emoji
        if event.sender_id in _pending_meeting_emoji:
            # Extract custom emoji from message
            emoji_id = None
            if event.message.entities:
                for entity in event.message.entities:
                    if hasattr(entity, 'document_id'):
                        emoji_id = str(entity.document_id)
                        break

            if not emoji_id:
                await event.respond(
                    "❌ Отправьте кастомный emoji (не обычный)",
                    buttons=[[Button.inline("❌ Отмена", b"calendar_emoji_setup")]]
                )
                return

            Settings.set('meeting_emoji_id', emoji_id)
            _pending_meeting_emoji.discard(event.sender_id)
            logger.info(f"Meeting emoji set to {emoji_id}")

            await event.respond(
                f"✅ Emoji для встреч сохранён!\n\nID: `{emoji_id}`",
                buttons=[[Button.inline("« Назад", b"calendar_emoji_setup")]]
            )
            return

        # Check if user is setting absence emoji
        if event.sender_id in _pending_absence_emoji:
            # Extract custom emoji from message
            emoji_id = None
            if event.message.entities:
                for entity in event.message.entities:
                    if hasattr(entity, 'document_id'):
                        emoji_id = str(entity.document_id)
                        break

            if not emoji_id:
                await event.respond(
                    "❌ Отправьте кастомный emoji (не обычный)",
                    buttons=[[Button.inline("❌ Отмена", b"calendar_emoji_setup")]]
                )
                return

            Settings.set_absence_emoji_id(emoji_id)
            _pending_absence_emoji.discard(event.sender_id)
            logger.info(f"Absence emoji set to {emoji_id}")

            await event.respond(
                f"✅ Emoji для отсутствий сохранён!\n\nID: `{emoji_id}`",
                buttons=[[Button.inline("« Назад", b"calendar_emoji_setup")]]
            )
            return

        # Check if user is entering override dates
        if event.sender_id in _pending_override_dates:
            text = event.message.text.strip() if event.message.text else ""
            parsed = parse_datetime_range(text)

            if not parsed:
                await event.respond(
                    "❌ Неверный формат.\n\n"
                    "Примеры:\n"
                    "• `06.01-07.01` — весь день\n"
                    "• `06.01 9:30-11:30` — время в один день\n"
                    "• `06.01 12:00 - 07.01 15:00` — диапазон",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_override_cancel")]]
                )
                return

            date_start, time_start, date_end, time_end = parsed

            # Normalize time format
            time_start = ':'.join(p.zfill(2) for p in time_start.split(':'))
            time_end = ':'.join(p.zfill(2) for p in time_end.split(':'))

            # Move to emoji input stage
            _pending_override_dates.discard(event.sender_id)
            _pending_override_emoji[event.sender_id] = (date_start, time_start, date_end, time_end)

            # Format display
            if time_start == "00:00" and time_end == "23:59":
                period_display = f"**{date_start}** — **{date_end}**"
            elif date_start == date_end:
                period_display = f"**{date_start}** с **{time_start}** до **{time_end}**"
            else:
                period_display = f"**{date_start} {time_start}** — **{date_end} {time_end}**"

            await event.respond(
                f"📅 Период: {period_display}\n\n"
                f"Теперь отправьте эмодзи:",
                buttons=[[Button.inline("❌ Отмена", b"schedule_override_cancel")]]
            )
            return

        # Check if user is entering override emoji
        if event.sender_id in _pending_override_emoji:
            entities = event.message.entities or []
            custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

            if not custom_emojis:
                await event.respond(
                    "❌ Отправьте сообщение с кастомным эмодзи.",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_override_cancel")]]
                )
                return

            emoji_id = custom_emojis[0].document_id
            date_start, time_start, date_end, time_end = _pending_override_emoji.pop(event.sender_id)

            Schedule.create_override(emoji_id, date_start, date_end, time_start, time_end)
            logger.info(f"Override created: {date_start} {time_start} - {date_end} {time_end} with emoji {emoji_id}")

            # Format display
            if time_start == "00:00" and time_end == "23:59":
                period_display = f"**{date_start}** — **{date_end}**"
            elif date_start == date_end:
                period_display = f"**{date_start}** с **{time_start}** до **{time_end}**"
            else:
                period_display = f"**{date_start} {time_start}** — **{date_end} {time_end}**"

            await event.respond(
                f"✅ Временное правило создано!\n\n"
                f"📅 {period_display}",
                buttons=get_schedule_keyboard()
            )
            return

        # Default reply (no emoji status) - waiting for text
        if event.sender_id in _pending_default_reply_setup:
            _pending_default_reply_setup.discard(event.sender_id)

            Reply.create(DEFAULT_REPLY_EMOJI, event.message)
            logger.info("Default reply set via bot")

            await event.respond(
                "✅ Дефолтный автоответ сохранён!\n\n"
                "Срабатывает, когда у вас не установлен эмодзи-статус.",
                buttons=get_main_menu_keyboard()
            )
            return

        # Check if we have pending emoji (waiting for reply text) - FIRST!
        if event.sender_id in _pending_reply_setup:
            emoji_id = _pending_reply_setup.pop(event.sender_id)

            # Save the reply (even if it contains custom emojis)
            Reply.create(emoji_id, event.message)
            logger.info(f"Reply set for emoji {emoji_id} via bot")

            await event.respond(
                f"✅ Автоответ сохранён!\n\n"
                f"Emoji ID: `{emoji_id}`",
                buttons=get_main_menu_keyboard()
            )
            return

        # Check if user is in "add mode" and message contains custom emoji
        if event.sender_id in _pending_reply_add_mode:
            entities = event.message.entities or []
            custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

            if custom_emojis:
                # User sent emoji - store it for reply setup
                _pending_reply_add_mode.discard(event.sender_id)
                emoji_id = custom_emojis[0].document_id
                _pending_reply_setup[event.sender_id] = emoji_id

                await event.respond(
                    f"📝 Эмодзи выбран: `{emoji_id}`\n\n"
                    "Теперь отправьте текст автоответа для этого статуса.\n"
                    "Или нажмите кнопку для отмены.",
                    buttons=[[Button.inline("❌ Отмена", b"cancel_reply_setup")]]
                )
                return

    @bot.on(events.CallbackQuery(data=b"cancel_reply_setup"))
    async def cancel_reply_setup(event):
        """Cancel reply setup."""
        if not await _has_access(event):
            return

        # Clear add mode and pending setup
        _pending_reply_add_mode.discard(event.sender_id)
        _pending_default_reply_setup.discard(event.sender_id)
        if event.sender_id in _pending_reply_setup:
            del _pending_reply_setup[event.sender_id]

        await event.edit(
            "❌ Настройка автоответа отменена.",
            buttons=get_main_menu_keyboard()
        )

    # =========================================================================
    # Autoreply Toggle
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"autoreply_toggle_on"))
    async def autoreply_toggle_on(event):
        """Enable autoreply."""
        if not await _has_access(event):
            return

        Settings.set_autoreply_enabled(True)
        logger.info("Autoreply enabled via bot")
        await event.answer("✅ Автоответы включены")
        await replies_menu(event)

    @bot.on(events.CallbackQuery(data=b"autoreply_toggle_off"))
    async def autoreply_toggle_off(event):
        """Disable autoreply."""
        if not await _has_access(event):
            return

        Settings.set_autoreply_enabled(False)
        logger.info("Autoreply disabled via bot")
        await event.answer("🔴 Автоответы выключены")
        await replies_menu(event)

    # =========================================================================
    # Mentions Menu
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"mentions"))
    async def mentions_menu(event):
        """Show mentions configuration menu."""
        if not await _has_access(event):
            return

        offline_status = "✅" if Settings.is_offline_mention_enabled() else "❌"
        online_status = "✅" if Settings.is_online_mention_enabled() else "❌"
        delay = Settings.get_online_mention_delay()
        vip_count = len(VipList.get_all())

        text = (
            "🔔 **Уведомления о призыве**\n\n"
            f"📴 Во время отсутствия: {offline_status}\n"
            f"📱 Во время онлайн: {online_status}"
        )
        if Settings.is_online_mention_enabled() and delay > 0:
            text += f" (задержка {delay} мин)"
        text += f"\n⭐ Приоритетных: {vip_count}"

        await event.edit(text, buttons=get_mentions_keyboard())

    @bot.on(events.CallbackQuery(data=b"mention_offline"))
    async def mention_offline_menu(event):
        """Show offline mention settings."""
        if not await _has_access(event):
            return

        is_enabled = Settings.is_offline_mention_enabled()
        status = "✅ включены" if is_enabled else "❌ выключены"

        text = (
            "📴 **Уведомления во время отсутствия**\n\n"
            f"Статус: {status}\n\n"
            "Уведомления приходят сразу, когда вас упоминают\n"
            "в группе, а у вас не рабочий эмодзи-статус."
        )

        await event.edit(text, buttons=get_mention_offline_keyboard())

    @bot.on(events.CallbackQuery(data=b"mention_online"))
    async def mention_online_menu(event):
        """Show online mention settings."""
        if not await _has_access(event):
            return

        is_enabled = Settings.is_online_mention_enabled()
        delay = Settings.get_online_mention_delay()
        status = "✅ включены" if is_enabled else "❌ выключены"

        text = (
            "📱 **Уведомления во время онлайн**\n\n"
            f"Статус: {status}\n"
        )
        if delay > 0:
            text += f"Задержка: {delay} мин\n\n"
            text += "Если вы не прочитаете сообщение за это время,\n"
            text += "вам придёт уведомление."
        else:
            text += "Задержка: без задержки\n\n"
            text += "Уведомления приходят сразу."

        await event.edit(text, buttons=get_mention_online_keyboard())

    @bot.on(events.CallbackQuery(data=b"offline_mention_on"))
    async def offline_mention_enable(event):
        """Enable offline mention notifications."""
        if not await _has_access(event):
            return

        Settings.set_offline_mention_enabled(True)
        logger.info("Offline mention notifications enabled")
        await event.answer("✅ Уведомления включены")
        await mention_offline_menu(event)

    @bot.on(events.CallbackQuery(data=b"offline_mention_off"))
    async def offline_mention_disable(event):
        """Disable offline mention notifications."""
        if not await _has_access(event):
            return

        Settings.set_offline_mention_enabled(False)
        logger.info("Offline mention notifications disabled")
        await event.answer("🔴 Уведомления выключены")
        await mention_offline_menu(event)

    @bot.on(events.CallbackQuery(data=b"online_mention_on"))
    async def online_mention_enable(event):
        """Enable online mention notifications."""
        if not await _has_access(event):
            return

        Settings.set_online_mention_enabled(True)
        logger.info("Online mention notifications enabled")
        await event.answer("✅ Уведомления включены")
        await mention_online_menu(event)

    @bot.on(events.CallbackQuery(data=b"online_mention_off"))
    async def online_mention_disable(event):
        """Disable online mention notifications."""
        if not await _has_access(event):
            return

        Settings.set_online_mention_enabled(False)
        logger.info("Online mention notifications disabled")
        await event.answer("🔴 Уведомления выключены")
        await mention_online_menu(event)

    # Store users waiting to input delay
    _pending_delay_edit: set[int] = set()

    @bot.on(events.CallbackQuery(data=b"online_delay_edit"))
    async def online_delay_edit_start(event):
        """Start editing online mention delay."""
        if not await _has_access(event):
            return

        _pending_delay_edit.add(event.sender_id)
        current = Settings.get_online_mention_delay()

        await event.edit(
            f"⏱ **Настройка задержки**\n\n"
            f"Текущая задержка: {current} мин\n\n"
            f"Отправьте число от 0 до 60:\n"
            f"• `0` — без задержки (сразу)\n"
            f"• `5` — 5 минут\n"
            f"• `10` — 10 минут (по умолчанию)",
            buttons=[[Button.inline("❌ Отмена", b"online_delay_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"online_delay_cancel"))
    async def online_delay_cancel(event):
        """Cancel delay editing."""
        if not await _has_access(event):
            return

        _pending_delay_edit.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await mention_online_menu(event)

    # =========================================================================
    # VIP Menu
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"mention_vip"))
    async def mention_vip_menu(event):
        """Show VIP management menu."""
        if not await _has_access(event):
            return

        users = VipList.get_users()
        chats = VipList.get_chats()

        text = (
            "⭐ **Приоритетные**\n\n"
            "Упоминания от приоритетных пользователей\n"
            "и в приоритетных чатах всегда срочные.\n\n"
            f"👤 Пользователей: {len(users)}\n"
            f"💬 Чатов: {len(chats)}"
        )

        await event.edit(text, buttons=get_vip_keyboard())

    @bot.on(events.CallbackQuery(data=b"vip_users"))
    async def vip_users_menu(event):
        """Show VIP users list."""
        if not await _has_access(event):
            return

        users = VipList().select(SQL().WHERE('item_type', '=', 'user')) or []

        if users:
            text = "👤 **Приоритетные пользователи**\n\n"
            for u in users[:10]:
                display = u.display_name if u.display_name else f"@{u.item_id}"
                text += f"• {display}\n"
        else:
            text = "👤 **Приоритетные пользователи**\n\nСписок пуст."

        await event.edit(text, buttons=get_vip_users_keyboard())

    @bot.on(events.CallbackQuery(data=b"vip_chats"))
    async def vip_chats_menu(event):
        """Show VIP chats list."""
        if not await _has_access(event):
            return

        chats = VipList().select(SQL().WHERE('item_type', '=', 'chat')) or []

        if chats:
            text = "💬 **Приоритетные чаты**\n\n"
            for c in chats[:10]:
                display = c.display_name if c.display_name else f"ID: {c.item_id}"
                text += f"• {display}\n"
        else:
            text = "💬 **Приоритетные чаты**\n\nСписок пуст."

        await event.edit(text, buttons=get_vip_chats_keyboard())

    # Store users waiting to input VIP username/chat
    _pending_vip_user: set[int] = set()
    _pending_vip_chat: set[int] = set()
    _pending_productivity_time: set[int] = set()

    @bot.on(events.CallbackQuery(data=b"vip_add_user"))
    async def vip_add_user_start(event):
        """Start adding VIP user."""
        if not await _has_access(event):
            return

        _pending_vip_user.add(event.sender_id)

        await event.edit(
            "👤 **Добавить пользователя**\n\n"
            "Отправьте username пользователя\n"
            "(с @ или без):",
            buttons=[[Button.inline("❌ Отмена", b"vip_add_user_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"vip_add_user_cancel"))
    async def vip_add_user_cancel(event):
        """Cancel adding VIP user."""
        if not await _has_access(event):
            return

        _pending_vip_user.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await vip_users_menu(event)

    @bot.on(events.CallbackQuery(data=b"vip_add_chat"))
    async def vip_add_chat_start(event):
        """Start adding VIP chat."""
        if not await _has_access(event):
            return

        _pending_vip_chat.add(event.sender_id)

        await event.edit(
            "💬 **Добавить чат**\n\n"
            "Перешлите любое сообщение из чата,\n"
            "который хотите добавить.\n\n"
            "Или отправьте ID чата вручную.",
            buttons=[[Button.inline("❌ Отмена", b"vip_add_chat_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"vip_add_chat_cancel"))
    async def vip_add_chat_cancel(event):
        """Cancel adding VIP chat."""
        if not await _has_access(event):
            return

        _pending_vip_chat.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await vip_chats_menu(event)

    @bot.on(events.CallbackQuery(pattern=rb"vip_del:(\d+)"))
    async def vip_delete(event):
        """Delete VIP entry."""
        if not await _has_access(event):
            return

        entry_id = int(event.pattern_match.group(1))
        if VipList.remove_by_id(entry_id):
            logger.info(f"VIP entry #{entry_id} deleted")
            await event.answer("✅ Удалено")
        else:
            await event.answer("❌ Не найдено", alert=True)

        # Refresh the appropriate menu
        await mention_vip_menu(event)

    # =========================================================================
    # Productivity Summary Menu
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"productivity"))
    async def productivity_menu(event):
        """Show productivity summary configuration menu."""
        if not await _has_access(event):
            return

        # Personal account doesn't have access to productivity (requires user client)
        if await _is_personal(event):
            await event.answer("❌ Недоступно", alert=True)
            return

        is_enabled = Settings.is_productivity_summary_enabled()
        summary_time = Settings.get_productivity_summary_time()

        status = "✅ включена" if is_enabled else "❌ выключена"
        time_info = f"⏰ Время: {summary_time}" if summary_time else "⏰ Время не настроено"

        text = (
            "📊 **Сводка продуктивности**\n\n"
            "Ежедневный отчёт о ваших переписках:\n"
            "• Сколько чатов и сообщений\n"
            "• Краткое саммари по каждому чату\n"
            "• Общие выводы о дне\n\n"
            f"Автоотправка: {status}\n"
            f"{time_info}"
        )

        await event.edit(text, buttons=get_productivity_keyboard())

    @bot.on(events.CallbackQuery(data=b"productivity_now"))
    async def productivity_generate_now(event):
        """Generate productivity summary right now."""
        if not await _has_access(event):
            return

        await event.answer("⏳ Генерирую сводку...", alert=False)

        try:
            from services.productivity_service import get_productivity_service
            from services.yandex_gpt_service import get_yandex_gpt_service

            service = get_productivity_service()
            gpt_service = get_yandex_gpt_service()

            # Get extra chat IDs for muted chats user wants to include
            # Combine permanent extra chats + temporary chats (from mentions/replies)
            extra_chat_ids = Settings.get_productivity_extra_chats()
            temp_chat_ids = Settings.get_productivity_temp_chats()
            all_extra_chats = list(set(extra_chat_ids + temp_chat_ids))

            # Collect messages (this may take a while)
            daily = await service.collect_daily_messages(
                _user_client, extra_chat_ids=all_extra_chats
            )
            summary_text = await service.generate_daily_summary(daily, gpt_service)

            # Clear temporary chats after summary is generated
            Settings.clear_productivity_temp_chats()
            if temp_chat_ids:
                logger.info(f"Cleared {len(temp_chat_ids)} temporary productivity chats")

            # Send as a new message
            await event.respond(summary_text)
            logger.info("Productivity summary generated on demand via bot")

        except Exception as e:
            logger.error(f"Failed to generate productivity summary: {e}")
            await event.respond(f"❌ Ошибка генерации сводки:\n{e}")

    @bot.on(events.CallbackQuery(data=b"productivity_on"))
    async def productivity_enable(event):
        """Enable automatic productivity summary."""
        if not await _has_access(event):
            return

        # Check if time is set
        summary_time = Settings.get_productivity_summary_time()
        if not summary_time:
            await event.answer("⚠️ Сначала настройте время", alert=True)
            return

        Settings.set_productivity_summary_enabled(True)
        logger.info("Productivity summary enabled via bot")
        await event.answer("✅ Автоотправка включена")
        await productivity_menu(event)

    @bot.on(events.CallbackQuery(data=b"productivity_off"))
    async def productivity_disable(event):
        """Disable automatic productivity summary."""
        if not await _has_access(event):
            return

        Settings.set_productivity_summary_enabled(False)
        logger.info("Productivity summary disabled via bot")
        await event.answer("🔴 Автоотправка выключена")
        await productivity_menu(event)

    @bot.on(events.CallbackQuery(data=b"productivity_time"))
    async def productivity_time_start(event):
        """Start setting productivity summary time."""
        if not await _has_access(event):
            return

        _pending_productivity_time.add(event.sender_id)

        current = Settings.get_productivity_summary_time()
        hint = f"\n\nТекущее время: {current}" if current else ""

        await event.edit(
            f"⏰ **Настройка времени**\n\n"
            f"Отправьте время для ежедневной сводки\n"
            f"в формате **ЧЧ:ММ** (например, 19:00).{hint}",
            buttons=[[Button.inline("❌ Отмена", b"productivity_time_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"productivity_time_cancel"))
    async def productivity_time_cancel(event):
        """Cancel time setting."""
        if not await _has_access(event):
            return

        _pending_productivity_time.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await productivity_menu(event)

    # State for pending chat addition
    _pending_productivity_chat: set[int] = set()

    @bot.on(events.CallbackQuery(data=b"productivity_chats"))
    async def productivity_chats_menu(event):
        """Show productivity extra chats menu."""
        if not await _has_access(event):
            return

        extra_chats = Settings.get_productivity_extra_chats()

        lines = [
            "➕ **Дополнительные чаты**\n",
            "По умолчанию учитываются только незамьюченные чаты.",
            "Здесь можно добавить замьюченные чаты, которые тоже нужно включить.\n"
        ]

        if extra_chats:
            lines.append("**Добавленные чаты:**")
            for chat_id in extra_chats[:10]:
                try:
                    entity = await _user_client.get_entity(chat_id)
                    title = getattr(entity, 'title', None) or getattr(entity, 'first_name', str(chat_id))
                    lines.append(f"• {title}")
                except Exception:
                    lines.append(f"• ID: {chat_id}")
        else:
            lines.append("_Дополнительные чаты не добавлены_")

        buttons = [
            [Button.inline("➕ Добавить чат", b"productivity_chat_add")],
        ]
        if extra_chats:
            buttons.append([Button.inline("🗑 Очистить все", b"productivity_chat_clear")])
        buttons.append([Button.inline("« Назад", b"productivity")])

        await event.edit("\n".join(lines), buttons=buttons)

    @bot.on(events.CallbackQuery(data=b"productivity_chat_add"))
    async def productivity_chat_add_start(event):
        """Start adding productivity chat."""
        if not await _has_access(event):
            return

        _pending_productivity_chat.add(event.sender_id)

        await event.edit(
            "➕ **Добавить чат**\n\n"
            "Перешлите любое сообщение из чата,\n"
            "который хотите добавить в сводку.\n\n"
            "Или отправьте ID чата вручную.",
            buttons=[[Button.inline("❌ Отмена", b"productivity_chat_add_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"productivity_chat_add_cancel"))
    async def productivity_chat_add_cancel(event):
        """Cancel adding productivity chat."""
        if not await _has_access(event):
            return

        _pending_productivity_chat.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await productivity_chats_menu(event)

    @bot.on(events.CallbackQuery(data=b"productivity_chat_clear"))
    async def productivity_chat_clear(event):
        """Clear all productivity extra chats."""
        if not await _has_access(event):
            return

        Settings.set('productivity_extra_chats', '')
        logger.info("Productivity extra chats cleared")
        await event.answer("✅ Список очищен")
        await productivity_chats_menu(event)

    # Handle VIP input in handle_private_message - need to add check there
