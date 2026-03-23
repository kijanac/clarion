"""Cooperative cancellation for async operations — layer 0.

Provides a simple token that long-running operations can check
to see if they should abort. Thread-safe so it works across
asyncio.to_thread() boundaries (e.g. SQLite calls).
"""

from __future__ import annotations

import threading


class CancellationError(Exception):
    """Raised when an operation is cancelled."""


class CancellationToken:
    """Cooperative cancellation token.

    Create one per operation, pass it down the call chain. The owner
    calls abort() to signal cancellation. Callees check .cancelled
    or call .check() which raises CancellationError.

    Thread-safe: abort() can be called from the main thread while
    .cancelled is read from a worker thread (e.g. inside
    asyncio.to_thread).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def abort(self) -> None:
        """Signal cancellation."""
        with self._lock:
            self._cancelled = True

    def check(self) -> None:
        """Raise CancellationError if cancelled."""
        if self.cancelled:
            raise CancellationError("Operation cancelled")
