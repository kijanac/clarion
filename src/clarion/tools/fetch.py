"""URL fetch with SSRF protection, IP pinning, and content extraction."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable as _Iterable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpcore
import httpx
import structlog
from lxml.html import document_fromstring, tostring
from markdownify import markdownify
from readability import Document

try:
    from scrapling import Selector

    _HAS_SCRAPLING = True
except ImportError:
    _HAS_SCRAPLING = False

from clarion.boundary_validation import (
    MAX_FETCH_CONTENT_LEN,
    BoundaryValidationError,
    validate_url,
)
from clarion.tools.fetch_cache import FetchCache

log = structlog.get_logger()

UNTRUSTED_WEB_CONTENT_START = "[UNTRUSTED WEB CONTENT START]"
UNTRUSTED_WEB_CONTENT_END = "[UNTRUSTED WEB CONTENT END]"
_UNTRUSTED_WEB_OVERHEAD = len(UNTRUSTED_WEB_CONTENT_START) + len(UNTRUSTED_WEB_CONTENT_END) + 2

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_MAX_FETCH_REDIRECTS = 5
_DNS_TIMEOUT_S = 5.0
_FETCH_TIMEOUT_S = 15.0
_SCRAPLING_TIMEOUT_S = 30.0
_SCRAPLING_THREAD_TIMEOUT_S = 45.0
_MAX_FETCH_RESPONSE_BYTES = 1_500_000
_FETCH_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_FETCH_MODE = "fast"
DEFAULT_SELECTOR_TYPE = "css"
_MARKDOWNIFY_STRIP = ["img", "script", "style"]

# Scrapling fetcher class names keyed by mode.
_SCRAPLING_FETCHERS: dict[str, str] = {
    "stealth": "StealthyFetcher",
    "browser": "PlayWrightFetcher",
}


# ---------------------------------------------------------------------------
# SSRF protection helpers
# ---------------------------------------------------------------------------


def _is_public_ip(ip_text: str) -> bool:
    try:
        return ipaddress.ip_address(ip_text).is_global
    except ValueError:
        return False


def _resolve_host_ips(
    host: str,
    port: int,
) -> list[str]:
    """Resolve host to unique IPs (resolver order preserved)."""
    try:
        addr_info = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return []
    ips: list[str] = []
    seen: set[str] = set()
    for info in addr_info:
        raw_ip = info[4][0]
        ip = str(raw_ip)
        if ip in seen:
            continue
        seen.add(ip)
        ips.append(ip)
    return ips


async def _check_ssrf(url: str) -> str | None:
    """DNS-level SSRF pre-check. Returns error string or None if safe."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return "(fetch blocked: URL has no host)"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    try:
        resolved_ips = await asyncio.wait_for(
            asyncio.to_thread(_resolve_host_ips, host, port),
            timeout=_DNS_TIMEOUT_S,
        )
    except TimeoutError:
        return "(fetch blocked: DNS resolution timed out)"
    if not resolved_ips:
        return "(fetch blocked: host did not resolve to a public address)"
    non_public_ips = [ip for ip in resolved_ips if not _is_public_ip(ip)]
    if non_public_ips:
        return "(fetch blocked: host resolves to non-public address)"
    return None


# ---------------------------------------------------------------------------
# IP-pinned httpx transport (fast mode)
# ---------------------------------------------------------------------------


_SocketOption = (
    tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
)


