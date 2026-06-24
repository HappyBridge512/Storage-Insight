from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, Any], Awaitable[None] | None]


class AsyncEventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, set[EventHandler]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, event_name: str, handler: EventHandler) -> Callable[[], Awaitable[None]]:
        async with self._lock:
            self._handlers[event_name].add(handler)

        async def unsubscribe() -> None:
            async with self._lock:
                self._handlers[event_name].discard(handler)

        return unsubscribe

    async def publish(self, event_name: str, payload: Any) -> None:
        async with self._lock:
            handlers = list(self._handlers.get(event_name, ())) + list(self._handlers.get("*", ()))

        for handler in handlers:
            try:
                result = handler(event_name, payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("event handler failed for %s", event_name)
