"""Shared infrastructure for outbound calls: caching, rate limiting, circuit breaking.

Every primitive has an in-process implementation (CLI, tests, single worker) and an
interface that the service layer can back with Redis so that all workers share one quota."""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol


# --------------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------------
class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl_s: int) -> None: ...


class NullCache:
    async def get(self, key: str) -> Any | None:
        return None

    async def set(self, key: str, value: Any, ttl_s: int) -> None:
        return None


class MemoryCache:
    def __init__(self, max_items: int = 10_000) -> None:
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_items

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.time():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl_s: int) -> None:
        self._data[key] = (time.time() + ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)


class DiskCache:
    """Persistent cache for the CLI and eval runs (diskcache is process-safe)."""

    def __init__(self, directory: Path) -> None:
        import diskcache

        directory.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(directory), size_limit=2 * 1024**3)

    async def get(self, key: str) -> Any | None:
        raw = self._cache.get(key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, ttl_s: int) -> None:
        self._cache.set(key, json.dumps(value), expire=ttl_s)

    def close(self) -> None:
        self._cache.close()


class RedisCache:
    def __init__(self, url: str, prefix: str = "cg:cache:") -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(self._prefix + key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, ttl_s: int) -> None:
        await self._redis.set(self._prefix + key, json.dumps(value), ex=ttl_s)

    async def close(self) -> None:
        await self._redis.aclose()


# --------------------------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------------------------
class RateLimiter(Protocol):
    async def acquire(self, cost: float = 1.0) -> None: ...


class TokenBucket:
    """Async token bucket: `rate` tokens per second, up to `burst` stored."""

    def __init__(self, rate: float, burst: float | None = None) -> None:
        self.rate = rate
        self.capacity = burst if burst is not None else max(1.0, rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= cost:
                    self._tokens -= cost
                    return
                await asyncio.sleep((cost - self._tokens) / self.rate)


class RedisTokenBucket:
    """Token bucket shared across processes (atomic via a Lua script)."""

    _LUA = """
    local key = KEYS[1]
    local rate = tonumber(ARGV[1]); local cap = tonumber(ARGV[2])
    local now = tonumber(ARGV[3]); local cost = tonumber(ARGV[4])
    local data = redis.call('HMGET', key, 'tokens', 'ts')
    local tokens = tonumber(data[1]) or cap
    local ts = tonumber(data[2]) or now
    tokens = math.min(cap, tokens + (now - ts) * rate)
    local wait = 0
    if tokens >= cost then tokens = tokens - cost else wait = (cost - tokens) / rate end
    if wait == 0 then redis.call('HSET', key, 'tokens', tokens, 'ts', now) end
    redis.call('EXPIRE', key, 3600)
    return tostring(wait)
    """

    def __init__(self, redis: Any, name: str, rate: float, burst: float | None = None) -> None:
        self._redis = redis
        self._key = f"cg:rl:{name}"
        self.rate = rate
        self.capacity = burst if burst is not None else max(1.0, rate)
        self._script = redis.register_script(self._LUA)

    async def acquire(self, cost: float = 1.0) -> None:
        while True:
            wait = float(
                await self._script(
                    keys=[self._key], args=[self.rate, self.capacity, time.time(), cost]
                )
            )
            if wait <= 0:
                return
            await asyncio.sleep(min(wait, 5.0))


# --------------------------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------------------------
class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    """Opens after `threshold` consecutive failures for `cooldown_s` (or for as long as the
    server asked via `open_for`), then lets one trial request through (half-open)."""

    def __init__(self, name: str, threshold: int = 5, cooldown_s: float = 60.0) -> None:
        self.name = name
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.open_until: float | None = None
        self.reason: str | None = None

    @property
    def state(self) -> str:
        if self.open_until is None:
            return "closed"
        if time.monotonic() >= self.open_until:
            return "half-open"
        return "open"

    def check(self) -> None:
        if self.state == "open":
            raise CircuitOpenError(f"circuit open for {self.name}: {self.reason or 'failures'}")

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = None
        self.reason = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold or self.state == "half-open":
            self.open_until = time.monotonic() + self.cooldown_s

    def open_for(self, seconds: float, reason: str) -> None:
        self.open_until = time.monotonic() + seconds
        self.reason = reason