class _PinnedHostBackend(httpcore.AsyncNetworkBackend):
    """Network backend that pins a hostname to one validated IP."""

    def __init__(
        self,
        *,
        pinned_host: str,
        pinned_ip: str,
        delegate: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._pinned_host = pinned_host.rstrip(".").lower()
        self._pinned_ip = pinned_ip
        if delegate is not None:
            self._delegate = delegate
        else:
            # AnyIOBackend extends AsyncNetworkBackend at runtime;
            # ty does not see this inheritance so we validate explicitly.
            backend = httpcore.AnyIOBackend()
            if not isinstance(backend, httpcore.AsyncNetworkBackend):
                raise TypeError("AnyIOBackend is not an AsyncNetworkBackend")
            self._delegate = backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: _Iterable[_SocketOption] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        connect_host = host
        if host.rstrip(".").lower() == self._pinned_host:
            connect_host = self._pinned_ip
        return await self._delegate.connect_tcp(
            host=connect_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: _Iterable[_SocketOption] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._delegate.connect_unix_socket(
            path=path,
            timeout=timeout,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


def _build_pinned_transport(
    *,
    host: str,
    pinned_ip: str,
) -> httpx.AsyncHTTPTransport:
    """Build an HTTP transport that preserves TLS hostname but pins TCP target."""
    transport = httpx.AsyncHTTPTransport(
        trust_env=False,
    )
    old_pool = transport._pool
    if not isinstance(old_pool, httpcore.AsyncConnectionPool):
        raise TypeError(f"unexpected pool type: {type(old_pool)}")
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=old_pool._ssl_context,
        max_connections=old_pool._max_connections,
        max_keepalive_connections=old_pool._max_keepalive_connections,
        keepalive_expiry=old_pool._keepalive_expiry,
        http1=old_pool._http1,
        http2=old_pool._http2,
        retries=old_pool._retries,
        local_address=old_pool._local_address,
        uds=old_pool._uds,
        socket_options=old_pool._socket_options,
        network_backend=_PinnedHostBackend(
            pinned_host=host,
            pinned_ip=pinned_ip,
        ),
    )
    return transport


def _parse_content_length(
    headers: object,
) -> int | None:
    get = getattr(headers, "get", None)
    if get is None:
        return None
    raw = get("content-length")
    if raw is None:
        return None
    try:
        value = int(str(raw))
    except ValueError:
        return None
    if value < 0:
        return None
    return value


async def _read_response_text_limited(
    resp: object,
    *,
    max_bytes: int,
) -> str | None:
    headers = getattr(resp, "headers", None)
    if headers is not None:
        content_length = _parse_content_length(headers)
        if content_length is not None and content_length > max_bytes:
            return None

    aiter_bytes = getattr(resp, "aiter_bytes", None)
    if aiter_bytes is not None:
        chunks: list[bytes] = []
        total = 0
        async for chunk in aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                return None
            chunks.append(chunk)
        raw = b"".join(chunks)
        encoding = getattr(resp, "encoding", None) or "utf-8"
        return raw.decode(encoding, errors="replace")

    # Fallback to .text attribute for simpler response objects.
    text = getattr(resp, "text", None)
    if isinstance(text, str):
        if len(text.encode("utf-8")) > max_bytes:
            return None
        return text
    return None


# ---------------------------------------------------------------------------
# Content wrapping and extraction
# ---------------------------------------------------------------------------


def wrap_untrusted_web_content(
    text: str,
    max_len: int | None = None,
) -> str:
    """Wrap external web content while preserving boundary length limits."""
    from clarion.boundary_validation import MAX_SEARCH_RESULT_LEN

    if max_len is None:
        max_len = MAX_SEARCH_RESULT_LEN
    payload_budget = max_len - _UNTRUSTED_WEB_OVERHEAD
    safe_payload = text[: max(payload_budget, 0)]
    return f"{UNTRUSTED_WEB_CONTENT_START}\n{safe_payload}\n{UNTRUSTED_WEB_CONTENT_END}"


def _html_to_markdown(raw_html: str) -> str:
    """Extract main content from HTML and convert to markdown."""
    try:
        doc = Document(raw_html)
        content_html = doc.summary()
        title = doc.short_title() or ""
    except Exception:
        try:
            tree = document_fromstring(raw_html)
            body = tree.find(".//body")
            if body is not None:
                content_html = tostring(body, encoding="unicode")
            else:
                content_html = raw_html
            title = ""
        except Exception:
            content_html = raw_html
            title = ""

    md = markdownify(content_html, strip=_MARKDOWNIFY_STRIP)

    if title:
        md = f"# {title}\n\n{md}"

    stripped = md.strip()
    return stripped if stripped else "(no extractable content)"


# ---------------------------------------------------------------------------
# Fast mode (httpx + IP pinning)
# ---------------------------------------------------------------------------


async def _fetch_html_fast(url: str) -> tuple[str | None, str | None]:
    """Fetch raw HTML via httpx with IP pinning and SSRF protection.

    Returns (html, None) on success, (None, error_message) on failure.
    """
    current_url = url
    for _hop in range(_MAX_FETCH_REDIRECTS + 1):
        raw_html: str | None = None
        try:
            await validate_url(current_url)
        except BoundaryValidationError as exc:
            return None, f"(fetch blocked: {exc})"

        parsed = httpx.URL(current_url)
        host = parsed.host
        if not host:
            return None, "(fetch blocked: URL has no host)"
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80

        try:
            resolved_ips = await asyncio.wait_for(
                asyncio.to_thread(_resolve_host_ips, host, port),
                timeout=_DNS_TIMEOUT_S,
            )
        except TimeoutError:
            return None, "(fetch timed out — DNS resolution)"
        if not resolved_ips:
            return None, "(fetch blocked: host did not resolve to a public address)"
        non_public_ips = [ip for ip in resolved_ips if not _is_public_ip(ip)]
        if non_public_ips:
            return None, "(fetch blocked: host resolves to non-public address)"

        for attempt in range(2):
            pinned_ip = resolved_ips[attempt % len(resolved_ips)]
            try:
                transport = _build_pinned_transport(
                    host=host,
                    pinned_ip=pinned_ip,
                )
                async with httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=_FETCH_TIMEOUT_S,
                    trust_env=False,
                    transport=transport,
                ) as client:
                    async with client.stream(
                        "GET",
                        current_url,
                        headers={
                            "User-Agent": _FETCH_USER_AGENT,
                        },
                    ) as resp:
                        if resp.status_code >= 500:
                            if attempt == 0:
                                continue
                            return None, "(fetch temporarily unavailable)"
                        if resp.status_code in _REDIRECT_STATUS_CODES:
                            location = str(
                                resp.headers.get("location", ""),
                            ).strip()
                            if not location:
                                return None, "(fetch failed: redirect without location)"
                            current_url = urljoin(
                                current_url,
                                location,
                            )
                            break
                        if resp.status_code == 429:
                            return None, "(fetch rate limited — try again shortly)"
                        if 400 <= resp.status_code < 500:
                            return None, f"(fetch failed: HTTP {resp.status_code})"
                        resp.raise_for_status()
                        raw_html = await _read_response_text_limited(
                            resp,
                            max_bytes=_MAX_FETCH_RESPONSE_BYTES,
                        )
                        if raw_html is None:
                            return None, "(fetch failed: response too large)"
                        break
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
            ):
                if attempt == 0:
                    continue
                return None, "(fetch timed out — try again shortly)"
            except httpx.HTTPError as exc:
                if attempt == 0:
                    continue
                log.warning(
                    "fetch failed",
                    error=str(exc),
                )
                return None, "(fetch temporarily unavailable)"
        else:
            return None, "(fetch unavailable)"

        if raw_html is None:
            continue
        break
    else:
        return None, "(fetch failed: too many redirects)"

    return raw_html, None


