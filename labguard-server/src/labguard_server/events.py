"""In-process fan-out for authenticated administrator event streams."""
import asyncio
from collections.abc import AsyncIterator
from typing import Any


class AdminEventHub:
    def __init__(self, queue_size: int = 128):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.queue_size = queue_size

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def publish(self, event: dict[str, Any]) -> None:
        loop = self.loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._publish_on_loop, event)

    def _publish_on_loop(self, event: dict[str, Any]) -> None:
        for queue in tuple(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self.queue_size)
        self.subscribers.add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield None
        finally:
            self.subscribers.discard(queue)
