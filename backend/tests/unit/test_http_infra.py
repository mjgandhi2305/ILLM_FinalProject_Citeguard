import asyncio
import time

import httpx
import respx

from citeguard.sources.http import SourceHttp
from citeguard.sources.infra import CircuitBreaker, MemoryCache, TokenBucket


def make(client: httpx.AsyncClient, **kw: object) -> SourceHttp:
    return SourceHttp(
        "t",
        client,
        TokenBucket(1000),
        MemoryCache(),
        CircuitBreaker("t", threshold=2),
        **kw,  # type: ignore[arg-type]
    )


@respx.mock
async def test_retry_then_success_and_cache() -> None:
    route = respx.get("https://api.test/x").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as client:
        http = make(client)
        res = await http.get("https://api.test/x")
        assert res.ok and res.data == {"ok": True}
        again = await http.get("https://api.test/x")
        assert again.cached and again.data == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_not_found_is_cached_and_not_retried() -> None:
    route = respx.get("https://api.test/missing").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        http = make(client)
        assert (await http.get("https://api.test/missing")).not_found
        assert (await http.get("https://api.test/missing")).cached
    assert route.call_count == 1


@respx.mock
async def test_circuit_opens_after_failures() -> None:
    respx.get("https://api.test/down").mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as client:
        http = make(client, max_retries=0)
        assert (await http.get("https://api.test/down", use_cache=False)).status == 503
        assert (await http.get("https://api.test/down", use_cache=False)).status == 503
        blocked = await http.get("https://api.test/down", use_cache=False)
        assert blocked.status == -1 and "circuit open" in (blocked.error or "")


@respx.mock
async def test_html_interstitial_is_an_error() -> None:
    respx.get("https://api.test/bot").mock(
        return_value=httpx.Response(
            202, text="<html>not a bot?</html>", headers={"content-type": "text/html"}
        )
    )
    async with httpx.AsyncClient() as client:
        res = await make(client).get("https://api.test/bot")
        assert res.status == 0 and res.error


@respx.mock
async def test_long_retry_after_opens_circuit_instead_of_waiting() -> None:
    route = respx.get("https://api.test/quota").mock(
        return_value=httpx.Response(429, headers={"retry-after": "28055"})
    )
    async with httpx.AsyncClient() as client:
        http = make(client)
        res = await http.get("https://api.test/quota", use_cache=False)
        assert res.status == 429 and "retry after 28055s" in (res.error or "")
        assert http.breaker.state == "open"
        again = await http.get("https://api.test/quota", use_cache=False)
        assert again.status == -1  # skipped without a request
    assert route.call_count == 1


@respx.mock
async def test_call_budget_limits_total_retry_time() -> None:
    route = respx.get("https://api.test/slow").mock(
        return_value=httpx.Response(503, headers={"retry-after": "8"})
    )
    async with httpx.AsyncClient() as client:
        http = make(client, call_budget_s=5.0)
        res = await http.get("https://api.test/slow", use_cache=False)
    assert res.status == 503 and route.call_count == 1  # an 8 s wait would exceed the 5 s budget


@respx.mock
async def test_call_budget_is_a_hard_deadline() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    respx.get("https://api.test/slow").mock(side_effect=slow)
    async with httpx.AsyncClient() as client:
        http = make(client, call_budget_s=0.3)
        started = time.perf_counter()
        res = await http.get("https://api.test/slow")
    assert not res.ok and "no answer within" in (res.error or "")
    assert time.perf_counter() - started < 1.0
    assert http.breaker.failures == 1
