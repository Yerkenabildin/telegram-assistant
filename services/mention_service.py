"""
Mention notification service for handling group chat mentions.

Sends notifications when user is mentioned in group chats while "offline".
"""
from datetime import datetime, timedelta
from typing import Optional, Any, List, Tuple
import re

from logging_config import get_logger
from models import Schedule, VipList

logger = get_logger('mention')

# Urgent keywords that trigger notification with sound
URGENT_KEYWORDS = [
    'asap', 'срочно', 'urgent', 'emergency', 'помогите', 'help',
    'важно', 'critical', 'блокер', 'blocker', 'падает', 'упал',
    'прод', 'prod', 'авария', 'incident', 'горит'
]

# Compile regex pattern for urgent detection (case-insensitive)
URGENT_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(kw) for kw in URGENT_KEYWORDS) + r')\b',
    re.IGNORECASE
)

# Topic detection patterns for summarization
TOPIC_PATTERNS = [
    # Production issues
    (r'\b(прод|prod|production|продакшн?)\b', '🔥 Проблема с продом'),
    (r'\b(падает|упал|crash|down|лежит|не работает|сломал|broken)\b', '💥 Что-то сломалось/упало'),
    (r'\b(500|502|503|504|ошибк[аи]|error|exception|баг|bug)\b', '🐛 Ошибка/баг'),

    # Code review
    (r'\b(pr|пр|pull.?request|merge|мерж|ревью|review)\b', '👀 Нужно ревью кода'),
    (r'\b(код|code|коммит|commit)\b', '💻 Вопрос по коду'),

    # Help requests
    (r'\b(помо[гщ]|help|подскаж|объясн|разбер)\b', '🆘 Нужна помощь'),
    (r'\b(вопрос|question|спроси|узнать)\b', '❓ Есть вопрос'),

    # Tasks/work
    (r'\b(задач[аи]|task|тикет|ticket|issue|джир[ау]|jira)\b', '📋 По задаче/тикету'),
    (r'\b(деплой|deploy|релиз|release|выкат)\b', '🚀 Деплой/релиз'),
    (r'\b(тест|test|qa)\b', '🧪 Тестирование'),

    # Meetings/communication
    (r'\b(созвон|звонок|call|встреч|митинг|meeting)\b', '📞 Созвон/встреча'),
    (r'\b(обсуд|discuss|поговор)\b', '💬 Нужно обсудить'),

    # Access/permissions
    (r'\b(доступ|access|права|permission|ключ|key|токен|token)\b', '🔑 Доступы/права'),

    # Documentation
    (r'\b(док[у|а]|doc|readme|инструкц)\b', '📄 Документация'),
]

# Compile topic patterns
COMPILED_TOPICS = [(re.compile(pattern, re.IGNORECASE), summary) for pattern, summary in TOPIC_PATTERNS]


