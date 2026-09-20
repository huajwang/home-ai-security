"""Fan-out for authenticated event WebSockets."""

from __future__ import annotations

import asyncio
import json
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def register(self, queue: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._queues.add(queue)
        print(f"EventBus clients={len(self._queues)}")

    async def unregister(self, queue: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._queues.discard(queue)

    async def publish(self, payload: dict[str, Any]) -> None:
        message = json.dumps(payload)
        async with self._lock:
            queues = list(self._queues)
        print(f"EventBus publish {payload.get('type')} to {len(queues)} client(s)")
        for queue in queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                print("EventBus drop: client queue full")

    def publish_threadsafe(self, loop: asyncio.AbstractEventLoop, payload: dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(self.publish(payload), loop)
