"""URL fetch cache backed by per-agent SQLite."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TTL_S = 3600  # 1 hour

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS fetch_cache (
    url TEXT PRIMARY KEY,
    markdown TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    ttl_s INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class CacheEntry:
    url: str
    markdown: str
    content_hash: str
    fetched_at: float
    ttl_s: int


class FetchCache:
    """Per-agent cache for fetched web page markdown."""

    def __init__(
        self,
        workspace_root: Path,
        agent_id: str,
        *,
        default_ttl_s: int = DEFAULT_TTL_S,
    ) -> None:
        self._default_ttl_s = default_ttl_s
        cache_dir = workspace_root / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        db_path = cache_dir / "fetch_cache.db"
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)
        self.evict_expired()

    def get(self, url: str) -> CacheEntry | None:
        """Return cached entry if present and not expired."""
        row = self._conn.execute(
            "SELECT url, markdown, content_hash, fetched_at, ttl_s FROM fetch_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        entry = CacheEntry(*row)
        if time.time() - entry.fetched_at > entry.ttl_s:
            self._conn.execute(
                "DELETE FROM fetch_cache WHERE url = ?",
                (url,),
            )
            self._conn.commit()
            return None
        return entry

    def put(
        self,
        url: str,
        markdown: str,
        *,
        ttl_s: int | None = None,
    ) -> CacheEntry:
        """Insert or replace a cache entry."""
        if ttl_s is None:
            ttl_s = self._default_ttl_s
        content_hash = hashlib.sha256(
            markdown.encode("utf-8", errors="replace"),
        ).hexdigest()
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO fetch_cache"
            " (url, markdown, content_hash, fetched_at, ttl_s)"
            " VALUES (?, ?, ?, ?, ?)",
            (url, markdown, content_hash, now, ttl_s),
        )
        self._conn.commit()
        return CacheEntry(
            url=url,
            markdown=markdown,
            content_hash=content_hash,
            fetched_at=now,
            ttl_s=ttl_s,
        )

    def evict(self, url: str) -> bool:
        """Remove a single URL from cache. Returns True if it existed."""
        cursor = self._conn.execute(
            "DELETE FROM fetch_cache WHERE url = ?",
            (url,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def evict_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = time.time()
        cursor = self._conn.execute(
            "DELETE FROM fetch_cache WHERE (? - fetched_at) > ttl_s",
            (now,),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
