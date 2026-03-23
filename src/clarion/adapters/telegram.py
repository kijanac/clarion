"""Telegram delivery adapter for Clarion.

Sends messages to Telegram chats via the Bot API. Outbound only —
Clarion agents don't receive inbound messages.
"""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()

# Telegram message length limit
_MAX_MESSAGE_LENGTH = 4096


class TelegramAdapter:
    """Delivers output to a Telegram chat via the Bot API.

    Implements the DeliveryAdapter protocol from clarion.models.
    """

    def __init__(self, bot_token: str) -> None:
        if not bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self._bot_token = bot_token
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    async def deliver(
        self,
        destination: str,
        content: str,
        output_name: str,
    ) -> str:
        """Send content to a Telegram chat.

        Args:
            destination: Telegram chat_id (numeric string or @channel)
            content: Message content (Markdown)
            output_name: Name of the output (for logging)

        Returns:
            Confirmation message string.
        """
        chunks = _split_message(content)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, chunk in enumerate(chunks):
                payload = {
                    "chat_id": destination,
                    "text": chunk,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                }

                response = await client.post(
                    f"{self._base_url}/sendMessage",
                    json=payload,
                )

                if response.status_code != 200:
                    error_body = response.text
                    log.error(
                        "telegram.send_failed",
                        status=response.status_code,
                        error=error_body,
                        output_name=output_name,
                        chunk=i + 1,
                    )
                    # If Markdown parsing fails, retry without parse_mode
                    if "can't parse" in error_body.lower():
                        payload.pop("parse_mode")
                        retry = await client.post(
                            f"{self._base_url}/sendMessage",
                            json=payload,
                        )
                        if retry.status_code != 200:
                            raise RuntimeError(
                                f"Telegram API error: {retry.status_code} {retry.text}"
                            )
                    else:
                        raise RuntimeError(
                            f"Telegram API error: {response.status_code} {error_body}"
                        )

                log.info(
                    "telegram.sent",
                    output_name=output_name,
                    chat_id=destination,
                    chunk=i + 1,
                    total_chunks=len(chunks),
                )

        return f"Delivered '{output_name}' to Telegram ({len(chunks)} message(s))"


def _split_message(content: str) -> list[str]:
    """Split a message into chunks that fit Telegram's limit.

    Tries to split at paragraph boundaries first, then line boundaries,
    then hard-splits at the character limit.
    """
    if len(content) <= _MAX_MESSAGE_LENGTH:
        return [content]

    chunks: list[str] = []
    remaining = content

    while remaining:
        if len(remaining) <= _MAX_MESSAGE_LENGTH:
            chunks.append(remaining)
            break

        # Try to find a paragraph break within the limit
        split_at = remaining.rfind("\n\n", 0, _MAX_MESSAGE_LENGTH)
        if split_at == -1:
            # Try a line break
            split_at = remaining.rfind("\n", 0, _MAX_MESSAGE_LENGTH)
        if split_at == -1:
            # Hard split
            split_at = _MAX_MESSAGE_LENGTH

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks
