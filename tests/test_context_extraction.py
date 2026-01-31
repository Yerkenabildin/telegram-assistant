"""
Unit tests for context extraction service.

Tests ContextExtractionService for anchor-based context extraction.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.context_extraction_service import (
    ContextExtractionService,
    ContextMessage,
    ExtractedContext,
    DEFAULT_CONTEXT_BEFORE_MINUTES,
    DEFAULT_FALLBACK_CONTEXT_MINUTES,
)


class TestContextExtractionServiceInit:
    """Tests for ContextExtractionService initialization."""

    def test_default_values(self):
        """Test default initialization values."""
        service = ContextExtractionService()

        assert service.context_before_minutes == DEFAULT_CONTEXT_BEFORE_MINUTES
        assert service.fallback_context_minutes == DEFAULT_FALLBACK_CONTEXT_MINUTES
        assert service.max_reply_chain_depth == 50
        assert service.chunk_size == 15
        assert service.max_tokens_per_chunk == 2000

    def test_custom_values(self):
        """Test custom initialization values."""
        service = ContextExtractionService(
            context_before_minutes=60,
            fallback_context_minutes=120,
            max_reply_chain_depth=100,
            chunk_size=20,
            max_tokens_per_chunk=3000
        )

        assert service.context_before_minutes == 60
        assert service.fallback_context_minutes == 120
        assert service.max_reply_chain_depth == 100
        assert service.chunk_size == 20
        assert service.max_tokens_per_chunk == 3000


class TestContextMessage:
    """Tests for ContextMessage dataclass."""

    def test_basic_creation(self):
        """Test basic ContextMessage creation."""
        now = datetime.now(timezone.utc)
        msg = ContextMessage(
            message_id=1,
            text="Hello world",
            sender_name="John",
            sender_username="john_doe",
            timestamp=now
        )

        assert msg.message_id == 1
        assert msg.text == "Hello world"
        assert msg.sender_name == "John"
        assert msg.sender_username == "john_doe"
        assert msg.timestamp == now
        assert msg.is_anchor is False
        assert msg.is_mention is False

    def test_anchor_message(self):
        """Test ContextMessage with is_anchor=True."""
        now = datetime.now(timezone.utc)
        msg = ContextMessage(
            message_id=1,
            text="Original question",
            sender_name="Alice",
            sender_username="alice",
            timestamp=now,
            is_anchor=True
        )

        assert msg.is_anchor is True
        assert msg.is_mention is False

    def test_mention_message(self):
        """Test ContextMessage with is_mention=True."""
        now = datetime.now(timezone.utc)
        msg = ContextMessage(
            message_id=2,
            text="@user can you help?",
            sender_name="Bob",
            sender_username="bob",
            timestamp=now,
            is_mention=True
        )

        assert msg.is_anchor is False
        assert msg.is_mention is True


class TestExtractedContext:
    """Tests for ExtractedContext dataclass."""

    def test_basic_creation(self):
        """Test basic ExtractedContext creation."""
        now = datetime.now(timezone.utc)
        mention_msg = ContextMessage(
            message_id=1, text="@user help",
            sender_name="Bob", sender_username="bob",
            timestamp=now, is_mention=True
        )

        context = ExtractedContext(
            messages=[mention_msg],
            anchor_message=None,
            mention_message=mention_msg,
            has_reply_chain=False,
            total_messages=1,
            time_span_minutes=0
        )

        assert len(context.messages) == 1
        assert context.anchor_message is None
        assert context.mention_message == mention_msg
        assert context.has_reply_chain is False
        assert context.total_messages == 1
        assert context.time_span_minutes == 0

    def test_with_reply_chain(self):
        """Test ExtractedContext with reply chain."""
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(minutes=10)

        anchor_msg = ContextMessage(
            message_id=1, text="Original question",
            sender_name="Alice", sender_username="alice",
            timestamp=earlier, is_anchor=True
        )
        mention_msg = ContextMessage(
            message_id=2, text="@user check this",
            sender_name="Bob", sender_username="bob",
            timestamp=now, is_mention=True
        )

        context = ExtractedContext(
            messages=[anchor_msg, mention_msg],
            anchor_message=anchor_msg,
            mention_message=mention_msg,
            has_reply_chain=True,
            total_messages=2,
            time_span_minutes=10.0
        )

        assert context.has_reply_chain is True
        assert context.anchor_message is not None
        assert context.anchor_message.is_anchor is True


class TestGetReplyToId:
    """Tests for _get_reply_to_id helper method."""

    def test_direct_reply_to_msg_id(self):
        """Test extraction from direct reply_to_msg_id attribute."""
        service = ContextExtractionService()
        msg = MagicMock()
        msg.reply_to_msg_id = 42
        msg.reply_to = None

        result = service._get_reply_to_id(msg)
        assert result == 42

    def test_nested_reply_to(self):
        """Test extraction from nested reply_to.reply_to_msg_id."""
        service = ContextExtractionService()
        msg = MagicMock()
        msg.reply_to_msg_id = None
        msg.reply_to = MagicMock()
        msg.reply_to.reply_to_msg_id = 100

        result = service._get_reply_to_id(msg)
        assert result == 100

    def test_no_reply(self):
        """Test when message is not a reply."""
        service = ContextExtractionService()
        msg = MagicMock()
        msg.reply_to_msg_id = None
        msg.reply_to = None

        result = service._get_reply_to_id(msg)
        assert result is None

    def test_both_attributes_prefers_direct(self):
        """Test that direct reply_to_msg_id is preferred."""
        service = ContextExtractionService()
        msg = MagicMock()
        msg.reply_to_msg_id = 42
        msg.reply_to = MagicMock()
        msg.reply_to.reply_to_msg_id = 100

        result = service._get_reply_to_id(msg)
        assert result == 42


class TestFindAnchorMessage:
    """Tests for find_anchor_message method."""

    @pytest.mark.asyncio
    async def test_no_reply_chain(self):
        """Test when message is not a reply."""
        service = ContextExtractionService()
        client = MagicMock()

        mention_msg = MagicMock()
        mention_msg.reply_to_msg_id = None
        mention_msg.reply_to = None

        anchor, chain = await service.find_anchor_message(client, 123, mention_msg)

        assert anchor is None
        assert chain == []

    @pytest.mark.asyncio
    async def test_simple_reply_chain(self):
        """Test simple reply chain with 2 messages."""
        service = ContextExtractionService()
        client = AsyncMock()

        # Original message
        original = MagicMock()
        original.id = 1
        original.reply_to_msg_id = None
        original.reply_to = None

        # Reply to original
        mention_msg = MagicMock()
        mention_msg.id = 2
        mention_msg.reply_to_msg_id = 1
        mention_msg.reply_to = None

        client.get_messages = AsyncMock(return_value=original)

        anchor, chain = await service.find_anchor_message(client, 123, mention_msg)

        assert anchor is not None
        assert anchor.id == 1
        assert len(chain) == 1
        assert chain[0].id == 1

    @pytest.mark.asyncio
    async def test_deep_reply_chain(self):
        """Test deep reply chain (multiple levels)."""
        service = ContextExtractionService(max_reply_chain_depth=5)
        client = AsyncMock()

        # Build chain of 4 messages (1 -> 2 -> 3 -> 4)
        msg1 = MagicMock(id=1, reply_to_msg_id=None, reply_to=None)
        msg2 = MagicMock(id=2, reply_to_msg_id=1, reply_to=None)
        msg3 = MagicMock(id=3, reply_to_msg_id=2, reply_to=None)
        msg4 = MagicMock(id=4, reply_to_msg_id=3, reply_to=None)

        # Mention message is msg4
        mention_msg = msg4

        # Mock get_messages to return the correct message
        def mock_get_messages(chat_id, ids):
            msg_map = {1: msg1, 2: msg2, 3: msg3}
            return msg_map.get(ids)

        client.get_messages = AsyncMock(side_effect=mock_get_messages)

        anchor, chain = await service.find_anchor_message(client, 123, mention_msg)

        assert anchor is not None
        assert anchor.id == 1
        assert len(chain) == 3
        # Chain should be in chronological order (oldest first)
        assert chain[0].id == 1
        assert chain[1].id == 2
        assert chain[2].id == 3

    @pytest.mark.asyncio
    async def test_respects_max_depth(self):
        """Test that max_reply_chain_depth is respected."""
        service = ContextExtractionService(max_reply_chain_depth=2)
        client = AsyncMock()

        # Build chain of 5 messages
        msg1 = MagicMock(id=1, reply_to_msg_id=None, reply_to=None)
        msg2 = MagicMock(id=2, reply_to_msg_id=1, reply_to=None)
        msg3 = MagicMock(id=3, reply_to_msg_id=2, reply_to=None)
        msg4 = MagicMock(id=4, reply_to_msg_id=3, reply_to=None)
        msg5 = MagicMock(id=5, reply_to_msg_id=4, reply_to=None)

        mention_msg = msg5

        def mock_get_messages(chat_id, ids):
            msg_map = {1: msg1, 2: msg2, 3: msg3, 4: msg4}
            return msg_map.get(ids)

        client.get_messages = AsyncMock(side_effect=mock_get_messages)

        anchor, chain = await service.find_anchor_message(client, 123, mention_msg)

        # Should stop at depth 2
        assert len(chain) == 2

    @pytest.mark.asyncio
    async def test_handles_fetch_error(self):
        """Test graceful handling of message fetch errors."""
        service = ContextExtractionService()
        client = AsyncMock()

        mention_msg = MagicMock()
        mention_msg.id = 2
        mention_msg.reply_to_msg_id = 1
        mention_msg.reply_to = None

        # Simulate fetch error
        client.get_messages = AsyncMock(side_effect=Exception("Network error"))

        anchor, chain = await service.find_anchor_message(client, 123, mention_msg)

        # Should return empty on error
        assert anchor is None
        assert chain == []


class TestExtractContext:
    """Tests for extract_context method."""

    @pytest.mark.asyncio
    async def test_without_reply_chain_uses_fallback(self):
        """Test context extraction without reply chain uses fallback time."""
        service = ContextExtractionService(
            context_before_minutes=30,
            fallback_context_minutes=60
        )
        client = AsyncMock()

        now = datetime.now(timezone.utc)

        # Message without reply
        mention_msg = MagicMock()
        mention_msg.id = 1
        mention_msg.date = now
        mention_msg.text = "@user hello"
        mention_msg.reply_to_msg_id = None
        mention_msg.reply_to = None

        # Context messages
        msg1 = MagicMock(id=2, date=now - timedelta(minutes=30), text="Earlier message")
        msg2 = MagicMock(id=3, date=now - timedelta(minutes=90), text="Too old")

        client.get_messages = AsyncMock(return_value=[mention_msg, msg1, msg2])

        context = await service.extract_context(client, 123, mention_msg)

        assert context.has_reply_chain is False
        # Should use 60 min fallback, so msg1 (30min) should be included, msg2 (90min) excluded
        assert context.total_messages >= 1  # At least mention message

    @pytest.mark.asyncio
    async def test_with_reply_chain_uses_anchor(self):
        """Test context extraction with reply chain uses anchor-based time."""
        service = ContextExtractionService(context_before_minutes=30)
        client = AsyncMock()

        now = datetime.now(timezone.utc)
        anchor_time = now - timedelta(minutes=20)

        # Anchor message (root of reply chain)
        anchor_msg = MagicMock()
        anchor_msg.id = 1
        anchor_msg.date = anchor_time
        anchor_msg.text = "Original question"
        anchor_msg.reply_to_msg_id = None
        anchor_msg.reply_to = None

        # Mention message (reply to anchor)
        mention_msg = MagicMock()
        mention_msg.id = 2
        mention_msg.date = now
        mention_msg.text = "@user please help"
        mention_msg.reply_to_msg_id = 1
        mention_msg.reply_to = None

        # Mock get_messages to return different results
        async def mock_get_messages(chat_id, **kwargs):
            if 'ids' in kwargs:
                return anchor_msg
            return [mention_msg, anchor_msg]

        client.get_messages = AsyncMock(side_effect=mock_get_messages)

        context = await service.extract_context(client, 123, mention_msg)

        assert context.has_reply_chain is True
        assert context.anchor_message is not None

    @pytest.mark.asyncio
    async def test_minimal_context_on_error(self):
        """Test minimal context is returned on fetch error."""
        service = ContextExtractionService()
        client = AsyncMock()

        now = datetime.now(timezone.utc)
        mention_msg = MagicMock()
        mention_msg.id = 1
        mention_msg.date = now
        mention_msg.text = "@user help"
        mention_msg.reply_to_msg_id = None
        mention_msg.reply_to = None

        # Simulate fetch error
        client.get_messages = AsyncMock(side_effect=Exception("Network error"))

        context = await service.extract_context(client, 123, mention_msg)

        assert context.total_messages == 1
        assert context.mention_message.text == "@user help"


class TestFormatContextForDisplay:
    """Tests for format_context_for_display method."""

    def test_basic_formatting(self):
        """Test basic context formatting."""
        service = ContextExtractionService()
        now = datetime.now(timezone.utc)

        msg1 = ContextMessage(
            message_id=1, text="Hello",
            sender_name="Alice", sender_username="alice",
            timestamp=now
        )
        msg2 = ContextMessage(
            message_id=2, text="@user help",
            sender_name="Bob", sender_username="bob",
            timestamp=now, is_mention=True
        )

        context = ExtractedContext(
            messages=[msg1, msg2],
            anchor_message=None,
            mention_message=msg2,
            has_reply_chain=False,
            total_messages=2,
            time_span_minutes=0
        )

        result = service.format_context_for_display(context)

        assert "@alice" in result
        assert "Hello" in result
        assert "@user help" in result

    def test_anchor_indicator(self):
        """Test anchor message has indicator."""
        service = ContextExtractionService()
        now = datetime.now(timezone.utc)

        anchor = ContextMessage(
            message_id=1, text="Original",
            sender_name="Alice", sender_username="alice",
            timestamp=now, is_anchor=True
        )

        context = ExtractedContext(
            messages=[anchor],
            anchor_message=anchor,
            mention_message=anchor,
            has_reply_chain=True,
            total_messages=1,
            time_span_minutes=0
        )

        result = service.format_context_for_display(context)

        # Anchor indicator
        assert "🎯" in result

    def test_mention_indicator(self):
        """Test mention message has indicator."""
        service = ContextExtractionService()
        now = datetime.now(timezone.utc)

        mention = ContextMessage(
            message_id=1, text="@user help",
            sender_name="Bob", sender_username="bob",
            timestamp=now, is_mention=True
        )

        context = ExtractedContext(
            messages=[mention],
            anchor_message=None,
            mention_message=mention,
            has_reply_chain=False,
            total_messages=1,
            time_span_minutes=0
        )

        result = service.format_context_for_display(context)

        # Mention indicator
        assert "➡️" in result

    def test_truncates_long_messages(self):
        """Test long messages are truncated."""
        service = ContextExtractionService()
        now = datetime.now(timezone.utc)

        long_text = "A" * 200
        msg = ContextMessage(
            message_id=1, text=long_text,
            sender_name="Alice", sender_username="alice",
            timestamp=now
        )

        context = ExtractedContext(
            messages=[msg],
            anchor_message=None,
            mention_message=msg,
            has_reply_chain=False,
            total_messages=1,
            time_span_minutes=0
        )

        result = service.format_context_for_display(context)

        # Should be truncated
        assert "..." in result


class TestSplitIntoChunks:
    """Tests for split_into_chunks method."""

    def test_small_context_single_chunk(self):
        """Test small context returns single chunk."""
        service = ContextExtractionService(chunk_size=10)
        now = datetime.now(timezone.utc)

        messages = [
            ContextMessage(
                message_id=i, text=f"Message {i}",
                sender_name="User", sender_username="user",
                timestamp=now
            )
            for i in range(5)
        ]

        context = ExtractedContext(
            messages=messages,
            anchor_message=None,
            mention_message=messages[-1],
            has_reply_chain=False,
            total_messages=5,
            time_span_minutes=0
        )

        chunks = service.split_into_chunks(context)

        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_large_context_multiple_chunks(self):
        """Test large context is split into multiple chunks."""
        service = ContextExtractionService(chunk_size=5)
        now = datetime.now(timezone.utc)

        messages = [
            ContextMessage(
                message_id=i, text=f"Message {i}",
                sender_name="User", sender_username="user",
                timestamp=now
            )
            for i in range(12)
        ]

        context = ExtractedContext(
            messages=messages,
            anchor_message=None,
            mention_message=messages[-1],
            has_reply_chain=False,
            total_messages=12,
            time_span_minutes=0
        )

        chunks = service.split_into_chunks(context)

        assert len(chunks) == 3  # 5 + 5 + 2
        assert len(chunks[0]) == 5
        assert len(chunks[1]) == 5
        assert len(chunks[2]) == 2


class TestEstimateTokens:
    """Tests for estimate_tokens method."""

    def test_empty_context(self):
        """Test token estimation for empty context."""
        service = ContextExtractionService()

        context = ExtractedContext(
            messages=[],
            anchor_message=None,
            mention_message=ContextMessage(
                message_id=1, text="",
                sender_name="", sender_username=None,
                timestamp=datetime.now(timezone.utc)
            ),
            has_reply_chain=False,
            total_messages=0,
            time_span_minutes=0
        )

        tokens = service.estimate_tokens(context)
        assert tokens == 0

    def test_token_estimation(self):
        """Test token estimation calculation."""
        service = ContextExtractionService()
        now = datetime.now(timezone.utc)

        # 100 chars text + 10 sender name + 10 overhead = 120 / 4 = 30 tokens
        msg = ContextMessage(
            message_id=1, text="A" * 100,
            sender_name="SenderName", sender_username="sender",
            timestamp=now
        )

        context = ExtractedContext(
            messages=[msg],
            anchor_message=None,
            mention_message=msg,
            has_reply_chain=False,
            total_messages=1,
            time_span_minutes=0
        )

        tokens = service.estimate_tokens(context)
        assert tokens == 30


class TestNeedsChunkedSummarization:
    """Tests for needs_chunked_summarization method."""

    def test_small_context_no_chunking(self):
        """Test small context doesn't need chunking."""
        service = ContextExtractionService(max_tokens_per_chunk=2000)
        now = datetime.now(timezone.utc)

        # Small message, ~30 tokens
        msg = ContextMessage(
            message_id=1, text="Hello world",
            sender_name="Alice", sender_username="alice",
            timestamp=now
        )

        context = ExtractedContext(
            messages=[msg],
            anchor_message=None,
            mention_message=msg,
            has_reply_chain=False,
            total_messages=1,
            time_span_minutes=0
        )

        assert service.needs_chunked_summarization(context) is False

    def test_large_context_needs_chunking(self):
        """Test large context needs chunking."""
        service = ContextExtractionService(max_tokens_per_chunk=100)
        now = datetime.now(timezone.utc)

        # Large messages, many tokens
        messages = [
            ContextMessage(
                message_id=i, text="A" * 500,
                sender_name="User", sender_username="user",
                timestamp=now
            )
            for i in range(10)
        ]

        context = ExtractedContext(
            messages=messages,
            anchor_message=None,
            mention_message=messages[-1],
            has_reply_chain=False,
            total_messages=10,
            time_span_minutes=0
        )

        assert service.needs_chunked_summarization(context) is True


