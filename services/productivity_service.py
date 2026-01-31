"""
Productivity summary service for daily activity reports.

Collects user's outgoing messages across all chats and generates
a summary of daily communication activity.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from telethon.errors import FloodWaitError

from logging_config import get_logger

logger = get_logger('productivity')


@dataclass
class ChatSummary:
    """Summary of activity in a single chat."""
    chat_id: int
    chat_title: str
    chat_type: str  # 'private', 'group', 'channel'
    message_count: int
    participants_mentioned: List[str]  # usernames of people you talked to/mentioned
    messages: List[Dict[str, Any]]  # list of {text, timestamp} for analysis
    first_message_time: Optional[datetime] = None
    last_message_time: Optional[datetime] = None


@dataclass
class DailySummary:
    """Complete daily productivity summary."""
    date: datetime
    total_messages: int
    total_chats: int
    chat_summaries: List[ChatSummary] = field(default_factory=list)
    topics_discussed: List[str] = field(default_factory=list)
    summary_text: str = ""


class ProductivityService:
    """
    Service for collecting and summarizing daily communication activity.

    Workflow:
    1. Iterate through all dialogs with recent activity
    2. For each dialog, fetch today's outgoing messages
    3. Group and summarize by chat
    4. Generate overall daily summary using AI
    """

    def __init__(
        self,
        timezone: str = "Europe/Moscow",
        max_dialogs: int = 100,
        max_messages_per_chat: int = 200,
        summary_chunk_size: int = 20,
        request_delay: float = 0.5  # Delay between API requests to avoid FloodWait
    ):
        """
        Initialize the productivity service.

        Args:
            timezone: Timezone for "today" calculation
            max_dialogs: Maximum number of dialogs to scan
            max_messages_per_chat: Maximum messages to fetch per chat
            summary_chunk_size: Messages per chunk for AI summarization
            request_delay: Delay in seconds between API requests (rate limiting)
        """
        self.timezone = ZoneInfo(timezone)
        self.max_dialogs = max_dialogs
        self.max_messages_per_chat = max_messages_per_chat
        self.summary_chunk_size = summary_chunk_size
        self.request_delay = request_delay

    def _get_today_range(self, date: Optional[datetime] = None) -> tuple[datetime, datetime]:
        """
        Get start and end of the day in configured timezone.

        Args:
            date: Optional date (defaults to today)

        Returns:
            Tuple of (day_start, day_end) as timezone-aware datetimes
        """
        if date is None:
            date = datetime.now(self.timezone)
        elif date.tzinfo is None:
            date = date.replace(tzinfo=self.timezone)

        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        return day_start, day_end

    def _is_dialog_muted(self, dialog) -> bool:
        """
        Check if a dialog is muted.

        Args:
            dialog: Telethon dialog object

        Returns:
            True if dialog is muted, False otherwise
        """
        try:
            # dialog.dialog contains PeerNotifySettings
            notify_settings = getattr(dialog.dialog, 'notify_settings', None)
            if notify_settings is None:
                return False

            # Check mute_until - if set to a future timestamp or max int, it's muted
            mute_until = getattr(notify_settings, 'mute_until', None)
            if mute_until:
                # mute_until is a timestamp; if it's in the future, dialog is muted
                # Max value (2147483647) means muted forever
                if mute_until > datetime.now().timestamp():
                    return True

            # Also check silent flag
            silent = getattr(notify_settings, 'silent', False)
            if silent:
                return True

            return False
        except Exception:
            return False

    async def collect_daily_messages(
        self,
        client,
        date: Optional[datetime] = None,
        extra_chat_ids: Optional[List[int]] = None
    ) -> DailySummary:
        """
        Collect all outgoing messages for a given day.

        Iterates through dialogs and fetches outgoing messages.
        By default, only unmuted chats are included, but extra_chat_ids
        allows including specific muted chats.

        Args:
            client: Telethon client
            date: Date to collect messages for (defaults to today)
            extra_chat_ids: List of chat IDs to always include (even if muted)

        Returns:
            DailySummary with collected messages grouped by chat
        """
        extra_chat_ids = extra_chat_ids or []
        day_start, day_end = self._get_today_range(date)

        logger.info(f"Collecting messages for {day_start.date()}")

        summary = DailySummary(
            date=day_start,
            total_messages=0,
            total_chats=0
        )

        # Get current user for from_user filter
        me = await client.get_me()

        dialog_count = 0
        skipped_inactive = 0
        skipped_muted = 0

        # Iterate through all dialogs
        # Dialogs are sorted by date (most recent first)
        async for dialog in client.iter_dialogs():
            if dialog_count >= self.max_dialogs:
                logger.info(f"Reached max dialogs limit ({self.max_dialogs})")
                break

            # Quick check: skip dialogs with no recent activity
            # dialog.message contains the last message in the dialog
            if dialog.message and dialog.message.date:
                last_msg_date = dialog.message.date.astimezone(self.timezone)
                if last_msg_date < day_start:
                    # No messages today - skip this dialog entirely
                    skipped_inactive += 1
                    # Since dialogs are sorted by date, once we see old dialogs
                    # we might still have newer ones if user has many chats
                    # So we continue but increment counter to stop early if too many skipped
                    if skipped_inactive > 50:
                        logger.info(f"Skipped {skipped_inactive} inactive dialogs, stopping search")
                        break
                    continue

            # Skip muted dialogs unless they're in extra_chat_ids
            is_extra = dialog.id in extra_chat_ids
            if not is_extra and self._is_dialog_muted(dialog):
                skipped_muted += 1
                continue

            dialog_count += 1

            # Skip channels where we're not admin (usually no outgoing messages)
            if dialog.is_channel and not dialog.is_group:
                continue

            # Determine chat type
            if dialog.is_user:
                chat_type = 'private'
            elif dialog.is_group:
                chat_type = 'group'
            else:
                chat_type = 'channel'

            chat_title = dialog.title or dialog.name or 'Unknown'

            # Fetch today's messages
            # Optimization: use from_user=me to only get outgoing messages
            chat_messages = []
            participants = set()
            first_msg_time = None
            last_msg_time = None

            try:
                # Rate limiting: small delay between dialog processing
                await asyncio.sleep(self.request_delay)

                # First, quickly check if we have any outgoing messages today
                # by fetching a small batch with from_user filter
                found_my_messages = False
                async for message in client.iter_messages(
                    dialog.entity,
                    offset_date=day_end,
                    from_user=me,  # Only my messages!
                    limit=5  # Quick check
                ):
                    if message.date.astimezone(self.timezone) < day_start:
                        break
                    found_my_messages = True
                    break

                if not found_my_messages:
                    # No outgoing messages from me today - skip this chat
                    continue

                # Now fetch all my messages today
                async for message in client.iter_messages(
                    dialog.entity,
                    offset_date=day_end,
                    from_user=me,  # Only my messages
                    limit=self.max_messages_per_chat
                ):
                    # Skip if before our target day
                    if message.date.astimezone(self.timezone) < day_start:
                        break

                    # Skip empty messages
                    text = message.text or ''
                    if not text.strip():
                        continue

                    msg_time = message.date.astimezone(self.timezone)

                    chat_messages.append({
                        'text': text,
                        'timestamp': msg_time,
                        'reply_to': message.reply_to_msg_id
                    })

                    # Track time range
                    if first_msg_time is None or msg_time < first_msg_time:
                        first_msg_time = msg_time
                    if last_msg_time is None or msg_time > last_msg_time:
                        last_msg_time = msg_time

                    # Extract @mentions from text
                    import re
                    mentions = re.findall(r'@(\w+)', text)
                    participants.update(mentions)

            except FloodWaitError as e:
                # Telegram rate limit hit - wait and continue
                wait_time = e.seconds
                logger.warning(f"FloodWait: waiting {wait_time}s before continuing...")
                await asyncio.sleep(wait_time + 1)  # Wait + 1s safety margin
                continue  # Skip this chat, move to next

            except Exception as e:
                logger.warning(f"Failed to fetch messages from '{chat_title}': {e}")
                continue

            # Skip chats with no messages today
            if not chat_messages:
                continue

            # Reverse to chronological order (oldest first)
            chat_messages.reverse()

            chat_summary = ChatSummary(
                chat_id=dialog.id,
                chat_title=chat_title,
                chat_type=chat_type,
                message_count=len(chat_messages),
                participants_mentioned=list(participants),
                messages=chat_messages,
                first_message_time=first_msg_time,
                last_message_time=last_msg_time
            )

            summary.chat_summaries.append(chat_summary)
            summary.total_messages += len(chat_messages)
            summary.total_chats += 1

        # Sort by message count (most active first)
        summary.chat_summaries.sort(key=lambda x: x.message_count, reverse=True)

        logger.info(
            f"Collected {summary.total_messages} messages from "
            f"{summary.total_chats} chats (scanned {dialog_count} active dialogs, "
            f"skipped {skipped_inactive} inactive, {skipped_muted} muted)"
        )

        return summary

    async def generate_chat_summary(
        self,
        chat: ChatSummary,
        gpt_service=None
    ) -> str:
        """
        Generate a brief summary for a single chat.

        Args:
            chat: ChatSummary with messages
            gpt_service: Optional Yandex GPT service for AI summarization

        Returns:
            Brief summary text (1-2 sentences)
        """
        if not chat.messages:
            return "Нет сообщений"

        # If GPT is available and enough messages, use AI
        if gpt_service and len(chat.messages) >= 3:
            messages_text = "\n".join([
                f"[{m['timestamp'].strftime('%H:%M')}] {m['text'][:200]}"
                for m in chat.messages[-15:]  # Last 15 messages
            ])

            prompt = f"""Это мои сообщения из чата "{chat.chat_title}" за сегодня.

