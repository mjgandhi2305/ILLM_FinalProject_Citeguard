"""Progress event bus: in-process (inline jobs) or Redis pub/sub (ARQ workers → API)."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

TERMINAL_EVENTS = {"check.completed", "check.failed"}

Event = tuple[str, dict[str, Any]]


class EventBus(Protocol):
    async def publish(self, check_id: str, event: str, data: dict[str, Any]) -> None: ...

    def subscribe(self, check_id: str) -> Any:  # async context manager -> AsyncIterator[Event]
        ...


class LocalEventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    async def publish(self, check_id: str, event: str, data: dict[str, Any]) -> None:
        for q in list(self._subs.get(check_id, ())):
            q.put_nowait((event, data))

    @asynccontextmanager
    async def subscribe(self, check_id: str) -> AsyncIterator[AsyncIterator[Event]]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subs[check_id].add(q)

        async def iterate() -> AsyncIterator[Event]:
            while True:
                yield await q.get()

        try:
            yield iterate()
        finally:
            self._subs[check_id].discard(q)
            if not self._subs[check_id]:
                self._subs.pop(check_id, None)


class RedisEventBus:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, decode_responses=True)

    @staticmethod
    def _channel(check_id: str) -> str:
        return f"cg:events:{check_id}"

    async def publish(self, check_id: str, event: str, data: dict[str, Any]) -> None:
        await self._redis.publish(
            self._channel(check_id), json.dumps({"event": event, "data": data})
        )

    @asynccontextmanager
    async def subscribe(self, check_id: str) -> AsyncIterator[AsyncIterator[Event]]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(check_id))

        async def iterate() -> AsyncIterator[Event]:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                payload = json.loads(message["data"])
                yield payload["event"], payload["data"]

        try:
            yield iterate()
        finally:
            await pubsub.unsubscribe(self._channel(check_id))
            await pubsub.aclose()

    async def close(self) -> None:
        await self._redis.aclose()