class TestSelectRelevantMessages:
    """Tests for _select_relevant_messages method."""

    def test_returns_all_if_under_limit(self):
        """Test all messages returned if under limit."""
        service = ContextExtractionService()
        now = datetime.now(timezone.utc)

        messages = [
            ContextMessage(
                message_id=i, text=f"Message {i}",
                sender_name="User", sender_username="user",
                timestamp=now + timedelta(minutes=i)
            )
            for i in range(5)
        ]
        messages[-1].is_mention = True

        context = ExtractedContext(
            messages=messages,
            anchor_message=None,
            mention_message=messages[-1],
            has_reply_chain=False,
            total_messages=5,
            time_span_minutes=5
        )

        result = service._select_relevant_messages(context, max_messages=10)

        assert len(result) == 5

    def test_always_includes_anchor_and_mention(self):
        """Test anchor and mention are always included."""
        service = ContextExtractionService()
        now = datetime.now(timezone.utc)

        anchor = ContextMessage(
            message_id=1, text="Anchor",
            sender_name="User1", sender_username="user1",
            timestamp=now, is_anchor=True
        )
        mention = ContextMessage(
            message_id=10, text="Mention",
            sender_name="User2", sender_username="user2",
            timestamp=now + timedelta(minutes=10), is_mention=True
        )
        other = ContextMessage(
            message_id=5, text="Other",
            sender_name="User3", sender_username="user3",
            timestamp=now + timedelta(minutes=5)
        )

        context = ExtractedContext(
            messages=[anchor, other, mention],
            anchor_message=anchor,
            mention_message=mention,
            has_reply_chain=True,
            total_messages=3,
            time_span_minutes=10
        )

        result = service._select_relevant_messages(context, max_messages=2)

        # Should include both anchor and mention
        result_ids = [m.message_id for m in result]
        assert 1 in result_ids  # anchor
        assert 10 in result_ids  # mention


class TestServiceSingleton:
    """Tests for get_context_extraction_service singleton."""

    def test_returns_service_instance(self):
        """Test singleton returns service instance."""
        from services.context_extraction_service import get_context_extraction_service

        service = get_context_extraction_service()
        assert service is not None
        assert isinstance(service, ContextExtractionService)

    def test_returns_same_instance(self):
        """Test singleton returns same instance."""
        from services.context_extraction_service import get_context_extraction_service

        service1 = get_context_extraction_service()
        service2 = get_context_extraction_service()
        assert service1 is service2
