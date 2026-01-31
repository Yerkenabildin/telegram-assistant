"""
Context extraction service for mention notifications.

Extracts conversation context around mentions using reply chain anchoring.
Supports chunked summarization for large contexts.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Any, Tuple

from logging_config import get_logger

logger = get_logger('context_extraction')


# Default configuration
DEFAULT_CONTEXT_BEFORE_MINUTES = 30  # Minutes before anchor
DEFAULT_FALLBACK_CONTEXT_MINUTES = 60  # When no reply chain
DEFAULT_MAX_REPLY_CHAIN_DEPTH = 50  # Max messages in reply chain
DEFAULT_CHUNK_SIZE = 20  # Messages per chunk for summarization
DEFAULT_MAX_TOKENS_PER_CHUNK = 20000  # Yandex GPT supports 32K, leave room for prompt/response


@dataclass
class ContextMessage:
    """Represents a message in the extracted context."""
    message_id: int
    text: str
    sender_name: str
    sender_username: Optional[str]
    timestamp: datetime
    is_anchor: bool = False
    is_mention: bool = False


@dataclass
class ExtractedContext:
    """Result of context extraction."""
    messages: List[ContextMessage]
    anchor_message: Optional[ContextMessage]
    mention_message: ContextMessage
    has_reply_chain: bool
    total_messages: int
    time_span_minutes: float


class ContextExtractionService:
    """
    Service for extracting conversation context around mentions.

    Uses reply chain anchoring:
    1. Find the root (oldest) message in the reply chain
    2. Take messages from 30 min before the anchor to current moment
    3. If no reply chain, take last 1 hour of messages
    """

    def __init__(
        self,
        context_before_minutes: int = DEFAULT_CONTEXT_BEFORE_MINUTES,
        fallback_context_minutes: int = DEFAULT_FALLBACK_CONTEXT_MINUTES,
        max_reply_chain_depth: int = DEFAULT_MAX_REPLY_CHAIN_DEPTH,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_tokens_per_chunk: int = DEFAULT_MAX_TOKENS_PER_CHUNK
    ):
        """
        Initialize context extraction service.

        Args:
            context_before_minutes: Minutes before anchor to include
            fallback_context_minutes: Minutes of context when no reply chain
            max_reply_chain_depth: Maximum reply chain traversal depth
            chunk_size: Messages per chunk for summarization
            max_tokens_per_chunk: Approximate max tokens per chunk
        """
        self.context_before_minutes = context_before_minutes
        self.fallback_context_minutes = fallback_context_minutes
        self.max_reply_chain_depth = max_reply_chain_depth
        self.chunk_size = chunk_size
        self.max_tokens_per_chunk = max_tokens_per_chunk

    async def find_anchor_message(
        self,
        client,
        chat_id: int,
        mention_message: Any
    ) -> Tuple[Optional[Any], List[Any]]:
        """
        Find the anchor message by traversing the reply chain.

        The anchor is the root (oldest/first) message in the reply chain.
        If no reply chain exists, returns None.

        Args:
            client: Telethon client
            chat_id: Chat ID
            mention_message: The message containing the mention

        Returns:
            Tuple of (anchor_message, reply_chain_list)
            anchor_message is None if no reply chain exists
        """
        chain = []
        current_msg = mention_message
        depth = 0

        while depth < self.max_reply_chain_depth:
            reply_to_id = self._get_reply_to_id(current_msg)

            if not reply_to_id:
                break

            try:
                replied_msg = await client.get_messages(chat_id, ids=reply_to_id)
                if replied_msg:
                    chain.append(replied_msg)
                    current_msg = replied_msg
                    depth += 1
                else:
                    break
            except Exception as e:
                logger.warning(f"Failed to fetch reply message {reply_to_id}: {e}")
                break

        if not chain:
            return None, []

        # The anchor is the last message in our chain (oldest in conversation)
        anchor = chain[-1]
        # Reverse chain to get chronological order (oldest first)
        chain.reverse()

        logger.info(f"Found reply chain with {len(chain)} messages, anchor: {anchor.id}")
        return anchor, chain

    def _get_reply_to_id(self, message: Any) -> Optional[int]:
        """Extract reply_to_msg_id from message, handling different API versions."""
        reply_to_id = getattr(message, 'reply_to_msg_id', None)
        if not reply_to_id:
            reply_to = getattr(message, 'reply_to', None)
            if reply_to:
                reply_to_id = getattr(reply_to, 'reply_to_msg_id', None)
        return reply_to_id

    async def extract_context(
        self,
        client,
        chat_id: int,
        mention_message: Any,
        message_limit: int = 200
    ) -> ExtractedContext:
        """
        Extract conversation context around a mention.

        Logic:
        1. Find anchor message (root of reply chain)
        2. If anchor exists: fetch 30min before anchor + all until now
        3. If no anchor: fetch last 1 hour of messages

        Args:
            client: Telethon client
            chat_id: Chat ID
            mention_message: The message containing the mention
            message_limit: Maximum messages to fetch

        Returns:
            ExtractedContext with all context information
        """
        # Find anchor message
        anchor_msg, reply_chain = await self.find_anchor_message(
            client, chat_id, mention_message
        )

        has_reply_chain = anchor_msg is not None

        # Determine time boundaries
        mention_time = mention_message.date

        if has_reply_chain:
            anchor_time = anchor_msg.date
            # Context from 30 min before anchor to current moment
            context_start = anchor_time - timedelta(minutes=self.context_before_minutes)
            context_end = mention_time
            logger.info(
                f"Using anchor-based context: {self.context_before_minutes}min before "
                f"anchor ({anchor_time}) to mention ({mention_time})"
            )
        else:
            # No reply chain: use last 1 hour
            context_end = mention_time
            context_start = mention_time - timedelta(minutes=self.fallback_context_minutes)
            logger.info(
                f"No reply chain, using {self.fallback_context_minutes}min fallback context"
            )

        # Fetch messages in the time range
        try:
            all_messages = await client.get_messages(
                chat_id,
                limit=message_limit
            )
        except Exception as e:
            logger.error(f"Failed to fetch messages: {e}")
            # Return minimal context with just the mention
            return self._create_minimal_context(mention_message)

        # Filter messages by time range
        filtered_messages = []
        for msg in all_messages:
            msg_time = msg.date
            if msg_time and context_start <= msg_time <= context_end:
                filtered_messages.append(msg)

        # Sort by timestamp (oldest first)
        filtered_messages.sort(key=lambda m: m.date)

        # Convert to ContextMessage objects
        context_messages = []
        anchor_context_msg = None
        mention_context_msg = None

        for msg in filtered_messages:
            sender = await self._get_sender_info(client, msg)

            is_anchor = has_reply_chain and msg.id == anchor_msg.id
            is_mention = msg.id == mention_message.id

            ctx_msg = ContextMessage(
                message_id=msg.id,
                text=msg.text or '',
                sender_name=sender['name'],
                sender_username=sender['username'],
                timestamp=msg.date,
                is_anchor=is_anchor,
                is_mention=is_mention
            )
            context_messages.append(ctx_msg)

            if is_anchor:
                anchor_context_msg = ctx_msg
            if is_mention:
                mention_context_msg = ctx_msg

        # Ensure mention message is included even if outside time range
        if not mention_context_msg:
            sender = await self._get_sender_info(client, mention_message)
            mention_context_msg = ContextMessage(
                message_id=mention_message.id,
                text=mention_message.text or '',
                sender_name=sender['name'],
                sender_username=sender['username'],
                timestamp=mention_message.date,
                is_anchor=False,
                is_mention=True
            )
            context_messages.append(mention_context_msg)
            context_messages.sort(key=lambda m: m.timestamp)

        # Calculate time span
        if context_messages:
            time_span = (
                context_messages[-1].timestamp - context_messages[0].timestamp
            ).total_seconds() / 60
        else:
            time_span = 0

        return ExtractedContext(
            messages=context_messages,
            anchor_message=anchor_context_msg,
            mention_message=mention_context_msg,
            has_reply_chain=has_reply_chain,
            total_messages=len(context_messages),
            time_span_minutes=time_span
        )

    async def _get_sender_info(self, client, message: Any) -> dict:
        """Extract sender information from message."""
        sender = getattr(message, 'sender', None)

        # Try to get sender if not cached
        if not sender:
            try:
                sender = await message.get_sender()
            except Exception:
                pass

        if not sender:
            return {'name': 'Unknown', 'username': None}

        first_name = getattr(sender, 'first_name', '') or ''
        last_name = getattr(sender, 'last_name', '') or ''
        username = getattr(sender, 'username', None)

        name = f"{first_name} {last_name}".strip() or username or 'Unknown'

        return {'name': name, 'username': username}

    def _create_minimal_context(self, mention_message: Any) -> ExtractedContext:
        """Create minimal context when fetching fails."""
        mention_ctx = ContextMessage(
            message_id=mention_message.id,
            text=mention_message.text or '',
            sender_name='Unknown',
            sender_username=None,
            timestamp=mention_message.date,
            is_anchor=False,
            is_mention=True
        )

        return ExtractedContext(
            messages=[mention_ctx],
            anchor_message=None,
            mention_message=mention_ctx,
            has_reply_chain=False,
            total_messages=1,
            time_span_minutes=0
        )

    def format_context_for_display(
        self,
        context: ExtractedContext,
        max_messages: int = 10
    ) -> str:
        """
        Format extracted context for display in notification.

        Args:
            context: Extracted context
            max_messages: Maximum messages to include

        Returns:
            Formatted context string
        """
        lines = []

        # Select most relevant messages
        messages_to_show = self._select_relevant_messages(context, max_messages)

        for msg in messages_to_show:
            prefix = ""
            if msg.is_anchor:
                prefix = "🎯 "  # Anchor indicator
            elif msg.is_mention:
                prefix = "➡️ "  # Mention indicator

            sender = f"@{msg.sender_username}" if msg.sender_username else msg.sender_name
            text = msg.text[:100] + "..." if len(msg.text) > 100 else msg.text

            lines.append(f"{prefix}[{sender}] {text}")

        return "\n".join(lines)

    def _select_relevant_messages(
        self,
        context: ExtractedContext,
        max_messages: int
    ) -> List[ContextMessage]:
        """
        Select most relevant messages from context.

        Prioritizes:
        1. Anchor message
        2. Mention message
        3. Messages closest to anchor and mention
        """
        if len(context.messages) <= max_messages:
            return context.messages

        # Always include anchor and mention
        must_include = []
        if context.anchor_message:
            must_include.append(context.anchor_message)
        if context.mention_message:
            must_include.append(context.mention_message)

        remaining_slots = max_messages - len(must_include)

        # Get messages around anchor and mention
        other_messages = [
            m for m in context.messages
            if m not in must_include
        ]

        # Split remaining slots between before anchor and after anchor
        if remaining_slots > 0:
            # Take some before anchor
            before_anchor = remaining_slots // 2
            after_anchor = remaining_slots - before_anchor

            anchor_idx = 0
            if context.anchor_message:
                for i, m in enumerate(context.messages):
                    if m.message_id == context.anchor_message.message_id:
                        anchor_idx = i
                        break

            # Messages before anchor (but after context start)
            before = [m for m in other_messages if m.timestamp < context.messages[anchor_idx].timestamp]
            # Messages after anchor (conversation continuation)
            after = [m for m in other_messages if m.timestamp >= context.messages[anchor_idx].timestamp]

            selected_before = before[-before_anchor:] if before else []
            selected_after = after[:after_anchor] if after else []

            result = selected_before + must_include + selected_after
            result.sort(key=lambda m: m.timestamp)
            return result

        return must_include

    def split_into_chunks(
        self,
        context: ExtractedContext
    ) -> List[List[ContextMessage]]:
        """
        Split context into chunks for summarization.

        Used when context is too large for a single LLM call.

        Args:
            context: Extracted context

        Returns:
            List of message chunks
        """
        messages = context.messages

        if len(messages) <= self.chunk_size:
            return [messages]

        chunks = []
        for i in range(0, len(messages), self.chunk_size):
            chunk = messages[i:i + self.chunk_size]
            chunks.append(chunk)

        logger.info(f"Split context into {len(chunks)} chunks for summarization")
        return chunks

    def estimate_tokens(self, context: ExtractedContext) -> int:
        """
        Estimate token count for context.

        Rough estimate: ~4 characters per token for Russian/English mix.

        Args:
            context: Extracted context

        Returns:
            Estimated token count
        """
        total_chars = sum(len(m.text) + len(m.sender_name) + 10 for m in context.messages)
        return total_chars // 4

    def needs_chunked_summarization(self, context: ExtractedContext) -> bool:
        """
        Check if context needs to be chunked for summarization.

        Args:
            context: Extracted context

        Returns:
            True if context should be split into chunks
        """
        estimated_tokens = self.estimate_tokens(context)
        return estimated_tokens > self.max_tokens_per_chunk


# Singleton instance
_service_instance: Optional[ContextExtractionService] = None


def get_context_extraction_service() -> ContextExtractionService:
    """Get or create context extraction service instance."""
    global _service_instance

    if _service_instance is None:
        from config import config

        _service_instance = ContextExtractionService(
            context_before_minutes=config.mention_time_limit_minutes,  # Reuse existing config
            fallback_context_minutes=60,  # 1 hour for no reply chain
            max_reply_chain_depth=50
        )
        logger.info("Context extraction service initialized")

    return _service_instance
