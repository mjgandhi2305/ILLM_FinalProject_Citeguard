"""Process-wide service state shared by the routes."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from citeguard.config import Settings
from citeguard.db.repo import Repository
from citeguard.engine import Engine
from citeguard.worker.events import EventBus


class RateLimiter:
    """Non-blocking per-principal token bucket (requests per minute)."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, per_minute: int) -> tuple[bool, float]:
        rate = per_minute / 60.0
        now = time.monotonic()
        tokens, updated = self._buckets.get(key, (float(per_minute), now))
        tokens = min(float(per_minute), tokens + (now - updated) * rate)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return True, 0.0
        self._buckets[key] = (tokens, now)
        return False, (1.0 - tokens) / rate


@dataclass
class AppState:
    settings: Settings
    db: AsyncEngine
    repo: Repository
    engine: Engine
    bus: EventBus
    arq: Any | None = None
    rate_limiter: RateLimiter = field(default_factory=RateLimiter)
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    check_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def enqueue(self, check_id: uuid.UUID) -> None:
        if self.arq is not None:
            await self.arq.enqueue_job("run_check", str(check_id))
            return
        from citeguard.worker.runner import execute_check

        async def run() -> None:
            async with self.check_slots:
                await execute_check(check_id, engine=self.engine, repo=self.repo, bus=self.bus)

        self.spawn(run())


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.cg
    return state