class MentionService:
    """
    Service for handling group chat mention notifications.

    Handles:
    - Detecting mentions while user is offline
    - Fetching context messages
    - Generating summaries
    - Determining notification urgency
    """

    def __init__(
        self,
        message_limit: int = 50,
        time_limit_minutes: int = 30,
        available_emoji_id: Optional[int] = None,
        vip_usernames: Optional[List[str]] = None
    ):
        """
        Initialize the mention service.

        Args:
            message_limit: Maximum number of messages to fetch for context
            time_limit_minutes: Maximum age of messages to include in context
            available_emoji_id: Emoji ID that indicates user is "online/available"
            vip_usernames: List of usernames whose mentions are always urgent
        """
        self.message_limit = message_limit
        self.time_limit = timedelta(minutes=time_limit_minutes)
        self.available_emoji_id = available_emoji_id
        self.vip_usernames = [u.lower() for u in (vip_usernames or [])]

    def should_notify(self, emoji_status_id: Optional[int]) -> bool:
        """
        Check if notification should be sent based on user's emoji status.

        User is considered "offline" if:
        - No emoji status set
        - Emoji status is different from "available" emoji
        - Work emoji from schedule is set and current status doesn't match

        Args:
            emoji_status_id: Current user's emoji status ID

        Returns:
            True if user is "offline" and should be notified
        """
        # If available emoji is configured and user has it - they're online
        if self.available_emoji_id and emoji_status_id == self.available_emoji_id:
            logger.debug(f"User has available emoji {emoji_status_id}, not notifying")
            return False

        # Check work emoji from schedule - if matches, user is "available"
        work_emoji_id = Schedule.get_work_emoji_id()
        if work_emoji_id is not None and emoji_status_id == work_emoji_id:
            logger.debug(f"User has work emoji {emoji_status_id}, not notifying")
            return False

        return True

    def is_urgent(self, messages: List[Any]) -> bool:
        """
        Check if mention context contains urgent keywords.

        Args:
            messages: List of message objects with text attribute

        Returns:
            True if any message contains urgent keywords
        """
        for msg in messages:
            text = getattr(msg, 'text', '') or ''
            if URGENT_PATTERN.search(text):
                logger.debug(f"Urgent keyword found in message: {text[:50]}...")
                return True
        return False

    def is_vip_sender(self, sender_username: Optional[str]) -> bool:
        """
        Check if sender is a VIP whose mentions are always urgent.

        First checks VipList in database, then falls back to config.

        Args:
            sender_username: Username of the sender (without @)

        Returns:
            True if sender is in VIP list
        """
        if not sender_username:
            return False

        # Check database first
        vip_users = VipList.get_users()
        if sender_username.lower() in vip_users:
            logger.debug(f"VIP sender detected (from DB): @{sender_username}")
            return True

        # Fallback to config (for backwards compatibility)
        if self.vip_usernames and sender_username.lower() in self.vip_usernames:
            logger.debug(f"VIP sender detected (from config): @{sender_username}")
            return True

        return False

    def is_vip_chat(self, chat_id: int) -> bool:
        """
        Check if chat is a VIP chat where all mentions are urgent.

        Args:
            chat_id: Chat ID

        Returns:
            True if chat is in VIP list
        """
        vip_chats = VipList.get_chats()
        is_vip = chat_id in vip_chats
        if is_vip:
            logger.debug(f"VIP chat detected: {chat_id}")
        return is_vip

    def filter_messages_by_time(
        self,
        messages: List[Any],
        reference_time: Optional[datetime] = None
    ) -> List[Any]:
        """
        Filter messages to only include those within time limit.

        Args:
            messages: List of message objects with date attribute
            reference_time: Reference time (default: now)

        Returns:
            Filtered list of messages within time limit
        """
        if reference_time is None:
            # Use timezone from first message if available
            if messages and hasattr(messages[0], 'date') and messages[0].date:
                reference_time = datetime.now(messages[0].date.tzinfo)
            else:
                reference_time = datetime.now()

        cutoff_time = reference_time - self.time_limit
        filtered = []

        for msg in messages:
            msg_date = getattr(msg, 'date', None)
            if msg_date and msg_date >= cutoff_time:
                filtered.append(msg)

        return filtered

    def _detect_topics(self, text: str) -> List[str]:
        """
        Detect topics from text using keyword patterns.

        Args:
            text: Text to analyze

        Returns:
            List of detected topic summaries
        """
        topics = []
        for pattern, summary in COMPILED_TOPICS:
            if pattern.search(text):
                if summary not in topics:
                    topics.append(summary)
        return topics

    def generate_summary(
        self,
        messages: List[Any],
        mention_message: Any,
        max_context_messages: int = 5,
        reply_chain: Optional[List[Any]] = None
    ) -> str:
        """
        Generate a short summary of the mention context.

        Analyzes messages to detect the likely reason for mention,
        then shows a brief context.

        Args:
            messages: List of messages (newest first)
            mention_message: The message that contains the mention
            max_context_messages: Maximum messages to include in summary
            reply_chain: Optional list of messages in reply chain (oldest first)

        Returns:
            Summary text
        """
        mention_text = getattr(mention_message, 'text', '') or ''

        # Collect all text for topic detection
        all_text_parts = [mention_text]

        # Add reply chain text for topic detection
        if reply_chain:
            for msg in reply_chain:
                text = getattr(msg, 'text', '') or ''
                if text.strip():
                    all_text_parts.append(text)

        # Get messages before the mention for context
        context_msgs = []
        found_mention = False

        for msg in messages:
            if msg.id == mention_message.id:
                found_mention = True
                continue
            if found_mention and len(context_msgs) < max_context_messages:
                text = getattr(msg, 'text', '') or ''
                if text.strip():
                    context_msgs.append(text)
                    all_text_parts.append(text)

        # Detect topics from all messages
        all_text = ' '.join(all_text_parts)
        detected_topics = self._detect_topics(all_text)

        # Build summary
        lines = []

        # Add detected reason/topic
        if detected_topics:
            lines.append("📌 Вероятная причина:")
            lines.append(f"  {detected_topics[0]}")  # Primary topic
            if len(detected_topics) > 1:
                lines.append(f"  (также: {', '.join(detected_topics[1:3])})")
            lines.append("")
        else:
            lines.append("📌 Причина: общий вопрос/обсуждение")
            lines.append("")

        # Note: reply_chain is used for topic detection above but not displayed
        # in the notification to keep it concise

        # Add brief context (just 2 messages max for brevity)
        if context_msgs:
            lines.append("💬 Контекст:")
            for text in reversed(context_msgs[-2:]):
                # Truncate long messages
                if len(text) > 80:
                    text = text[:80] + "..."
                lines.append(f"  «{text}»")
            lines.append("")

        # Add the mention message (shorter)
        lines.append("➡️ Сообщение:")
        if len(mention_text) > 150:
            mention_text = mention_text[:150] + "..."
        lines.append(f"  «{mention_text}»")

        return "\n".join(lines)

    def generate_private_summary(
        self,
        messages: List[Any],
        current_message: Any,
        max_context_messages: int = 5
    ) -> str:
        """
        Generate a short summary of the private conversation context.

        Args:
            messages: List of messages (newest first)
            current_message: The new message that triggered the notification
            max_context_messages: Maximum messages to include in summary

        Returns:
            Summary text
        """
        current_text = getattr(current_message, 'text', '') or ''

        # Collect text for topic detection
        all_text_parts = [current_text]

        # Get recent messages for context (excluding the current one)
        context_msgs = []
        for msg in messages:
            if msg.id == current_message.id:
                continue
            if len(context_msgs) >= max_context_messages:
                break
            text = getattr(msg, 'text', '') or ''
            if text.strip():
                context_msgs.append(text)
                all_text_parts.append(text)

        # Detect topics from all messages
        all_text = ' '.join(all_text_parts)
        detected_topics = self._detect_topics(all_text)

        # Build summary
        lines = []

        # Add detected topic if found
        if detected_topics:
            lines.append("📌 Тема:")
            lines.append(f"  {detected_topics[0]}")
            if len(detected_topics) > 1:
                lines.append(f"  (также: {', '.join(detected_topics[1:3])})")
        else:
            lines.append("📌 Тема: общение")

        # Add brief context (last 2 messages max)
        if context_msgs:
            lines.append("")
            lines.append("💬 Контекст разговора:")
            for text in reversed(context_msgs[-2:]):
                if len(text) > 80:
                    text = text[:80] + "..."
                lines.append(f"  «{text}»")

        return "\n".join(lines)

    async def generate_private_summary_with_ai(
        self,
        messages: List[Any],
        current_message: Any,
        sender_name: str
    ) -> Tuple[str, Optional[bool]]:
        """
        Generate summary for private message using Yandex GPT if available.

        Args:
            messages: List of messages (newest first)
            current_message: The new message
            sender_name: Name of the sender

        Returns:
            Tuple of (summary text, is_urgent from AI or None)
        """
        from services.yandex_gpt_service import get_yandex_gpt_service

        gpt_service = get_yandex_gpt_service()

        if gpt_service is None:
            logger.debug("Yandex GPT not configured, using keyword-based summary")
            return self.generate_private_summary(messages, current_message), None

        current_text = getattr(current_message, 'text', '') or ''

        # Prepare context messages
        context_texts = []
        for msg in messages:
            if msg.id == current_message.id:
                continue
            if len(context_texts) >= 8:
                break
            text = getattr(msg, 'text', '') or ''
            if text.strip():
                # Mark if message is from sender or from me
                is_outgoing = getattr(msg, 'out', False)
                prefix = "[Я] " if is_outgoing else f"[{sender_name}] "
                context_texts.append(f"{prefix}{text}")

        # Reverse to get chronological order
        context_texts = list(reversed(context_texts))

        try:
            summary, is_urgent = await gpt_service.summarize_mention(
                messages=context_texts,
                mention_message=current_text,
                chat_title=f"Личный чат с {sender_name}"
            )

            if summary:
                logger.info("Generated private message summary using Yandex GPT")
                return summary, is_urgent

        except Exception as e:
            logger.warning(f"Yandex GPT failed for private message, falling back: {e}")

        return self.generate_private_summary(messages, current_message), None

    async def generate_summary_with_ai(
        self,
        messages: List[Any],
        mention_message: Any,
        chat_title: str,
        reply_chain: Optional[List[Any]] = None,
        extracted_context: Optional[Any] = None
    ) -> Tuple[str, Optional[bool]]:
        """
        Generate summary using Yandex GPT if available, otherwise fallback to keywords.

        Args:
            messages: List of messages (newest first)
            mention_message: The message that contains the mention
            chat_title: Title of the chat for context
            reply_chain: Optional list of messages in reply chain (oldest first)
            extracted_context: Optional ExtractedContext from context_extraction_service

        Returns:
            Tuple of (summary text, is_urgent from AI or None to use keyword detection)
        """
        from services.yandex_gpt_service import get_yandex_gpt_service

        gpt_service = get_yandex_gpt_service()

        if gpt_service is None:
            logger.debug("Yandex GPT not configured, using keyword-based summary")
            return self.generate_summary(messages, mention_message, reply_chain=reply_chain), None

        mention_text = getattr(mention_message, 'text', '') or ''

        # Use extracted context if available (new flow)
        if extracted_context is not None:
            from services.context_extraction_service import ContextExtractionService

            # Check if context needs chunking
            ctx_service = ContextExtractionService()
            needs_chunking = ctx_service.needs_chunked_summarization(extracted_context)

            # Prepare context messages for GPT
            context_messages = [
                {
                    'sender': msg.sender_name,
                    'text': msg.text
                }
                for msg in extracted_context.messages
                if msg.text.strip() and not msg.is_mention
            ]

            try:
                summary, is_urgent = await gpt_service.summarize_context(
                    context_messages=context_messages,
                    mention_message=mention_text,
                    chat_title=chat_title,
                    needs_chunking=needs_chunking
                )

                if summary:
                    logger.info(f"Generated summary using Yandex GPT (chunked={needs_chunking})")
                    return summary, is_urgent

            except Exception as e:
                logger.warning(f"Yandex GPT failed, falling back to keywords: {e}")

            # Fallback to keyword-based summary
            return self.generate_summary(messages, mention_message, reply_chain=reply_chain), None

        # Legacy flow: prepare messages manually
        context_texts = []

        # Add reply chain first (if present)
        if reply_chain:
            for msg in reply_chain:
                text = getattr(msg, 'text', '') or ''
                if text.strip():
                    sender = getattr(msg, 'sender', None)
                    sender_name = ''
                    if sender:
                        first = getattr(sender, 'first_name', '') or ''
                        sender_name = first if first else ''
                    prefix = f"[{sender_name}] " if sender_name else "[reply] "
                    context_texts.append(f"{prefix}{text}")

        found_mention = False
        for msg in messages:
            if msg.id == mention_message.id:
                found_mention = True
                continue
            if found_mention and len(context_texts) < 8:  # Allow more with reply chain
                text = getattr(msg, 'text', '') or ''
                if text.strip():
                    context_texts.append(text)

        # Reverse to get chronological order (oldest first)
        context_texts = list(reversed(context_texts))

        try:
            summary, is_urgent = await gpt_service.summarize_mention(
                messages=context_texts,
                mention_message=mention_text,
                chat_title=chat_title
            )

            if summary:
                logger.info("Generated summary using Yandex GPT")
                return summary, is_urgent

        except Exception as e:
            logger.warning(f"Yandex GPT failed, falling back to keywords: {e}")

        # Fallback to keyword-based summary
        return self.generate_summary(messages, mention_message, reply_chain=reply_chain), None

    def format_notification(
        self,
        chat_title: str,
        chat_id: int,
        sender_name: str,
        sender_username: Optional[str],
        summary: str,
        is_urgent: bool,
        message_id: Optional[int] = None
    ) -> str:
        """
        Format the notification message.

        Args:
            chat_title: Title of the group chat
            chat_id: ID of the chat
            sender_name: Display name of the person who mentioned
            sender_username: Username of the sender (may be None)
            summary: Generated summary of context
            is_urgent: Whether this is an urgent mention
            message_id: ID of the mention message (for deep link)

        Returns:
            Formatted notification message
        """
        # Header with urgency indicator
        if is_urgent:
            header = "🚨 Срочное упоминание в группе!"
        else:
            header = "📢 Упоминание в группе"

        # Sender info
        if sender_username:
            sender_info = f"@{sender_username} ({sender_name})"
        else:
            sender_info = sender_name

        # Build message
        lines = [
            header,
            "",
            f"📍 Чат: {chat_title}",
            f"👤 Призвал: {sender_info}",
            "",
            summary,
        ]

        # Add link to the specific message
        if chat_id and message_id:
            link = self.get_chat_link(chat_id, message_id)
            lines.append("")
            lines.append(f"🔗 Открыть сообщение: {link}")

        return "\n".join(lines)

    def get_chat_link(self, chat_id: int, message_id: int) -> str:
        """
        Generate a deep link to the specific message in a chat.

        Uses https://t.me/c/CHAT_ID/MSG_ID format which works for
        private groups and supergroups.

        Args:
            chat_id: Chat ID (may be negative for groups)
            message_id: Message ID

        Returns:
            Deep link URL
        """
        # Convert supergroup/channel ID format
        # t.me/c/ format requires chat_id without -100 prefix
        if chat_id < 0:
            chat_id_str = str(chat_id)
            if chat_id_str.startswith('-100'):
                chat_id_str = chat_id_str[4:]
            else:
                chat_id_str = chat_id_str[1:]  # Remove just the minus
        else:
            chat_id_str = str(chat_id)

        return f"https://t.me/c/{chat_id_str}/{message_id}"

    def format_private_notification(
        self,
        sender_name: str,
        sender_username: Optional[str],
        summary: str,
        is_urgent: bool,
        message_text: str
    ) -> str:
        """
        Format notification for private message.

        Args:
            sender_name: Display name of the sender
            sender_username: Username of the sender (may be None)
            summary: Generated summary of context
            is_urgent: Whether this is an urgent message
            message_text: The actual message text (truncated)

        Returns:
            Formatted notification message
        """
        # Header with urgency indicator
        if is_urgent:
            header = "🚨 Срочное личное сообщение!"
        else:
            header = "💬 Личное сообщение"

        # Sender info with link
        if sender_username:
            sender_info = f"@{sender_username} ({sender_name})"
            sender_link = f"https://t.me/{sender_username}"
        else:
            sender_info = sender_name
            sender_link = None

        # Truncate message text
        if len(message_text) > 200:
            message_text = message_text[:200] + "..."

        # Build message
        lines = [
            header,
            "",
            f"👤 От: {sender_info}",
            "",
        ]

        # Add summary if present
        if summary:
            lines.append(summary)
            lines.append("")

        # Add the message itself
        lines.append("✉️ Сообщение:")
        lines.append(f"  «{message_text}»")

        # Add link to conversation
        if sender_link:
            lines.append("")
            lines.append(f"🔗 Открыть диалог: {sender_link}")

        return "\n".join(lines)