async def _web_fetch_fast(url: str) -> str:
    """Fetch with httpx, IP pinning, redirect following, and SSRF checks."""
    html, error = await _fetch_html_fast(url)
    if error is not None:
        return error
    if html is None:
        return "(no extractable content)"
    return _html_to_markdown(html)


# ---------------------------------------------------------------------------
# Scrapling modes (stealth / browser)
# ---------------------------------------------------------------------------


def _element_to_html(obj: object) -> str | None:
    """Extract HTML string from a Scrapling Adaptor/Selector element.

    Tries the internal lxml ``_root`` attribute first, then ``.body``,
    then ``str()`` as a last resort.
    """
    root = getattr(obj, "_root", None)
    if root is not None:
        try:
            return tostring(root, encoding="unicode")
        except Exception:
            pass
    body = getattr(obj, "body", None)
    if isinstance(body, str) and body.strip():
        return body
    try:
        return str(obj)
    except Exception:
        return None


async def _web_fetch_scrapling(url: str, *, mode: str) -> str:
    """Fetch using Scrapling's StealthyFetcher or PlayWrightFetcher.

    SSRF note: the DNS pre-check here is best-effort.  Unlike the fast path
    which pins the validated IP for the actual TCP connection, Scrapling's
    fetchers resolve DNS independently.  A DNS rebinding attack between the
    check and the fetch is theoretically possible but requires the target to
    cooperate with alternating DNS responses within a narrow window.
    """
    if not _HAS_SCRAPLING:
        log.warning("scrapling not installed, falling back to fast mode", mode=mode)
        return await _web_fetch_fast(url)

    # SSRF pre-check: resolve DNS and verify all IPs are public.
    # validate_url() already ran in the boundary validation layer;
    # _check_ssrf adds the runtime DNS resolution check.
    ssrf_error = await _check_ssrf(url)
    if ssrf_error:
        return ssrf_error

    class_name = _SCRAPLING_FETCHERS[mode]
    try:
        import scrapling.fetchers as fetchers_mod

        fetcher_cls = getattr(fetchers_mod, class_name)
    except (ImportError, AttributeError):
        return f"({mode} mode unavailable — install scrapling with: pip install 'scrapling[all]')"

    try:
        page = await asyncio.wait_for(
            asyncio.to_thread(
                fetcher_cls.fetch,
                url,
                headless=True,
                network_idle=True,
                timeout=int(_SCRAPLING_TIMEOUT_S * 1000),
            ),
            timeout=_SCRAPLING_THREAD_TIMEOUT_S,
        )
    except TimeoutError:
        return f"({mode} fetch timed out — try again shortly)"
    except Exception as exc:
        log.warning("scrapling fetch failed", mode=mode, error=str(exc))
        return f"({mode} fetch failed: {type(exc).__name__})"

    status = getattr(page, "status", 200)
    if status and status >= 400:
        return f"(fetch failed: HTTP {status})"

    raw_html = _element_to_html(page)
    if not raw_html or not raw_html.strip():
        return "(no extractable content)"

    # Enforce the same response size limit as the fast path.
    if len(raw_html.encode("utf-8", errors="ignore")) > _MAX_FETCH_RESPONSE_BYTES:
        return "(fetch failed: response too large)"

    return _html_to_markdown(raw_html)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def web_fetch_url(
    url: str,
    *,
    mode: str = DEFAULT_FETCH_MODE,
    cache: FetchCache | None = None,
) -> str:
    """Fetch *url*, extract main content, return as markdown.

    Modes:
        fast    — httpx with IP-pinning SSRF protection (default).
        stealth — Scrapling StealthyFetcher for anti-bot bypass.
        browser — Scrapling PlayWrightFetcher for JS-rendered pages.

    If *cache* is provided, results are served from / stored to the
    per-agent SQLite cache.
    """
    if cache is not None:
        entry = cache.get(url)
        if entry is not None:
            return entry.markdown

    if mode in _SCRAPLING_FETCHERS:
        result = await _web_fetch_scrapling(url, mode=mode)
    else:
        result = await _web_fetch_fast(url)
        # Auto-fallback: if fast mode got blocked, retry with stealth.
        if result == "(fetch failed: HTTP 403)":
            log.info("fast fetch 403, falling back to stealth", url=url)
            result = await _web_fetch_scrapling(url, mode="stealth")

    # Cache successful fetches only; all error strings start with "(".
    if cache is not None and not result.startswith("("):
        cache.put(url, result)

    return result


