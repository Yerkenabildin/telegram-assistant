"""
Yandex GPT service for AI-powered text analysis.

Provides summarization and urgency detection for mention notifications.
"""
import aiohttp
from typing import Optional, Tuple
import json

from logging_config import get_logger

logger = get_logger('yandex_gpt')

# Yandex GPT API endpoint
YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class YandexGPTService:
    """
    Service for Yandex GPT API calls.

    Provides:
    - Message summarization
    - Urgency detection

    Supports two authentication methods:
    - API Key (starts with "AQVN" or similar)
    - IAM Token (starts with "t1." or obtained via yc iam create-token)
    """

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        model: str = "yandexgpt-lite",
        timeout: int = 10
    ):
        """
        Initialize Yandex GPT service.

        Args:
            api_key: Yandex Cloud API key or IAM token
            folder_id: Yandex Cloud folder ID
            model: Model name (yandexgpt-lite or yandexgpt)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.folder_id = folder_id
        self.model = model
        self.timeout = timeout
        self.model_uri = f"gpt://{folder_id}/{model}"

        # Detect auth type: IAM tokens usually start with "t1."
        self.is_iam_token = api_key.startswith("t1.")

    async def summarize_mention(
        self,
        messages: list[str],
        mention_message: str,
        chat_title: str
    ) -> Tuple[str, bool]:
        """
        Summarize mention context and detect urgency using Yandex GPT.

        Args:
            messages: List of context messages (oldest first)
            mention_message: The message that contains the mention
            chat_title: Name of the chat

        Returns:
            Tuple of (summary text, is_urgent)
        """
        # Build context for LLM
        context_text = "\n".join(f"- {msg}" for msg in messages[-5:])  # Last 5 messages

        prompt = f"""Проанализируй переписку из группового чата "{chat_title}" и кратко ответь:

Контекст переписки:
{context_text}

Сообщение с упоминанием пользователя:
{mention_message}

Ответь строго в формате:
ПРИЧИНА: [одно предложение - зачем призвали пользователя]
СРОЧНОСТЬ: [да/нет - требуется ли немедленная реакция]
КРАТКОЕ РЕЗЮМЕ: [2-3 предложения о сути обсуждения]"""

        try:
            response = await self._call_api(prompt)
            if response:
                return self._parse_response(response)
        except Exception as e:
            logger.error(f"Yandex GPT error: {e}")

        # Fallback
        return None, None

    async def _call_api(self, prompt: str) -> Optional[str]:
        """
        Call Yandex GPT API.

        Args:
            prompt: Text prompt for the model

        Returns:
            Model response text or None on error
        """
        # Support both API key and IAM token authentication
        if self.is_iam_token:
            auth_header = f"Bearer {self.api_key}"
        else:
            auth_header = f"Api-Key {self.api_key}"

        headers = {
            "Content-Type": "application/json",
            "Authorization": auth_header,
            "x-folder-id": self.folder_id
        }

        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.3,  # Low temperature for factual responses
                "maxTokens": 500
            },
            "messages": [
                {
                    "role": "system",
                    "text": "Ты помощник, который анализирует переписки и кратко суммаризирует причину упоминания пользователя. Отвечай кратко и по делу."
                },
                {
                    "role": "user",
                    "text": prompt
                }
            ]
        }

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(YANDEX_GPT_URL, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Extract text from response
                        alternatives = data.get("result", {}).get("alternatives", [])
                        if alternatives:
                            return alternatives[0].get("message", {}).get("text", "")
                    else:
                        error_text = await response.text()
                        logger.error(f"Yandex GPT API error {response.status}: {error_text}")
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"Yandex GPT request failed: {e}")
            return None

        return None

    def _parse_response(self, response: str) -> Tuple[str, bool]:
        """
        Parse LLM response to extract summary and urgency.

        Args:
            response: Raw LLM response text

        Returns:
            Tuple of (formatted summary, is_urgent)
        """
        lines = response.strip().split('\n')

        reason = ""
        is_urgent = False
        summary = ""

        for line in lines:
            line = line.strip()
            if line.upper().startswith("ПРИЧИНА:"):
                reason = line[8:].strip()
            elif line.upper().startswith("СРОЧНОСТЬ:"):
                urgency_text = line[10:].strip().lower()
                is_urgent = urgency_text in ["да", "yes", "true", "срочно", "высокая"]
            elif line.upper().startswith("КРАТКОЕ РЕЗЮМЕ:") or line.upper().startswith("РЕЗЮМЕ:"):
                summary = line.split(":", 1)[1].strip() if ":" in line else ""

        # Format output
        parts = []
        if reason:
            parts.append(f"📌 Причина: {reason}")
        if summary:
            parts.append(f"💬 {summary}")

        formatted = "\n".join(parts) if parts else response[:200]

        return formatted, is_urgent


# Singleton instance (created when config is available)
_service_instance: Optional[YandexGPTService] = None


def get_yandex_gpt_service() -> Optional[YandexGPTService]:
    """
    Get or create Yandex GPT service instance.

    Returns:
        YandexGPTService instance or None if not configured
    """
    global _service_instance

    if _service_instance is not None:
        return _service_instance

    from config import config

    if not config.yandex_api_key or not config.yandex_folder_id:
        logger.debug("Yandex GPT not configured (missing API key or folder ID)")
        return None

    _service_instance = YandexGPTService(
        api_key=config.yandex_api_key,
        folder_id=config.yandex_folder_id,
        model=config.yandex_gpt_model
    )

    logger.info(f"Yandex GPT service initialized (model: {config.yandex_gpt_model})")
    return _service_instance
