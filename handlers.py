"""
Telegram event handlers for auto-reply bot.

Handles incoming/outgoing messages and commands.
"""
from telethon import events
from telethon.errors import ReactionInvalidError
from telethon.tl import types
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import MessageEntityCustomEmoji

from config import config
from logging_config import logger
from models import Reply, Settings, Schedule, parse_days, parse_time_range, DAY_DISPLAY
from services.autoreply_service import AutoReplyService
from services.notification_service import NotificationService

# Services initialized once
_autoreply_service = AutoReplyService(cooldown_minutes=config.autoreply_cooldown_minutes)
_notification_service = NotificationService(
    personal_tg_login=config.personal_tg_login,
    available_emoji_id=config.available_emoji_id,
    webhook_url=config.asap_webhook_url,
    webhook_timeout=config.webhook_timeout_seconds
)


def register_handlers(client):
    """
    Register all Telegram event handlers on the client.

    Args:
        client: Telethon client instance
    """

    @client.on(events.NewMessage(outgoing=True))
    async def debug_outgoing(event):
        """Log all outgoing messages for debugging."""
        logger.debug(f"Outgoing: '{event.message.text}' in chat {event.chat_id}")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autoreply-settings\s*$"))
    async def select_settings_chat(event):
        """Handle /autoreply-settings command to set the settings chat."""
        chat_id = event.chat.id
        Settings.set_settings_chat_id(chat_id)
        logger.info(f"Settings chat set to: {chat_id}")

        await _send_reaction(client, event, '\u2705')  # ✅

        await client.send_message(
            entity=event.input_chat,
            message=(
                "✅ Этот чат выбран для настройки автоответчика.\n\n"
                "**Автоответы:**\n"
                "• `/set` — задать автоответ для текущего статуса\n"
                "• `/set_for <эмодзи>` — задать автоответ для эмодзи\n"
                "• `/autoreply-off` — отключить автоответчик\n\n"
                "**Расписание статусов:**\n"
                "• `/schedule` — справка по расписанию\n"
                "• `/schedule work <эмодзи>` — ПН-ПТ 09:00-18:00\n"
                "• `/schedule rest <эмодзи>` — остальное время"
            )
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autoreply-off\s*$"))
    async def disable_autoreply(event):
        """Handle /autoreply-off command to disable autoreply."""
        settings_chat_id = Settings.get_settings_chat_id()
        chat_id = event.chat.id

        if not _autoreply_service.is_settings_chat(chat_id, settings_chat_id):
            return

        Settings.set_settings_chat_id(None)
        logger.info("Autoreply disabled")

        await _send_reaction(client, event, '\u274c')  # ❌

        await client.send_message(
            entity=event.input_chat,
            message="❌ Автоответчик отключен. Используйте /autoreply-settings в любом чате, чтобы снова включить."
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/set_for\s+.*"))
    async def setup_response(event):
        """Handle /set_for command to set reply for specific emoji."""
        settings_chat_id = Settings.get_settings_chat_id()
        chat_id = event.chat.id

        if not _autoreply_service.is_settings_chat(chat_id, settings_chat_id):
            return

        if not event.reply_to:
            await client.send_message(
                entity=event.input_chat,
                message="Команда должна быть ответом на сообщение"
            )
            return

        msg_id = event.reply_to.reply_to_msg_id
        message = await client.get_messages(event.input_chat, ids=msg_id)

        entities = event.message.entities or []
        custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

        if len(custom_emojis) != 1:
            await client.send_message(
                entity=event.input_chat,
                reply_to=msg_id,
                message=(
                    f"Нужен 1 кастомный эмодзи Telegram (премиум), найдено: {len(custom_emojis)}. "
                    "Обычные эмодзи (🎄) не поддерживаются — используйте эмодзи из панели премиум-стикеров."
                )
            )
            return

        emoji = custom_emojis[0]
        Reply.create(emoji.document_id, message)
        logger.info(f"Reply set for emoji: {emoji.document_id}")

        await _send_reaction(client, event, '\U0001fae1')  # 🫡

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/set\s*$"))
    async def setup_response_current_status(event):
        """Handle /set command to set reply for current emoji status."""
        settings_chat_id = Settings.get_settings_chat_id()
        chat_id = event.chat.id

        if not _autoreply_service.is_settings_chat(chat_id, settings_chat_id):
            return

        if not event.reply_to:
            await client.send_message(
                entity=event.input_chat,
                message="Команда должна быть ответом на сообщение"
            )
            return

        me = await client.get_me()
        if not me.emoji_status:
            await client.send_message(
                entity=event.input_chat,
                message="❌ У вас не установлен эмодзи-статус. Установите статус в настройках Telegram и попробуйте снова."
            )
            return

        msg_id = event.reply_to.reply_to_msg_id
        message = await client.get_messages(event.input_chat, ids=msg_id)

        emoji_id = me.emoji_status.document_id
        Reply.create(emoji_id, message)
        logger.info(f"Reply set for current status emoji: {emoji_id}")

        await _send_reaction(client, event, '\U0001fae1')  # 🫡

        await client.send_message(
            entity=event.input_chat,
            message=f"✅ Автоответ установлен для текущего статуса (ID: {emoji_id})"
        )

    @client.on(events.NewMessage(incoming=True, pattern=".*[Aa][Ss][Aa][Pp].*"))
    async def asap_handler(event):
        """Handle incoming messages with ASAP keyword."""
        if not event.is_private:
            return

        me = await client.get_me()
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

        if not _notification_service.should_notify_asap(
            message_text=event.message.text or '',
            is_private=event.is_private,
            emoji_status_id=emoji_status_id
        ):
            return

        sender = await event.get_sender()
        sender_username = getattr(sender, 'username', None)
        sender_id = getattr(sender, 'id', 0)

        # Send notification to personal account
        notification_message = _notification_service.format_asap_message(sender_username, sender_id)
        await client.send_message(
            config.personal_tg_login,
            notification_message,
            formatting_entities=[MessageEntityCustomEmoji(offset=0, length=2, document_id=5379748062124056162)]
        )
        logger.info(f"ASAP notification sent for message from {sender_username or sender_id}")

        # Call webhook if configured
        if config.asap_webhook_url:
            await _notification_service.call_webhook(
                sender_username=sender_username,
                sender_id=sender_id,
                message_text=event.message.text or ''
            )

        await _send_reaction(client, event, '\U0001fae1')  # 🫡

    @client.on(events.NewMessage(incoming=True))
    async def new_messages(event):
        """Handle incoming messages for auto-reply."""
        if not event.is_private:
            return

        me = await client.get_me()
        emoji_status_id = me.emoji_status.document_id if me.emoji_status else None

        reply = Reply.get_by_emoji(emoji_status_id) if emoji_status_id else None

        sender = await event.get_sender()
        sender_username = getattr(sender, 'username', None)
        sender_id = getattr(sender, 'id', 0)

        # Use username or ID for message lookup
        user_identifier = sender_username or sender_id
        if not user_identifier:
            logger.warning("Could not identify sender, skipping auto-reply")
            return

        # Get last messages for rate limiting
        try:
            messages = await client.get_messages(user_identifier, limit=2)
        except Exception as e:
            logger.warning(f"Could not get messages for rate limiting: {e}")
            messages = []

        if not _autoreply_service.should_send_reply(
            emoji_status_id=emoji_status_id,
            available_emoji_id=config.available_emoji_id,
            reply_exists=reply is not None,
            last_two_messages=messages
        ):
            return

        message = reply.message if reply else None
        if message is None:
            return

        await client.send_message(user_identifier, message=message)
        logger.info(f"Auto-reply sent to {user_identifier}")

    # =========================================================================
    # Schedule Commands
    # =========================================================================

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s*$"))
    async def schedule_help(event):
        """Show schedule help."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        help_text = """📅 **Управление расписанием эмодзи-статуса**

**Быстрые команды:**
• `/schedule work <эмодзи>` — рабочие дни ПН-ПТ 09:00-18:00
• `/schedule weekends <эмодзи>` — выходные (ПТ 18:00 - ВС 23:59)
• `/schedule rest <эмодзи>` — нерабочее время (всё остальное)

**Кастомные правила:**
• `/schedule add <дни> <время> <эмодзи>` — добавить правило
  Примеры дней: `ПН-ПТ`, `СБ-ВС`, `ПН,СР,ПТ`
  Пример времени: `09:00-18:00`

**Временные переопределения:**
• `/schedule override <даты> <эмодзи> [название]`
  Пример: `/schedule override 25.12-31.12 🎄 Отпуск`

**Управление:**
• `/schedule list` — показать все правила
• `/schedule del <ID>` — удалить правило по ID
• `/schedule clear` — удалить все правила
• `/schedule on` — включить расписание
• `/schedule off` — выключить расписание
• `/schedule status` — текущий статус"""

        await client.send_message(entity=event.input_chat, message=help_text)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+work\s+.*"))
    async def schedule_work(event):
        """Set work schedule (Mon-Fri 09:00-18:00)."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        entities = event.message.entities or []
        custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

        if len(custom_emojis) != 1:
            await client.send_message(
                entity=event.input_chat,
                message="❌ Нужен 1 кастомный эмодзи. Используйте премиум-эмодзи из панели стикеров."
            )
            return

        emoji_id = custom_emojis[0].document_id
        Schedule.create(
            emoji_id=emoji_id,
            days=[0, 1, 2, 3, 4],  # Mon-Fri
            time_start="09:00",
            time_end="18:00",
            priority=10,
            name="Рабочее время"
        )
        Schedule.set_scheduling_enabled(True)
        logger.info(f"Work schedule created for emoji {emoji_id}")

        await _send_reaction(client, event, '\u2705')

        await client.send_message(
            entity=event.input_chat,
            message="✅ Рабочее расписание добавлено: ПН-ПТ 09:00-18:00\nРасписание включено."
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+weekends\s+.*"))
    async def schedule_weekends(event):
        """Set weekends schedule (Fri 18:00 - Sun 23:59)."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        entities = event.message.entities or []
        custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

        if len(custom_emojis) != 1:
            await client.send_message(
                entity=event.input_chat,
                message="❌ Нужен 1 кастомный эмодзи. Используйте премиум-эмодзи из панели стикеров."
            )
            return

        emoji_id = custom_emojis[0].document_id

        # Friday evening
        Schedule.create(
            emoji_id=emoji_id,
            days=[4],  # Friday
            time_start="18:00",
            time_end="23:59",
            priority=8,
            name="Пятница вечер"
        )

        # Saturday-Sunday all day
        Schedule.create(
            emoji_id=emoji_id,
            days=[5, 6],  # Sat-Sun
            time_start="00:00",
            time_end="23:59",
            priority=8,
            name="Выходные"
        )

        Schedule.set_scheduling_enabled(True)
        logger.info(f"Weekends schedule created for emoji {emoji_id}")

        await _send_reaction(client, event, '\u2705')

        await client.send_message(
            entity=event.input_chat,
            message="✅ Расписание выходных добавлено: ПТ 18:00-23:59 + СБ-ВС весь день\nРасписание включено."
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+rest\s+.*"))
    async def schedule_rest(event):
        """Set rest schedule (all other time)."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        entities = event.message.entities or []
        custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

        if len(custom_emojis) != 1:
            await client.send_message(
                entity=event.input_chat,
                message="❌ Нужен 1 кастомный эмодзи. Используйте премиум-эмодзи из панели стикеров."
            )
            return

        emoji_id = custom_emojis[0].document_id
        # Low priority rule that matches all time
        Schedule.create(
            emoji_id=emoji_id,
            days=[0, 1, 2, 3, 4, 5, 6],  # Every day
            time_start="00:00",
            time_end="23:59",
            priority=1,
            name="Нерабочее время"
        )
        Schedule.set_scheduling_enabled(True)
        logger.info(f"Rest schedule created for emoji {emoji_id}")

        await _send_reaction(client, event, '\u2705')

        await client.send_message(
            entity=event.input_chat,
            message="✅ Расписание для отдыха добавлено (низкий приоритет — применяется когда нет других правил)"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+add\s+(\S+)\s+(\S+)\s+.*"))
    async def schedule_add(event):
        """Add custom schedule rule."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        # Parse command arguments
        text = event.message.text
        parts = text.split(maxsplit=3)  # /schedule add DAYS TIME EMOJI

        if len(parts) < 4:
            await client.send_message(
                entity=event.input_chat,
                message="❌ Формат: `/schedule add <дни> <время> <эмодзи>`\nПример: `/schedule add ПН-ПТ 09:00-18:00 💼`"
            )
            return

        days_str = parts[2]
        time_str = parts[3].split()[0]  # Get time before emoji

        days = parse_days(days_str)
        if days is None:
            await client.send_message(
                entity=event.input_chat,
                message=f"❌ Не могу разобрать дни: `{days_str}`\nПримеры: `ПН-ПТ`, `СБ,ВС`, `ПН,СР,ПТ`"
            )
            return

        time_start, time_end = parse_time_range(time_str)
        if time_start is None or time_end is None:
            await client.send_message(
                entity=event.input_chat,
                message=f"❌ Не могу разобрать время: `{time_str}`\nПример: `09:00-18:00`"
            )
            return

        entities = event.message.entities or []
        custom_emojis = [e for e in entities if isinstance(e, MessageEntityCustomEmoji)]

        if len(custom_emojis) != 1:
            await client.send_message(
                entity=event.input_chat,
                message="❌ Нужен 1 кастомный эмодзи. Используйте премиум-эмодзи из панели стикеров."
            )
            return

        emoji_id = custom_emojis[0].document_id
        days_display = ', '.join(DAY_DISPLAY[d] for d in days)

        schedule = Schedule.create(
            emoji_id=emoji_id,
            days=days,
            time_start=time_start,
            time_end=time_end,
            priority=5,
            name=f"{days_display} {time_start}-{time_end}"
        )
        Schedule.set_scheduling_enabled(True)
        logger.info(f"Custom schedule #{schedule.id} created for emoji {emoji_id}")

        await _send_reaction(client, event, '\u2705')

        await client.send_message(
            entity=event.input_chat,
            message=f"✅ Правило #{schedule.id} добавлено: {days_display} {time_start}-{time_end}"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+list\s*$"))
    async def schedule_list(event):
        """List all schedule rules."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        schedules = Schedule.get_all()
        is_enabled = Schedule.is_scheduling_enabled()

        if not schedules:
            await client.send_message(
                entity=event.input_chat,
                message="📅 Расписание пустое. Используйте `/schedule` для справки."
            )
            return

        status = "✅ включено" if is_enabled else "❌ выключено"
        lines = [f"📅 **Расписание эмодзи** ({status})\n"]

        for s in schedules:
            lines.append(f"• `#{s.id}` {s.get_days_display()} {s.time_start}-{s.time_end} (приоритет: {s.priority})")

        # Show what's currently active
        current_emoji_id = Schedule.get_current_emoji_id()
        if current_emoji_id:
            lines.append(f"\n🕐 Сейчас активен emoji ID: `{current_emoji_id}`")
        else:
            lines.append("\n🕐 Сейчас нет активных правил")

        await client.send_message(entity=event.input_chat, message='\n'.join(lines))

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+del\s+(\d+)\s*$"))
    async def schedule_delete(event):
        """Delete a schedule rule by ID."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        match = event.pattern_match
        schedule_id = int(match.group(1))

        if Schedule.delete_by_id(schedule_id):
            logger.info(f"Schedule #{schedule_id} deleted")
            await _send_reaction(client, event, '\u2705')
            await client.send_message(
                entity=event.input_chat,
                message=f"✅ Правило #{schedule_id} удалено"
            )
        else:
            await client.send_message(
                entity=event.input_chat,
                message=f"❌ Правило #{schedule_id} не найдено"
            )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+clear\s*$"))
    async def schedule_clear(event):
        """Clear all schedule rules."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        Schedule.delete_all()
        Schedule.set_scheduling_enabled(False)
        logger.info("All schedules cleared")

        await _send_reaction(client, event, '\u2705')

        await client.send_message(
            entity=event.input_chat,
            message="✅ Все правила расписания удалены"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+on\s*$"))
    async def schedule_enable(event):
        """Enable scheduling."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        Schedule.set_scheduling_enabled(True)
        logger.info("Scheduling enabled")

        await _send_reaction(client, event, '\u2705')

        await client.send_message(
            entity=event.input_chat,
            message="✅ Расписание включено"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+off\s*$"))
    async def schedule_disable(event):
        """Disable scheduling."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        Schedule.set_scheduling_enabled(False)
        logger.info("Scheduling disabled")

        await _send_reaction(client, event, '\u274c')

        await client.send_message(
            entity=event.input_chat,
            message="❌ Расписание выключено"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/schedule\s+status\s*$"))
    async def schedule_status(event):
        """Show current schedule status."""
        settings_chat_id = Settings.get_settings_chat_id()
        if settings_chat_id != event.chat.id:
            return

        is_enabled = Schedule.is_scheduling_enabled()
        current_emoji_id = Schedule.get_current_emoji_id()
        schedules_count = len(Schedule.get_all())

        me = await client.get_me()
        actual_emoji_id = me.emoji_status.document_id if me.emoji_status else None

        status_text = "✅ включено" if is_enabled else "❌ выключено"

        lines = [
            "📅 **Статус расписания**",
            "",
            f"• Расписание: {status_text}",
            f"• Всего правил: {schedules_count}",
            f"• Текущий статус по расписанию: `{current_emoji_id or 'нет'}`",
            f"• Фактический emoji-статус: `{actual_emoji_id or 'не установлен'}`",
        ]

        await client.send_message(entity=event.input_chat, message='\n'.join(lines))


async def _send_reaction(client, event, emoticon: str) -> None:
    """Send a reaction to a message, handling errors gracefully."""
    try:
        await client(SendReactionRequest(
            peer=event.input_chat,
            msg_id=event.message.id,
            reaction=[types.ReactionEmoji(emoticon=emoticon)]
        ))
    except ReactionInvalidError:
        logger.debug(f"Reaction not allowed in chat {event.chat_id}")
    except Exception as e:
        logger.warning(f"Failed to send reaction: {e}")