# ---------------------------------------------------------------------------
# Targeted extraction (web_extract)
# ---------------------------------------------------------------------------

_MAX_EXTRACT_ELEMENTS = 50


async def web_extract_content(
    url: str,
    selector: str,
    *,
    selector_type: str = DEFAULT_SELECTOR_TYPE,
) -> str:
    """Fetch URL and extract specific content using CSS/XPath selectors."""
    html, error = await _fetch_html_fast(url)
    if error is not None:
        return error

    if _HAS_SCRAPLING:
        try:
            page = Selector(html)
        except Exception:
            return "(failed to parse page HTML)"

        try:
            if selector_type == "xpath":
                elements = page.xpath(selector)
            else:
                elements = page.css(selector)
        except Exception as exc:
            return f"(invalid selector: {exc})"

        if not elements:
            return "(no elements matched the selector)"

        budget = MAX_FETCH_CONTENT_LEN - _UNTRUSTED_WEB_OVERHEAD
        parts: list[str] = []
        parts_len = 0
        total = 0
        for el in elements:
            total += 1
            if len(parts) >= _MAX_EXTRACT_ELEMENTS:
                continue  # keep counting total
            el_html = _element_to_html(el)
            if el_html:
                md = markdownify(
                    el_html,
                    strip=_MARKDOWNIFY_STRIP,
                ).strip()
            else:
                text = getattr(el, "text", None)
                md = str(text).strip() if text else ""
            if md:
                parts.append(md)
                parts_len += len(md)
                if parts_len >= budget:
                    # Count remaining without converting
                    total += sum(1 for _ in elements)
                    break
    else:
        # Fallback: use lxml directly when scrapling is not available
        try:
            tree = document_fromstring(html)
        except Exception:
            return "(failed to parse page HTML)"

        try:
            if selector_type == "xpath":
                elements_lxml = tree.xpath(selector)
            else:
                from lxml.cssselect import CSSSelector

                css_sel = CSSSelector(selector)
                elements_lxml = css_sel(tree)
        except Exception as exc:
            return f"(invalid selector: {exc})"

        if not elements_lxml:
            return "(no elements matched the selector)"

        budget = MAX_FETCH_CONTENT_LEN - _UNTRUSTED_WEB_OVERHEAD
        parts = []
        parts_len = 0
        total = 0
        for el in elements_lxml:
            total += 1
            if len(parts) >= _MAX_EXTRACT_ELEMENTS:
                continue  # keep counting total
            try:
                el_html = tostring(el, encoding="unicode")
            except Exception:
                el_html = None
            if el_html:
                md = markdownify(
                    el_html,
                    strip=_MARKDOWNIFY_STRIP,
                ).strip()
            else:
                text = getattr(el, "text_content", lambda: "")()
                md = str(text).strip() if text else ""
            if md:
                parts.append(md)
                parts_len += len(md)
                if parts_len >= budget:
                    total += sum(1 for _ in elements_lxml)
                    break

    if not parts:
        return "(no extractable content from matched elements)"

    count_note = ""
    if total > _MAX_EXTRACT_ELEMENTS:
        count_note = f"\n\n(showing {_MAX_EXTRACT_ELEMENTS} of {total} matched elements)"

    if len(parts) == 1:
        result = parts[0]
    else:
        result = "\n\n---\n\n".join(f"**[{i + 1}]** {p}" for i, p in enumerate(parts))
    result = result[: max(budget - len(count_note), 0)] + count_note
    return result


