"""Prometheus metrics (no-op stand-ins when prometheus_client is not installed)."""

from __future__ import annotations

from typing import Any


class _Noop:
    def labels(self, **_: Any) -> _Noop:
        return self

    def inc(self, amount: float = 1) -> None:
        return None

    def observe(self, amount: float) -> None:
        return None


try:
    from prometheus_client import Counter, Histogram

    SOURCE_REQUESTS: Any = Counter(
        "citeguard_source_requests_total",
        "Outbound scholarly-source requests",
        ["source", "outcome"],
    )
    SOURCE_LATENCY: Any = Histogram(
        "citeguard_source_latency_seconds", "Outbound request latency", ["source"]
    )
    LLM_TOKENS: Any = Counter("citeguard_llm_tokens_total", "LLM tokens", ["model", "direction"])
    LLM_CALLS: Any = Counter("citeguard_llm_calls_total", "LLM calls", ["model", "outcome"])
    CHECKS_TOTAL: Any = Counter("citeguard_checks_total", "Checks finished", ["status"])
    VERDICTS_TOTAL: Any = Counter("citeguard_verdicts_total", "Citation verdicts", ["verdict"])
except ImportError:  # pragma: no cover - core install without the server extra
    SOURCE_REQUESTS = SOURCE_LATENCY = LLM_TOKENS = LLM_CALLS = _Noop()
    CHECKS_TOTAL = VERDICTS_TOTAL = _Noop()
