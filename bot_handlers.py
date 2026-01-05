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
# Regex pattern for parsing date range like "25.12-05.01" or "25.12.2024-05.01.2025"
DATE_RANGE_PATTERN = re.compile(r'^(\d{1,2}\.\d{1,2}(?:\.\d{4})?)\s*[-–—]\s*(\d{1,2}\.\d{1,2}(?:\.\d{4})?)$')

from sqlitemodel import SQL

from config import config
from logging_config import logger
from models import Reply, Settings, Schedule, PRIORITY_REST, PRIORITY_MORNING, PRIORITY_EVENING, PRIORITY_WEEKENDS, PRIORITY_WORK, PRIORITY_MEETING, PRIORITY_OVERRIDE


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


def get_main_menu_keyboard():
    """Main menu keyboard."""
    return [
        [Button.inline("📊 Статус", b"status")],
        [Button.inline("📝 Автоответы", b"replies"), Button.inline("📅 Расписание", b"schedule")],
        [Button.inline("📞 Встречи", b"meeting"), Button.inline("⚙️ Настройки", b"settings")],
    ]


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

    # Priority/type name
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
    toggle_text = "🔴 Выключить" if is_enabled else "🟢 Включить"
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


def get_settings_keyboard():
    """Settings keyboard."""
    return [
        [Button.inline("❌ Отключить автоответчик", b"autoreply_off_confirm")],
        [Button.inline("🚪 Выйти из аккаунта", b"logout_confirm")],
        [Button.inline("« Назад", b"main")],
    ]


def get_confirm_keyboard(action: str):
    """Confirmation keyboard."""
    return [
        [Button.inline("✅ Да", f"confirm_{action}".encode()),
         Button.inline("❌ Нет", b"main")],
    ]


