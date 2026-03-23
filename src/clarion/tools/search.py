"""Web search providers: DuckDuckGo, Brave, and Perplexity."""

from __future__ import annotations

import asyncio
import html as html_mod
import os
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import structlog
from ddgs import DDGS
from ddgs.exceptions import (
    DDGSException,
    RatelimitException,
    TimeoutException as DDGTimeout,
)

from clarion.secret_store import load_secret

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
PERPLEXITY_SEARCH_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"

_TAG_RE = re.compile(r"<[^>]+>")
log = structlog.get_logger()


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    return html_mod.unescape(_TAG_RE.sub("", text))


def _format_web_results(
    results: Sequence[Mapping[str, object]],
    *,
    title_key: str = "title",
    url_key: str = "url",
    desc_key: str = "description",
    strip_html: bool = False,
) -> str:
    lines = []
    for r in results[:5]:
        title = _coerce_text(r.get(title_key, ""))
        url = _coerce_text(r.get(url_key, ""))
        desc = _coerce_text(r.get(desc_key, ""))
        if strip_html:
            title = _strip_html(title)
            desc = _strip_html(desc)
        lines.append(f"- {title}\n  {url}\n  {desc}")
    return "\n\n".join(lines) if lines else "(no results)"


class DdgRateLimiter:
    """Throttles DDG calls to avoid silent rate-limiting."""

    _MIN_INTERVAL_S: float = 1.5

    def __init__(self) -> None:
        self._last_call: float = 0.0

    async def wait(self) -> None:
        delay = self._MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if delay > 0:
            await asyncio.sleep(delay)

    def mark(self) -> None:
        self._last_call = time.monotonic()


async def ddg_web_search(query: str, rate_limiter: DdgRateLimiter | None = None) -> str:
    """Search via DuckDuckGo (no API key needed)."""
    if rate_limiter is not None:
        await rate_limiter.wait()

    def _search() -> list[dict[str, str]]:
        return list(DDGS(timeout=10).text(query, max_results=5))

    for attempt in range(2):
        try:
            if rate_limiter is not None:
                rate_limiter.mark()
            results = await asyncio.wait_for(
                asyncio.to_thread(_search),
                timeout=15.0,
            )
            if not results:
                log.warning("search.ddg.empty_results", query=query)
                return "(web search returned no results)"
            return _format_web_results(
                results,
                title_key="title",
                url_key="href",
                desc_key="body",
            )
        except RatelimitException:
            return "(web search rate limited — try again shortly)"
        except (DDGTimeout, TimeoutError):
            if attempt == 0:
                continue
            return "(web search timed out — try again shortly)"
        except DDGSException as exc:
            if attempt == 0:
                continue
            log.warning(
                "ddg search failed: %s",
                exc,
            )
            return "(web search temporarily unavailable)"
    return "(web search unavailable)"


async def brave_web_search(
    query: str,
    *,
    api_key: str = "",
) -> str:
    """Call Brave Search API and return formatted results."""
    if not api_key:
        api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "BRAVE_API_KEY not set (env var or .secrets/)",
        )

    for attempt in range(2):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    BRAVE_SEARCH_URL,
                    params={"q": query, "count": 5},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": api_key,
                    },
                    timeout=10.0,
                )
            if resp.status_code == 429:
                return "(web search rate limited — try again shortly)"
            if 400 <= resp.status_code < 500:
                return f"(web search failed: HTTP {resp.status_code})"
            if resp.status_code >= 500:
                if attempt == 0:
                    continue
                return "(web search temporarily unavailable)"
            data = resp.json()
            break
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
        ):
            if attempt == 0:
                continue
            return "(web search timed out — try again shortly)"
    else:
        return "(web search unavailable)"

    results = data.get("web", {}).get("results", [])
    return _format_web_results(results, strip_html=True)


def _try_extract_text_field(item: object) -> str | None:
    """Try to extract a 'text' field from a dict-like object."""
    getter = getattr(item, "get", None)
    if getter is None:
        return None
    raw = getter("text")
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def _perplexity_content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _coerce_text(content)
    chunks: list[str] = []
    for item in content:
        extracted = _try_extract_text_field(item)
        if extracted is not None:
            chunks.append(extracted)
            continue
        text = _coerce_text(item)
        if text.strip():
            chunks.append(text)
    return "\n".join(chunks)


async def perplexity_web_search(
    query: str,
    *,
    api_key: str = "",
) -> str:
    """Call Perplexity Sonar API and return answer text with citations."""
    if not api_key:
        api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY not set (env var or .secrets/)",
        )

    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a concise web research assistant. "
                    "Answer with bullet points and include sources."
                ),
            },
            {"role": "user", "content": query},
        ],
    }

    for attempt in range(2):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    PERPLEXITY_SEARCH_URL,
                    json=payload,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    timeout=15.0,
                )
            if resp.status_code == 429:
                return "(web search rate limited — try again shortly)"
            if 400 <= resp.status_code < 500:
                return f"(web search failed: HTTP {resp.status_code})"
            if resp.status_code >= 500:
                if attempt == 0:
                    continue
                return "(web search temporarily unavailable)"
            data = resp.json()
            break
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
        ):
            if attempt == 0:
                continue
            return "(web search timed out — try again shortly)"
    else:
        return "(web search unavailable)"

    choices = data.get("choices", [])
    first_choice = choices[0] if choices else {}
    if not isinstance(first_choice, Mapping):
        first_choice = {}
    message = first_choice.get("message", {})
    if not isinstance(message, Mapping):
        message = {}
    content = _perplexity_content_to_text(
        message.get("content", ""),
    ).strip()

    citations = data.get("citations", [])
    citation_lines: list[str] = []
    if isinstance(citations, list):
        seen: set[str] = set()
        for item in citations:
            text = _coerce_text(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            citation_lines.append(f"- {text}")

    if citation_lines:
        citations_text = "Sources:\n" + "\n".join(citation_lines)
        if content:
            return f"{content}\n\n{citations_text}"
        return citations_text
    return content or "(no results)"


async def resolve_search(
    query: str,
    *,
    ddg_rate_limiter: DdgRateLimiter | None = None,
) -> str:
    """Pick the best available search provider and run the query."""
    perplexity_key = load_secret("perplexity_api_key")
    if perplexity_key:
        return await perplexity_web_search(query, api_key=perplexity_key)
    brave_key = load_secret("brave_api_key")
    if brave_key:
        return await brave_web_search(query, api_key=brave_key)
    return await ddg_web_search(query, rate_limiter=ddg_rate_limiter)


# ---------------------------------------------------------------------------
# ToolHandler
# ---------------------------------------------------------------------------

from clarion.boundary_validation import MAX_QUERY_LEN, BoundaryValidationError
from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class WebSearchHandler(ToolHandler):
    def __init__(self, ddg_rate_limiter: DdgRateLimiter) -> None:
        self._ddg_rate_limiter = ddg_rate_limiter

    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        query = str(arguments.get("query", ""))
        if len(query) > MAX_QUERY_LEN:
            raise BoundaryValidationError(
                f"Query exceeds maximum length of {MAX_QUERY_LEN} characters"
            )
        return arguments

    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        text = await resolve_search(
            str(arguments["query"]),
            ddg_rate_limiter=self._ddg_rate_limiter,
        )
        return ToolResult(text=text, wraps_untrusted_content=True)
