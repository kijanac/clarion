"""Event bus — layer 0.

Routes platform events to agent triggers. Event sources (APScheduler,
deliver_output, webhooks) emit events. The bus matches them against
registered agent triggers and calls the fire callback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Awaitable, Callable

import structlog

from clarion.models import TriggerDefinition, TriggerType

log = structlog.get_logger()

FireCallback = Callable[[str, str], Awaitable[None]]  # (agent_id, trigger_reason) -> None


class EventType(str, Enum):
    CRON_FIRED = "cron_fired"
    OUTPUT_PRODUCED = "output_produced"


@dataclass(frozen=True)
class Event:
    """A platform event that may trigger agent runs."""

    type: EventType
    agent_id: str = ""
    output_name: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    """Matches events against registered triggers and fires agent runs."""

    def __init__(self, fire_callback: FireCallback) -> None:
        self._fire = fire_callback
        self._triggers: dict[str, list[TriggerDefinition]] = {}  # agent_id -> triggers
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False

    def register(self, agent_id: str, triggers: list[TriggerDefinition]) -> None:
        """Register an agent's triggers."""
        self._triggers[agent_id] = list(triggers)
        log.info("event_bus.registered", agent_id=agent_id, trigger_count=len(triggers))

    def unregister(self, agent_id: str) -> None:
        """Remove an agent's triggers."""
        self._triggers.pop(agent_id, None)
        log.info("event_bus.unregistered", agent_id=agent_id)

    async def emit(self, event: Event) -> None:
        """Emit an event into the bus."""
        await self._queue.put(event)
        log.debug("event_bus.emit", event_type=event.type, agent_id=event.agent_id)

    async def run(self) -> None:
        """Process events until stopped."""
        self._running = True
        log.info("event_bus.start")
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            await self._dispatch(event)

    def stop(self) -> None:
        """Signal the bus to stop."""
        self._running = False

    async def _dispatch(self, event: Event) -> None:
        """Match an event against all registered triggers and fire matches."""
        for agent_id, triggers in self._triggers.items():
            for trigger in triggers:
                if self._matches(event, trigger, agent_id):
                    reason = f"{event.type}"
                    if event.output_name:
                        reason = f"{event.type}:{event.agent_id}/{event.output_name}"
                    log.info(
                        "event_bus.trigger_matched",
                        event_type=event.type,
                        target_agent=agent_id,
                    )
                    try:
                        await self._fire(agent_id, reason)
                    except Exception:
                        log.exception(
                            "event_bus.fire_failed",
                            agent_id=agent_id,
                            event_type=event.type,
                        )

    def _matches(self, event: Event, trigger: TriggerDefinition, agent_id: str) -> bool:
        """Check if an event matches a trigger."""
        if event.type == EventType.CRON_FIRED and trigger.type == TriggerType.CRON:
            return event.agent_id == agent_id

        if event.type == EventType.OUTPUT_PRODUCED and trigger.type == TriggerType.AGENT_OUTPUT:
            return (
                event.agent_id == trigger.source_agent
                and event.output_name == trigger.output_name
            )

        return False
