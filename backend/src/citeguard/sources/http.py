"""Resilient, cached, rate-limited HTTP access for one scholarly source."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from citeguard.observability.metrics import SOURCE_LATENCY, SOURCE_REQUESTS
from citeguard.sources.infra import Cache, CircuitBreaker, CircuitOpenError, RateLimiter

log = structlog.get_logger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class HttpResult:
    status: int  # HTTP status, or 0 for transport failure / -1 for circuit open
    data: Any = None  # parsed JSON, or text when json=False
    cached: bool = False
    latency_ms: int = 0
    error: str | None = None
    final_url: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def not_found(self) -> bool:
        return self.status in (404, 410)


class SourceHttp:
    def __init__(
        self,
        name: str,
        client: httpx.AsyncClient,
        limiter: RateLimiter,
        cache: Cache,
        breaker: CircuitBreaker,
        *,
        max_retries: int = 3,
        ttl_hit_s: int = 30 * 24 * 3600,
        ttl_miss_s: int = 24 * 3600,
        max_retry_after_s: float = 30.0,
        call_budget_s: float = 20.0,
    ) -> None:
        self.call_budget_s = call_budget_s
        self.name = name
        self.client = client
        self.limiter = limiter
        self.cache = cache
        self.breaker = breaker
        self.max_retries = max_retries
        self.ttl_hit_s = ttl_hit_s
        self.ttl_miss_s = ttl_miss_s
        self.max_retry_after_s = max_retry_after_s

    def _cache_key(self, url: str, params: dict[str, Any] | None, accept: str | None) -> str:
        blob = json.dumps([url, sorted((params or {}).items()), accept], default=str)
        return f"{self.name}:{hashlib.sha256(blob.encode()).hexdigest()[:32]}"

    async def get(self, url: str, params: dict[str, Any] | None = None, **kw: Any) -> HttpResult:
        # The budget is a hard deadline for the whole call: rate-limiter waits, retries, and
        # slow responses (httpx's timeout applies per read, not per response) all count.
        try:
            async with asyncio.timeout(self.call_budget_s):
                result = await self._get(url, params, **kw)
        except TimeoutError:
            self.breaker.record_failure()
            log.warning("source.deadline", source=self.name, url=url, budget_s=self.call_budget_s)
            result = HttpResult(
                status=0,
                error=f"no answer within {self.call_budget_s:g}s",
                latency_ms=int(self.call_budget_s * 1000),
            )
        outcome = (
            "cached"
            if result.cached
            else ("ok" if result.ok else "not_found" if result.not_found else "error")
        )
        SOURCE_REQUESTS.labels(source=self.name, outcome=outcome).inc()
        if not result.cached and result.latency_ms:
            SOURCE_LATENCY.labels(source=self.name).observe(result.latency_ms / 1000)
        return result

    async def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        as_json: bool = True,
        use_cache: bool = True,
        follow_redirects: bool = True,
    ) -> HttpResult:
        accept = (headers or {}).get("Accept")
        key = self._cache_key(url, params, accept)
        if use_cache:
            hit = await self.cache.get(key)
            if hit is not None:
                return HttpResult(
                    status=hit["status"], data=hit["data"], cached=True, final_url=hit.get("url")
                )

        try:
            self.breaker.check()
        except CircuitOpenError as exc:
            return HttpResult(status=-1, error=str(exc))

        started = time.perf_counter()
        attempt = 0
        last_error: str | None = None
        while True:
            attempt += 1
            await self.limiter.acquire()
            try:
                resp = await self.client.get(
                    url, params=params, headers=headers, follow_redirects=follow_redirects
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                backoff = self._backoff(attempt)
                if attempt <= self.max_retries and self._within_budget(started, backoff):
                    await asyncio.sleep(backoff)
                    continue
                self.breaker.record_failure()
                log.warning("source.transport_error", source=self.name, url=url, error=last_error)
                return HttpResult(status=0, error=last_error, latency_ms=self._ms(started))

            if resp.status_code in RETRYABLE_STATUS:
                asked = self._retry_after(resp)
                if asked is not None and asked > self.max_retry_after_s:
                    # e.g. a daily quota: stop calling this source for as long as it asked
                    # (capped at an hour, then one trial request) instead of stalling checks.
                    self.breaker.open_for(min(asked, 3600.0), f"rate limited ({int(asked)}s)")
                    log.warning("source.backoff", source=self.name, retry_after=int(asked))
                    return HttpResult(
                        status=resp.status_code,
                        error=f"rate limited; retry after {int(asked)}s",
                        latency_ms=self._ms(started),
                    )
                delay = asked if asked is not None else self._backoff(attempt)
                if attempt <= self.max_retries and self._within_budget(started, delay):
                    log.info(
                        "source.retry",
                        source=self.name,
                        status=resp.status_code,
                        delay=round(delay, 2),
                    )
                    await asyncio.sleep(delay)
                    continue
            break

        latency = self._ms(started)
        if resp.status_code in RETRYABLE_STATUS:
            self.breaker.record_failure()
            return HttpResult(
                status=resp.status_code, error=f"HTTP {resp.status_code}", latency_ms=latency
            )

        data: Any = None
        if 200 <= resp.status_code < 300:
            if as_json:
                try:
                    data = resp.json()
                except ValueError:
                    # e.g. an anti-bot interstitial served with 200/202 + HTML
                    self.breaker.record_failure()
                    return HttpResult(
                        status=0, error="unexpected non-JSON response", latency_ms=latency
                    )
            else:
                data = resp.text
        elif as_json and resp.headers.get("content-type", "").startswith("application/json"):
            try:
                data = resp.json()
            except ValueError:
                data = None
        self.breaker.record_success()

        result = HttpResult(
            status=resp.status_code, data=data, latency_ms=latency, final_url=str(resp.url)
        )
        if use_cache and (result.ok or result.not_found):
            ttl = self.ttl_hit_s if result.ok else self.ttl_miss_s
            await self.cache.set(
                key, {"status": result.status, "data": data, "url": result.final_url}, ttl
            )
        return result

    def _backoff(self, attempt: int) -> float:
        return float(min(20.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.5))  # noqa: S311

    def _retry_after(self, resp: httpx.Response) -> float | None:
        value = resp.headers.get("retry-after")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None

    def _within_budget(self, started: float, delay: float) -> bool:
        return (time.perf_counter() - started) + delay < self.call_budget_s

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
