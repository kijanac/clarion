"""Lightweight asyncio background task manager."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class BackgroundTaskHandle:
    task_id: str
    agent_id: str
    label: str


CompletionCallback = Callable[
    [BackgroundTaskHandle, str | None, str | None],
    Awaitable[None],
]
TaskFactory = Callable[[], Awaitable[str]]


class BackgroundTaskManager:
    """Manages background asyncio tasks with concurrency control."""

    def __init__(
        self,
        *,
        max_concurrent: int = 3,
        default_timeout_s: float = 900.0,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._default_timeout_s = default_timeout_s
        self._active: dict[str, asyncio.Task[None]] = {}

    @property
    def active_count(self) -> int:
        return len(self._active)

    def spawn(
        self,
        *,
        agent_id: str,
        label: str,
        task_factory: TaskFactory,
        on_complete: CompletionCallback,
        timeout_s: float | None = None,
    ) -> BackgroundTaskHandle:
        """Spawn a background task. Returns handle immediately."""
        task_id = uuid4().hex[:12]
        handle = BackgroundTaskHandle(
            task_id=task_id,
            agent_id=agent_id,
            label=label,
        )
        timeout = timeout_s if timeout_s is not None else self._default_timeout_s
        task = asyncio.create_task(
            self._run(
                handle,
                task_factory,
                on_complete,
                timeout,
            ),
        )
        self._active[task_id] = task
        task.add_done_callback(
            lambda _: self._active.pop(task_id, None),
        )
        log.info(
            "background_task.spawned",
            task_id=task_id,
            agent_id=agent_id,
            label=label,
        )
        return handle

    async def _run(
        self,
        handle: BackgroundTaskHandle,
        task_factory: TaskFactory,
        on_complete: CompletionCallback,
        timeout_s: float,
    ) -> None:
        async with self._semaphore:
            result: str | None = None
            error: str | None = None
            task_coro: Awaitable[str] | None = None
            try:
                # Delay coroutine construction until execution starts so
                # canceled/queued tasks don't leak un-awaited coroutines.
                task_coro = task_factory()
                result = await asyncio.wait_for(
                    task_coro,
                    timeout=timeout_s,
                )
            except TimeoutError:
                error = f"Task timed out after {timeout_s:.0f}s"
                log.warning(
                    "background_task.timeout",
                    task_id=handle.task_id,
                    agent_id=handle.agent_id,
                    label=handle.label,
                    timeout_s=timeout_s,
                )
            except asyncio.CancelledError:
                if task_coro is not None and hasattr(task_coro, "close"):
                    task_coro.close()  # type: ignore[attr-defined]
                return
            except Exception as exc:
                error = str(exc)
                log.error(
                    "background_task.error",
                    task_id=handle.task_id,
                    agent_id=handle.agent_id,
                    label=handle.label,
                    error=error,
                )
            try:
                await on_complete(handle, result, error)
            except Exception as cb_exc:
                log.error(
                    "background_task.callback_error",
                    task_id=handle.task_id,
                    agent_id=handle.agent_id,
                    label=handle.label,
                    error=str(cb_exc),
                )

    async def shutdown(self) -> None:
        """Cancel all active tasks."""
        for task in list(self._active.values()):
            task.cancel()
        if self._active:
            await asyncio.gather(
                *self._active.values(),
                return_exceptions=True,
            )
        self._active.clear()