def get_replies_keyboard():
    """Replies management keyboard."""
    return [
        [Button.inline("📋 Список автоответов", b"replies_list")],
        [Button.inline("➕ Добавить", b"reply_add")],
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
        if not await _is_owner(event):
            await event.respond("⛔ Доступ запрещён. Этот бот только для владельца.")
            return

        await event.respond(
            "🤖 **Панель управления автоответчиком**\n\n"
            "Выберите раздел:",
            buttons=get_main_menu_keyboard()
        )

    @bot.on(events.CallbackQuery(data=b"main"))
    async def main_menu(event):
        """Return to main menu."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        # Delete user client messages when returning to main menu
        await _delete_emoji_list_message()
        await _delete_schedule_list_message()

        await event.edit(
            "🤖 **Панель управления автоответчиком**\n\n"
            "Выберите раздел:",
            buttons=get_main_menu_keyboard()
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        # Clear add mode when returning to menu
        _pending_reply_add_mode.discard(event.sender_id)

        # Clean up user client messages when switching sections
        await _delete_emoji_list_message()
        await _delete_schedule_list_message()

        text = (
            "📝 **Автоответы**\n\n"
            "Для настройки автоответа отправьте боту:\n"
            "1. Сообщение с эмодзи-статусом\n"
            "2. Затем текст автоответа\n\n"
            "Или используйте список для просмотра."
        )

        await event.edit(text, buttons=get_replies_keyboard())

    @bot.on(events.CallbackQuery(data=b"replies_list"))
    async def replies_list(event):
        """List all configured replies as buttons."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        replies = Reply().select(SQL())

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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        # Clean up other section's message
        await _delete_emoji_list_message()

        is_enabled = Schedule.is_scheduling_enabled()
        status = "✅ включено" if is_enabled else "❌ выключено"

        text = (
            f"📅 **Расписание эмодзи-статуса**\n\n"
            f"Статус: {status}\n\n"
            "Управление расписанием:"
        )

        await event.edit(text, buttons=get_schedule_keyboard())

    @bot.on(events.CallbackQuery(data=b"schedule_list"))
    async def schedule_list_handler(event):
        """List all schedule rules with custom emoji display."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
                    text += f"\n{title}\n"
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
                add_section("🔄 Постоянные:", regular)

                # Footer
                text += "\n\n────────────────────"
                text += "\n💡 /schedule del <ID>"

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

                # Bot shows only keyboard
                await event.edit("⬆️ Список правил выше", buttons=get_schedule_keyboard())
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
        lines.append("💡 `/schedule del <ID>`")

        await event.edit('\n'.join(lines), buttons=get_schedule_keyboard())

    @bot.on(events.CallbackQuery(data=b"schedule_on"))
    async def schedule_enable(event):
        """Enable scheduling."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        Schedule.set_scheduling_enabled(True)
        logger.info("Scheduling enabled via bot")
        await event.answer("✅ Расписание включено")

        # Refresh menu
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_off"))
    async def schedule_disable(event):
        """Disable scheduling."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        Schedule.set_scheduling_enabled(False)
        logger.info("Scheduling disabled via bot")
        await event.answer("❌ Расписание выключено")

        # Refresh menu
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_clear_confirm"))
    async def schedule_clear_confirm(event):
        """Confirm schedule clear."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        await event.edit(
            "⚠️ **Удалить все правила расписания?**\n\n"
            "Это действие нельзя отменить.",
            buttons=get_confirm_keyboard("schedule_clear")
        )

    @bot.on(events.CallbackQuery(data=b"confirm_schedule_clear"))
    async def schedule_clear(event):
        """Clear all schedule rules."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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

    @bot.on(events.CallbackQuery(data=b"schedule_work_edit"))
    async def schedule_work_edit_start(event):
        """Start editing work schedule time."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        _pending_work_time_edit.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_morning"))
    async def schedule_morning_start(event):
        """Start setting morning emoji."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        _pending_morning_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_evening"))
    async def schedule_evening_start(event):
        """Start setting evening emoji."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        _pending_evening_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_weekend"))
    async def schedule_weekend_start(event):
        """Start setting weekend emoji."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        _pending_weekend_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_rest"))
    async def schedule_rest_start(event):
        """Start setting rest/fallback emoji."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        _pending_rest_emoji.discard(event.sender_id)
        await event.answer("❌ Отменено")
        await schedule_menu(event)

    @bot.on(events.CallbackQuery(data=b"schedule_override_add"))
    async def schedule_override_add_start(event):
        """Start adding an override schedule."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        _pending_override_dates.add(event.sender_id)

        await event.edit(
            "➕ **Добавить временное правило**\n\n"
            "Используется для отпуска, больничного и т.д.\n\n"
            "Отправьте даты в формате:\n"
            "`25.12-05.01` или `25.12.2024-05.01.2025`",
            buttons=[[Button.inline("❌ Отмена", b"schedule_override_cancel")]]
        )

    @bot.on(events.CallbackQuery(data=b"schedule_override_cancel"))
    async def schedule_override_cancel(event):
        """Cancel override creation."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        Schedule.end_meeting()
        logger.info("Meeting ended via bot")

        await event.answer("🔴 Звонок завершён")
        await meeting_menu(event)

    # =========================================================================
    # Settings
    # =========================================================================

    @bot.on(events.CallbackQuery(data=b"settings"))
    async def settings_menu(event):
        """Show settings menu."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        settings_chat_id = Settings.get_settings_chat_id()

        text = "⚙️ **Настройки**\n\n"

        if settings_chat_id:
            text += f"Настроечный чат: `{settings_chat_id}`\n"
            text += "Автоответчик: ✅ активен"
        else:
            text += "Автоответчик: ❌ не настроен\n"
            text += "Отправьте `/autoreply-settings` в любом чате для настройки."

        await event.edit(text, buttons=get_settings_keyboard())

    @bot.on(events.CallbackQuery(data=b"autoreply_off_confirm"))
    async def autoreply_off_confirm(event):
        """Confirm autoreply disable."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        await event.edit(
            "⚠️ **Отключить автоответчик?**\n\n"
            "Вам нужно будет заново отправить `/autoreply-settings` для включения.",
            buttons=get_confirm_keyboard("autoreply_off")
        )

    @bot.on(events.CallbackQuery(data=b"confirm_autoreply_off"))
    async def autoreply_off(event):
        """Disable autoreply."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        Settings.set_settings_chat_id(None)
        logger.info("Autoreply disabled via bot")

        await event.answer("❌ Автоответчик отключён")
        await event.edit(
            "⚙️ **Настройки**\n\n"
            "Автоответчик: ❌ отключён\n\n"
            "Отправьте `/autoreply-settings` в любом чате для включения.",
            buttons=get_settings_keyboard()
        )

    @bot.on(events.CallbackQuery(data=b"logout_confirm"))
    async def logout_confirm(event):
        """Confirm logout."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
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
    # Text message handlers for setting replies and schedule
    # =========================================================================

    # Store pending reply setup: {user_id: emoji_id}
    _pending_reply_setup: dict[int, int] = {}
    # Store users in "add mode" waiting for emoji
    _pending_reply_add_mode: set[int] = set()
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
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        # Enable add mode for this user
        _pending_reply_add_mode.add(event.sender_id)

        await event.edit(
            "➕ **Добавить автоответ**\n\n"
            "Отправьте сообщение с эмодзи-статусом,\n"
            "для которого хотите настроить автоответ.",
            buttons=[[Button.inline("❌ Отмена", b"replies")]]
        )

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
        # Reply/Schedule setup flow (only for authorized owner)
        # =====================================================================
        if not await _is_owner(event):
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

        # Check if user is entering override dates
        if event.sender_id in _pending_override_dates:
            text = event.message.text.strip() if event.message.text else ""
            match = DATE_RANGE_PATTERN.match(text)

            if not match:
                await event.respond(
                    "❌ Неверный формат дат.\n\n"
                    "Используйте: `25.12-05.01` или `25.12.2024-05.01.2025`",
                    buttons=[[Button.inline("❌ Отмена", b"schedule_override_cancel")]]
                )
                return

            date_start = match.group(1)
            date_end = match.group(2)

            # Move to emoji input stage
            _pending_override_dates.discard(event.sender_id)
            _pending_override_emoji[event.sender_id] = (date_start, date_end)

            await event.respond(
                f"📅 Даты: **{date_start}** — **{date_end}**\n\n"
                f"Теперь отправьте эмодзи для этого периода:",
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
            date_start, date_end = _pending_override_emoji.pop(event.sender_id)

            Schedule.create_override(emoji_id, date_start, date_end)
            logger.info(f"Override created: {date_start}-{date_end} with emoji {emoji_id}")

            await event.respond(
                f"✅ Временное правило создано!\n\n"
                f"📅 **{date_start}** — **{date_end}**",
                buttons=get_schedule_keyboard()
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
        if not await _is_owner(event):
            return

        # Clear both add mode and pending setup
        _pending_reply_add_mode.discard(event.sender_id)
        if event.sender_id in _pending_reply_setup:
            del _pending_reply_setup[event.sender_id]

        await event.edit(
            "❌ Настройка автоответа отменена.",
            buttons=get_main_menu_keyboard()
        )