{messages_text}

Кратко (1-2 предложения) опиши чем я занимался в этом чате.
Например: "Обсуждал архитектуру нового сервиса", "Помогал с ревью кода", "Отвечал на вопросы по API".
Отвечай от первого лица."""

            try:
                response = await gpt_service._call_api(prompt)
                if response:
                    return response.strip()
            except Exception as e:
                logger.warning(f"Failed to generate AI summary for chat: {e}")

        # Fallback: simple keyword-based summary
        return self._generate_keyword_summary(chat)

    def _generate_keyword_summary(self, chat: ChatSummary) -> str:
        """
        Generate a simple keyword-based summary.

        Args:
            chat: ChatSummary with messages

        Returns:
            Basic summary based on keywords
        """
        all_text = ' '.join(m['text'] for m in chat.messages).lower()

        # Activity patterns
        patterns = [
            (r'\b(ревью|review|pr|пр|merge)\b', 'ревью кода'),
            (r'\b(баг|bug|фикс|fix|исправ)\b', 'исправление багов'),
            (r'\b(созвон|звонок|call|митинг|meeting)\b', 'созвоны'),
            (r'\b(задач|task|тикет|ticket|jira)\b', 'обсуждение задач'),
            (r'\b(деплой|deploy|релиз|release)\b', 'деплой/релизы'),
            (r'\b(вопрос|помо[гщ]|подска)\b', 'помощь/ответы на вопросы'),
            (r'\b(тест|test)\b', 'тестирование'),
            (r'\b(документ|doc|readme)\b', 'документация'),
        ]

        import re
        detected = []
        for pattern, label in patterns:
            if re.search(pattern, all_text):
                detected.append(label)

        if detected:
            return f"Обсуждал: {', '.join(detected[:3])}"

        return f"{chat.message_count} сообщений"

    async def generate_daily_summary(
        self,
        daily: DailySummary,
        gpt_service=None
    ) -> str:
        """
        Generate a complete daily productivity summary.

        Args:
            daily: DailySummary with all collected messages
            gpt_service: Optional Yandex GPT service

        Returns:
            Formatted summary text
        """
        if daily.total_messages == 0:
            return "📊 **Сводка за день**\n\nСегодня вы не отправляли сообщений.\n\n#productivity #дайджест"

        lines = [
            f"📊 **Продуктивность за {daily.date.strftime('%d.%m.%Y')}**",
            "",
            f"📨 Всего сообщений: **{daily.total_messages}**",
            f"💬 Активных чатов: **{daily.total_chats}**",
            ""
        ]

        # Generate per-chat summaries (limit to top 10)
        chat_summaries = []

        for chat in daily.chat_summaries[:10]:
            summary = await self.generate_chat_summary(chat, gpt_service)

            # Format chat type emoji
            type_emoji = {
                'private': '👤',
                'group': '👥',
                'channel': '📢'
            }.get(chat.chat_type, '💬')

            chat_summaries.append({
                'chat': chat,
                'summary': summary
            })

        # If GPT available, generate overall insights
        if gpt_service and daily.total_messages >= 10:
            overall = await self._generate_overall_insights(daily, chat_summaries, gpt_service)
            if overall:
                lines.append("**Главное за день:**")
                lines.append(overall)
                lines.append("")

        # Add per-chat details
        lines.append("**По чатам:**")
        for item in chat_summaries:
            chat = item['chat']
            summary = item['summary']

            type_emoji = {
                'private': '👤',
                'group': '👥',
                'channel': '📢'
            }.get(chat.chat_type, '💬')

            lines.append(f"{type_emoji} **{chat.chat_title}** ({chat.message_count} сообщ.)")
            lines.append(f"   └ {summary}")

        # Note if there were more chats
        remaining = daily.total_chats - len(chat_summaries)
        if remaining > 0:
            lines.append(f"\n...и ещё {remaining} чатов")

        # Add hashtag for easy filtering
        lines.append("")
        lines.append("#productivity #дайджест")

        return "\n".join(lines)

    async def _generate_overall_insights(
        self,
        daily: DailySummary,
        chat_summaries: List[dict],
        gpt_service
    ) -> Optional[str]:
        """
        Generate overall insights about the day using AI.

        Args:
            daily: DailySummary
            chat_summaries: Per-chat summaries
            gpt_service: Yandex GPT service

        Returns:
            Overall insights text or None
        """
        # Prepare context for AI
        context_parts = []
        for item in chat_summaries[:7]:
            chat = item['chat']
            context_parts.append(f"- {chat.chat_title}: {item['summary']}")

        context = "\n".join(context_parts)

        prompt = f"""Проанализируй мою активность за день:

{context}

Всего: {daily.total_messages} сообщений в {daily.total_chats} чатах.

Напиши 2-4 пункта списком - краткие выводы о моей продуктивности.
Формат:
- Пункт 1
- Пункт 2

Будь конкретным, используй названия чатов и людей если уместно."""

        try:
            response = await gpt_service._call_api(prompt)
            if response:
                return response.strip()
        except Exception as e:
            logger.warning(f"Failed to generate overall insights: {e}")

        return None


# Singleton instance
_service_instance: Optional[ProductivityService] = None


def get_productivity_service() -> ProductivityService:
    """
    Get or create the productivity service instance.

    Returns:
        ProductivityService instance
    """
    global _service_instance

    if _service_instance is None:
        from config import config
        _service_instance = ProductivityService(timezone=config.timezone)

    return _service_instance