# ---------------------------------------------------------------------------
# ToolHandlers
# ---------------------------------------------------------------------------

from clarion.boundary_validation import EXTRACT_SELECTOR_TYPES, FETCH_MODES
from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class WebFetchHandler(ToolHandler):
    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        await validate_url(str(arguments.get("url", "")))
        mode = arguments.get("mode")
        if mode is not None and mode not in FETCH_MODES:
            raise BoundaryValidationError(
                f"Invalid fetch mode {mode!r}, must be one of {sorted(FETCH_MODES)}"
            )
        return arguments

    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        fetch_mode = str(arguments.get("mode", DEFAULT_FETCH_MODE))
        text = await web_fetch_url(
            str(arguments["url"]),
            mode=fetch_mode,
            cache=ctx.fetch_cache,
        )
        return ToolResult(text=text, wraps_untrusted_content=True)


class WebExtractHandler(ToolHandler):
    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        await validate_url(str(arguments.get("url", "")))
        selector_type = arguments.get("selector_type")
        if selector_type is not None and selector_type not in EXTRACT_SELECTOR_TYPES:
            raise BoundaryValidationError(
                f"Invalid selector_type {selector_type!r}, "
                f"must be one of {sorted(EXTRACT_SELECTOR_TYPES)}"
            )
        return arguments

    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        selector_type = str(
            arguments.get("selector_type", DEFAULT_SELECTOR_TYPE),
        )
        text = await web_extract_content(
            str(arguments["url"]),
            str(arguments["selector"]),
            selector_type=selector_type,
        )
        return ToolResult(text=text, wraps_untrusted_content=True)
