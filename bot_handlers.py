"""
Telegram Bot interface for controlling the auto-responder.

Provides inline keyboard interface for managing:
- Auto-replies
- Schedule
- Meetings
- Settings
"""
from __future__ import annotations

from telethon import events, Button
from telethon.tl.types import MessageEntityCustomEmoji

from sqlitemodel import SQL

from config import config
from logging_config import logger
from models import Reply, Settings, Schedule


# Store owner user ID (set when user client is authorized)
_owner_id: int | None = None
_owner_username: str | None = None


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


# =============================================================================
# Keyboard Layouts
# =============================================================================

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


def get_schedule_keyboard():
    """Schedule management keyboard."""
    is_enabled = Schedule.is_scheduling_enabled()
    toggle_text = "🔴 Выключить" if is_enabled else "🟢 Включить"
    toggle_data = b"schedule_off" if is_enabled else b"schedule_on"

    return [
        [Button.inline("📋 Список правил", b"schedule_list")],
        [Button.inline(toggle_text, toggle_data)],
        [Button.inline("🗑 Очистить всё", b"schedule_clear_confirm")],
        [Button.inline("« Назад", b"main")],
    ]


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
        [Button.inline("« Назад", b"main")],
    ]


def get_reply_view_keyboard(emoji_id: str):
    """Keyboard for viewing a specific reply."""
    return [
        [Button.inline("✏️ Изменить", f"reply_edit:{emoji_id}".encode())],
        [Button.inline("🗑 Удалить", f"reply_del_confirm:{emoji_id}".encode())],
        [Button.inline("« Назад", b"replies_list")],
    ]


def get_reply_edit_confirm_keyboard(emoji_id: str):
    """Keyboard for confirming reply edit."""
    return [
        [Button.inline("✅ Да", f"reply_edit_yes:{emoji_id}".encode()),
         Button.inline("❌ Нет", f"reply_view:{emoji_id}".encode())],
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

def register_bot_handlers(bot):
    """
    Register all bot event handlers.

    Args:
        bot: Telethon bot client instance
    """

    @bot.on(events.NewMessage(pattern=r"^/start"))
    async def start_handler(event):
        """Handle /start command - show main menu."""
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

        await event.edit(
            "🤖 **Панель управления автоответчиком**\n\n"
            "Выберите раздел:",
            buttons=get_main_menu_keyboard()
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

        # Build buttons for each reply (limit to 8 for UI)
        buttons = []
        for r in replies[:8]:
            emoji_id = r.emoji
            # Button text: emoji placeholder + ID
            btn_text = f"📝 {emoji_id}"
            buttons.append([Button.inline(btn_text, f"reply_view:{emoji_id}".encode())])

        if len(replies) > 8:
            buttons.append([Button.inline(f"... ещё {len(replies) - 8}", b"replies_list")])

        buttons.append([Button.inline("« Назад", b"replies")])

        await event.edit("📝 **Выберите автоответ:**", buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=b"reply_view:(.+)"))
    async def reply_view(event):
        """View a specific reply."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        emoji_id = event.pattern_match.group(1).decode()
        reply = Reply.get_by_emoji(emoji_id)

        if not reply:
            await event.answer("❌ Автоответ не найден", alert=True)
            return

        # Get message text
        msg = reply.message
        text_preview = msg.text[:200] if msg and msg.text else "(нет текста)"
        if msg and msg.text and len(msg.text) > 200:
            text_preview += "..."

        await event.edit(
            f"📝 **Автоответ**\n\n"
            f"**Emoji ID:** `{emoji_id}`\n\n"
            f"**Текст:**\n{text_preview}",
            buttons=get_reply_view_keyboard(emoji_id)
        )

    @bot.on(events.CallbackQuery(pattern=b"reply_edit:(.+)"))
    async def reply_edit_start(event):
        """Start editing a reply - ask for new text."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        emoji_id = event.pattern_match.group(1).decode()

        # Store pending edit state
        _pending_reply_edit[event.sender_id] = {'emoji_id': emoji_id, 'message': None}

        await event.edit(
            f"✏️ **Редактирование автоответа**\n\n"
            f"**Emoji ID:** `{emoji_id}`\n\n"
            f"Отправьте новый текст автоответа:",
            buttons=[[Button.inline("❌ Отмена", f"reply_view:{emoji_id}".encode())]]
        )

    @bot.on(events.CallbackQuery(pattern=b"reply_edit_yes:(.+)"))
    async def reply_edit_confirm(event):
        """Confirm and save the edited reply."""
        if not await _is_owner(event):
            await event.answer("⛔ Доступ запрещён", alert=True)
            return

        emoji_id = event.pattern_match.group(1).decode()

        # Get pending edit
        pending = _pending_reply_edit.get(event.sender_id)
        if not pending or pending['emoji_id'] != emoji_id or not pending['message']:
            await event.answer("❌ Ошибка: нет данных для сохранения", alert=True)
            return

        # Save the reply
        Reply.create(emoji_id, pending['message'])
        del _pending_reply_edit[event.sender_id]
        logger.info(f"Reply updated for emoji {emoji_id} via bot")

        await event.answer("✅ Автоответ сохранён")

        # Show updated reply
        reply = Reply.get_by_emoji(emoji_id)
        msg = reply.message
        text_preview = msg.text[:200] if msg and msg.text else "(нет текста)"
        if msg and msg.text and len(msg.text) > 200:
            text_preview += "..."

        await event.edit(
            f"📝 **Автоответ**\n\n"
            f"**Emoji ID:** `{emoji_id}`\n\n"
            f"**Текст:**\n{text_preview}",
            buttons=get_reply_view_keyboard(emoji_id)
        )

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
        """List all schedule rules."""
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

        lines = ["📅 **Правила расписания:**\n"]

        overrides = [s for s in schedules if s.is_override()]
        regular = [s for s in schedules if not s.is_override()]

        if overrides:
            lines.append("**🔴 Перекрытия:**")
            for s in overrides:
                date_info = s.get_date_display()
                expired = " ⚠️" if s.is_expired() else ""
                lines.append(f"• #{s.id} {date_info}{expired}")
            lines.append("")

        if regular:
            lines.append("**📋 Обычные:**")
            for s in regular:
                lines.append(f"• #{s.id} {s.get_days_display()} {s.time_start}-{s.time_end}")

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

    # =========================================================================
    # Text message handlers for setting replies
    # =========================================================================

    # Store pending reply setup: {user_id: emoji_id}
    _pending_reply_setup: dict[int, int] = {}
    # Store pending reply edit: {user_id: {'emoji_id': str, 'message': Message}}
    _pending_reply_edit: dict[int, dict] = {}

    @bot.on(events.NewMessage(func=lambda e: e.is_private))
    async def handle_private_message(event):
        """Handle private messages for reply setup and editing."""
        if not await _is_owner(event):
            return

        # Skip commands
        if event.message.text and event.message.text.startswith('/'):
            return

        # Check if we're editing an existing reply
        if event.sender_id in _pending_reply_edit:
            pending = _pending_reply_edit[event.sender_id]
            emoji_id = pending['emoji_id']
            pending['message'] = event.message

            # Preview and ask for confirmation
            text_preview = event.message.text[:200] if event.message.text else "(нет текста)"
            if event.message.text and len(event.message.text) > 200:
                text_preview += "..."

            await event.respond(
                f"✏️ **Подтверждение изменения**\n\n"
                f"**Emoji ID:** `{emoji_id}`\n\n"
                f"**Новый текст:**\n{text_preview}\n\n"
                f"Сохранить изменения?",
                buttons=get_reply_edit_confirm_keyboard(emoji_id)
            )
            return

        # Check if message contains custom emoji (new reply setup)
        entities = event.message.entities or []
        custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

        if custom_emojis:
            # User sent emoji - store it for reply setup
            emoji_id = custom_emojis[0].document_id
            _pending_reply_setup[event.sender_id] = emoji_id

            await event.respond(
                f"📝 Эмодзи выбран: `{emoji_id}`\n\n"
                "Теперь отправьте текст автоответа для этого статуса.\n"
                "Или нажмите кнопку для отмены.",
                buttons=[[Button.inline("❌ Отмена", b"cancel_reply_setup")]]
            )
            return

        # Check if we have pending emoji (new reply)
        if event.sender_id in _pending_reply_setup:
            emoji_id = _pending_reply_setup.pop(event.sender_id)

            # Save the reply
            Reply.create(emoji_id, event.message)
            logger.info(f"Reply set for emoji {emoji_id} via bot")

            await event.respond(
                f"✅ Автоответ сохранён!\n\n"
                f"Emoji ID: `{emoji_id}`",
                buttons=get_main_menu_keyboard()
            )

    @bot.on(events.CallbackQuery(data=b"cancel_reply_setup"))
    async def cancel_reply_setup(event):
        """Cancel reply setup."""
        if not await _is_owner(event):
            return

        if event.sender_id in _pending_reply_setup:
            del _pending_reply_setup[event.sender_id]
        if event.sender_id in _pending_reply_edit:
            del _pending_reply_edit[event.sender_id]

        await event.edit(
            "❌ Настройка автоответа отменена.",
            buttons=get_main_menu_keyboard()
        )
