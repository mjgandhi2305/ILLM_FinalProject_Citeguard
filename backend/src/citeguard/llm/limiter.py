"""Per-model request / token / daily budgets for Groq.

Groq enforces RPM, RPD, TPM and TPD per model. We pre-acquire with an estimate, then
reconcile with the `x-ratelimit-remaining-*` headers Groq returns on every response."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime


class BudgetExceededError(RuntimeError):
    """The configured daily token budget (or Groq's TPD) is spent."""


@dataclass
class _Bucket:
    rate: float  # units per second
    capacity: float
    tokens: float
    updated: float = field(default_factory=time.monotonic)

    def refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    def wait_for(self, cost: float) -> float:
        self.refill()
        cost = min(cost, self.capacity)
        if self.tokens >= cost:
            return 0.0
        return (cost - self.tokens) / self.rate

    def take(self, cost: float) -> None:
        self.tokens -= min(cost, self.capacity)


@dataclass
class _ModelState:
    requests: _Bucket
    tokens: _Bucket
    day: str = ""
    used_today: int = 0
    blocked_until: float = 0.0


class ModelLimiter:
    def __init__(
        self,
        rpm: int,
        tpm: int,
        tpd: int,
        daily_budget: int | None = None,
        max_wait_s: float = 90.0,
    ) -> None:
        self.rpm, self.tpm, self.tpd = rpm, tpm, tpd
        self.daily_budget = daily_budget
        self.max_wait_s = max_wait_s
        self._state: dict[str, _ModelState] = {}
        self._lock = asyncio.Lock()
        self._global_day = ""
        self._global_used = 0

    def _get(self, model: str) -> _ModelState:
        if model not in self._state:
            self._state[model] = _ModelState(
                requests=_Bucket(self.rpm / 60.0, max(1.0, self.rpm / 6), max(1.0, self.rpm / 6)),
                tokens=_Bucket(self.tpm / 60.0, float(self.tpm), float(self.tpm)),
            )
        return self._state[model]

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def remaining_today(self, model: str) -> int:
        st = self._get(model)
        if st.day != self._today():
            return self.tpd
        return max(0, self.tpd - st.used_today)

    def budget_left(self) -> int | None:
        if self.daily_budget is None:
            return None
        if self._global_day != self._today():
            return self.daily_budget
        return max(0, self.daily_budget - self._global_used)

    async def acquire(self, model: str, est_tokens: int) -> None:
        """Wait until `model` can take a request of ~`est_tokens`; raise if it cannot today."""
        deadline = time.monotonic() + self.max_wait_s
        while True:
            async with self._lock:
                st = self._get(model)
                today = self._today()
                if st.day != today:
                    st.day, st.used_today = today, 0
                if st.used_today + est_tokens > self.tpd:
                    raise BudgetExceededError(f"{model}: daily token limit reached")
                left = self.budget_left()
                if left is not None and est_tokens > left:
                    raise BudgetExceededError("daily LLM token budget reached")
                wait = max(
                    st.requests.wait_for(1),
                    st.tokens.wait_for(est_tokens),
                    st.blocked_until - time.monotonic(),
                )
                if wait <= 0:
                    st.requests.take(1)
                    st.tokens.take(est_tokens)
                    return
            if time.monotonic() + wait > deadline:
                raise TimeoutError(f"{model}: rate-limit wait of {wait:.0f}s exceeds budget")
            await asyncio.sleep(min(wait, 5.0))

    def record(self, model: str, est_tokens: int, actual_tokens: int) -> None:
        st = self._get(model)
        st.used_today += actual_tokens
        st.tokens.tokens -= max(0, actual_tokens - est_tokens)  # pay back under-estimates
        today = self._today()
        if self._global_day != today:
            self._global_day, self._global_used = today, 0
        self._global_used += actual_tokens

    def update_from_headers(self, model: str, headers: Mapping[str, str]) -> None:
        st = self._get(model)
        remaining = headers.get("x-ratelimit-remaining-tokens")
        if remaining is not None:
            try:
                st.tokens.refill()
                st.tokens.tokens = min(st.tokens.tokens, float(remaining))
            except ValueError:
                pass

    def penalize(self, model: str, retry_after_s: float | None) -> None:
        st = self._get(model)
        st.blocked_until = time.monotonic() + (retry_after_s if retry_after_s else 10.0)
