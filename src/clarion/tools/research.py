"""Deep research: search + parallel fetch + structured report."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from clarion.boundary_validation import MAX_FETCH_CONTENT_LEN, MAX_RESEARCH_SOURCES
from clarion.tools.fetch import _UNTRUSTED_WEB_OVERHEAD, web_fetch_url
from clarion.tools.fetch_cache import FetchCache
from clarion.tools.search import DdgRateLimiter, resolve_search

DEFAULT_MAX_SOURCES = 5
_RESEARCH_TIMEOUT_S = 60.0

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_MAX_SEARCH_DISPLAY_LEN = 8000

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "i",
        "me",
        "my",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "and",
        "or",
        "but",
        "not",
        "if",
        "so",
        "just",
    }
)


def _make_keyword_query(question: str) -> str:
    """Extract keywords from a question, dropping stop words."""
    words = re.findall(r"\w+", question.lower())
    keywords = [w for w in words if w not in _STOP_WORDS]
    return " ".join(keywords)


def _extract_urls(text: str) -> list[str]:
    """Extract unique URLs from formatted search results."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:)]}\"'")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _build_queries(question: str) -> list[str]:
    """Generate search queries from a research question."""
    queries = [question]
    keyword_query = _make_keyword_query(question)
    # Normalize original the same way to avoid near-duplicate searches.
    normalized = " ".join(re.findall(r"\w+", question.lower()))
    if keyword_query and keyword_query != normalized:
        queries.append(keyword_query)
    return queries


async def _fetch_source(
    url: str,
    budget: int,
    cache: FetchCache | None = None,
) -> tuple[str, str]:
    """Fetch and convert a URL. Returns (url, content_or_error_note)."""
    md = await web_fetch_url(url, cache=cache)
    return url, md[:budget]


async def deep_research(
    question: str,
    *,
    max_sources: int = DEFAULT_MAX_SOURCES,
    workspace_root: Path | None = None,
    agent_id: str = "",
    cache: FetchCache | None = None,
    ddg_rate_limiter: DdgRateLimiter | None = None,
) -> str:
    """Search the web, fetch top results in parallel, return a structured report."""
    try:
        return await asyncio.wait_for(
            _deep_research_inner(
                question,
                max_sources=max_sources,
                workspace_root=workspace_root,
                agent_id=agent_id,
                cache=cache,
                ddg_rate_limiter=ddg_rate_limiter,
            ),
            timeout=_RESEARCH_TIMEOUT_S,
        )
    except TimeoutError:
        return (
            f"## Research: {question}\n\n"
            "(research timed out — the search or one of the sources "
            "took too long to respond; try again or narrow the question)"
        )


async def _deep_research_inner(
    question: str,
    *,
    max_sources: int = DEFAULT_MAX_SOURCES,
    workspace_root: Path | None = None,
    agent_id: str = "",
    cache: FetchCache | None = None,
    ddg_rate_limiter: DdgRateLimiter | None = None,
) -> str:
    """Inner implementation wrapped by the timeout in deep_research."""
    queries = _build_queries(question)

    # Run all searches concurrently.
    search_tasks = [
        resolve_search(
            q,
            workspace_root=workspace_root,
            agent_id=agent_id,
            ddg_rate_limiter=ddg_rate_limiter,
        )
        for q in queries
    ]
    search_results = await asyncio.gather(*search_tasks)

    combined_search = "\n\n".join(search_results)
    urls = _extract_urls(combined_search)

    if not urls:
        return (
            f"## Research: {question}\n\n"
            f"{combined_search}\n\n"
            "(no fetchable URLs found in search results)"
        )

    urls = urls[: min(max_sources, MAX_RESEARCH_SOURCES)]

    # Cap search display to prevent budget collapse on large results.
    display_search = combined_search[:_MAX_SEARCH_DISPLAY_LEN]
    if len(combined_search) > _MAX_SEARCH_DISPLAY_LEN:
        display_search += "\n(search results truncated)"

    # Pre-build header and footer so budgets are exact.
    total_budget = MAX_FETCH_CONTENT_LEN - _UNTRUSTED_WEB_OVERHEAD
    header = f"## Research: {question}\n\n### Search Results\n{display_search}\n\n"
    footer_lines = ["### Sources"]
    for i, url in enumerate(urls, 1):
        footer_lines.append(f"[{i}] {url}")
    footer = "\n".join(footer_lines)

    content_budget = max(total_budget - len(header) - len(footer) - 20, 1000)
    per_source = content_budget // len(urls)

    # Fetch all URLs concurrently.
    fetch_tasks = [_fetch_source(url, per_source, cache) for url in urls]
    results = await asyncio.gather(*fetch_tasks)

    # Assemble report.
    parts: list[str] = [header]
    for idx, (url, content) in enumerate(results, 1):
        domain = urlparse(url).hostname or url
        parts.append(f"### Source [{idx}]: {domain}\n{content}\n")

    parts.append(footer)
    report = "\n".join(parts)
    return report[:total_budget]


# ---------------------------------------------------------------------------
# ToolHandler
# ---------------------------------------------------------------------------

from clarion.boundary_validation import MAX_QUERY_LEN, BoundaryValidationError
from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class DeepResearchHandler(ToolHandler):
    def __init__(self, ddg_rate_limiter: DdgRateLimiter) -> None:
        self._ddg_rate_limiter = ddg_rate_limiter

    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        question = str(arguments.get("question", ""))
        if len(question) > MAX_QUERY_LEN:
            raise BoundaryValidationError(
                f"Question exceeds maximum length of {MAX_QUERY_LEN} characters"
            )
        return arguments

    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        max_sources = int(
            str(arguments.get("max_sources", DEFAULT_MAX_SOURCES)),
        )
        text = await deep_research(
            str(arguments["question"]),
            max_sources=max_sources,
            workspace_root=ctx.workspace_root,
            agent_id=ctx.agent_id,
            cache=ctx.fetch_cache,
            ddg_rate_limiter=self._ddg_rate_limiter,
        )
        return ToolResult(text=text, wraps_untrusted_content=True)
