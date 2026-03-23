# Plan 04 — Adapters (Layer 4)

## Goal

Implement the Telegram delivery adapter. After this plan, `deliver_output`
can send messages to Telegram chats via the Bot API.

This layer depends on foundation (layer 0) only. It implements the
`DeliveryAdapter` protocol defined in `models.py`.

---

## Dependencies

```python
# From layer 0
from clarion.models import DeliveryAdapter
```

External:
- `httpx` — for HTTP POST to Telegram Bot API

---

## Module: `adapters/telegram.py`

**Purpose:** Send messages to Telegram chats via the Bot API. This is
the outbound-only adapter — Clarion agents don't receive inbound
Telegram messages (they're background agents, not chatbots).

**Source:** New. Much simpler than redclaw's `telegram_adapter.py` which
handles inbound polling, streaming edits, file uploads, etc. Clarion
only needs outbound POST.

### Implementation

```python
"""Telegram delivery adapter for Clarion.

Sends messages to Telegram chats via the Bot API. Outbound only —
Clarion agents don't receive inbound messages.
"""

from __future__ import annotations

import structlog
import httpx

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
        # Telegram has a 4096-char limit per message.
        # If content exceeds this, split into chunks.
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
```

### Environment variables

- `TELEGRAM_BOT_TOKEN` — the bot token, set globally for the platform.
  One bot serves all agents. Loaded by the CLI/daemon and passed to
  TelegramAdapter's constructor.

### Markdown handling

Telegram uses its own Markdown variant. The adapter sends with
`parse_mode: "Markdown"`. If parsing fails (agent produces content that
breaks Telegram's parser), it retries without parse_mode to ensure the
message is delivered, even if unformatted.

### Message splitting

Telegram limits messages to 4096 characters. Long outputs (like a weekly
briefing) are split at paragraph boundaries, then line boundaries, then
hard character limits. Each chunk is sent as a separate message.

### Tests

- Test deliver sends POST to correct URL with correct payload
- Test long message is split at paragraph boundaries
- Test Markdown parse failure triggers retry without parse_mode
- Test API error raises RuntimeError
- Test missing bot_token raises ValueError
- Test _split_message: short message → 1 chunk, long message → multiple

Use `pytest-mock` or `respx` to mock httpx calls. Do NOT make real
Telegram API calls in tests.

---

## Wiring into the executor

The TelegramAdapter is instantiated in the CLI/daemon and passed to
ToolExecutor via `delivery_adapters`:

```python
# In cli.py or daemon.py
import os
from clarion.models import OutputType
from clarion.adapters.telegram import TelegramAdapter

adapters = {}
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if bot_token:
    adapters[OutputType.TELEGRAM] = TelegramAdapter(bot_token)

executor = ToolExecutor(
    ...,
    delivery_adapters=adapters,
)
```

If `TELEGRAM_BOT_TOKEN` is not set, the adapter is simply not available.
The deliver_output tool returns a clear error message ("No delivery
adapter configured for output type: telegram") rather than crashing.

---

## Future adapters (not Phase 1)

When adding new adapters, follow the same pattern:

- Implement in `adapters/<name>.py`
- Satisfy the `DeliveryAdapter` protocol from `models.py`
- Add to the `delivery_adapters` dict in the CLI/daemon

Planned:
- `adapters/email.py` — SMTP or API-based email delivery
- `adapters/webhook.py` — generic HTTP POST to a URL

---

## Verification

```bash
# Imports work
uv run python -c "
from clarion.adapters.telegram import TelegramAdapter
print('Telegram adapter import OK')
"

# Unit tests pass
uv run pytest tests/test_telegram_adapter.py -x -v
```
