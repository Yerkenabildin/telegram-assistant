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
from telethon.tl.types import MessageEntityCustomEmoji, DocumentAttributeCustomEmoji
from telethon.tl.functions.messages import GetCustomEmojiDocumentsRequest

from sqlitemodel import SQL

from config import config
from logging_config import logger
from models import Reply, Settings, Schedule


# Store owner user ID (set when user client is authorized)
_owner_id: int | None = None
_owner_username: str | None = None
_user_client = None  # User client for sending custom emojis
_bot_username: str | None = None  # Bot username for user client to send messages
_emoji_list_message_id: int | None = None  # Message ID of emoji list from user client


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

        # Delete emoji list message when returning to main menu
        await _delete_emoji_list_message()

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

        # Delete emoji list message when returning to menu
        await _delete_emoji_list_message()

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

    @bot.on(events.NewMessage(func=lambda e: e.is_private))
    async def handle_private_message(event):
        """Handle private messages for reply setup."""
        if not await _is_owner(event):
            return

        # Skip commands
        if event.message.text and event.message.text.startswith('/'):
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

    @bot.on(events.CallbackQuery(data=b"cancel_reply_setup"))
    async def cancel_reply_setup(event):
        """Cancel reply setup."""
        if not await _is_owner(event):
            return

        if event.sender_id in _pending_reply_setup:
            del _pending_reply_setup[event.sender_id]

        await event.edit(
            "❌ Настройка автоответа отменена.",
            buttons=get_main_menu_keyboard()
        )
