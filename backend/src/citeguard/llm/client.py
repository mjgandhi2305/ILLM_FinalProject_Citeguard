"""Groq client wrapper: strict JSON-schema calls with budgets, caching and fallbacks.

Every LLM call in CiteGuard goes through `GroqLLM.structured`. It never raises for
model-side trouble: it returns `(None, usage)` and the caller falls back to deterministic
behaviour. A citation check never fails because of the LLM."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, TypeVar

import groq
import structlog
from pydantic import BaseModel, ValidationError

from citeguard.domain.models import LLMUsage
from citeguard.llm.limiter import BudgetExceededError, ModelLimiter
from citeguard.llm.schema import schema_name, strict_schema
from citeguard.observability.metrics import LLM_CALLS, LLM_TOKENS
from citeguard.sources.infra import Cache, NullCache

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high"]
LLM_CACHE_TTL_S = 30 * 24 * 3600
PROMPT_VERSION = "2026-11-02"


@dataclass(frozen=True)
class StageConfig:
    model: str
    effort: Effort
    max_tokens: int


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


class GroqLLM:
    def __init__(
        self,
        client: groq.AsyncGroq,
        limiter: ModelLimiter,
        *,
        cache: Cache | None = None,
        fallback_models: list[str] | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.client = client
        self.limiter = limiter
        self.cache = cache or NullCache()
        self.fallback_models = fallback_models or []
        self.timeout_s = timeout_s

    def _cache_key(self, model: str, schema: type[BaseModel], system: str, user: str) -> str:
        blob = json.dumps(
            [PROMPT_VERSION, model, schema_name(schema), strict_schema(schema), system, user],
            sort_keys=True,
        )
        return "llm:" + hashlib.sha256(blob.encode()).hexdigest()[:40]

    async def structured(
        self,
        stage: StageConfig,
        system: str,
        user: str,
        schema: type[T],
        *,
        use_cache: bool = True,
    ) -> tuple[T | None, LLMUsage]:
        usage = LLMUsage()
        key = self._cache_key(stage.model, schema, system, user)
        if use_cache:
            hit = await self.cache.get(key)
            if hit is not None:
                try:
                    usage.cached_calls += 1
                    return schema.model_validate(hit), usage
                except ValidationError:
                    pass

        queue = [stage.model] + [m for m in self.fallback_models if m != stage.model]
        retried: set[str] = set()
        json_schema = strict_schema(schema)
        while queue:
            model = queue.pop(0)
            est = estimate_tokens(system + user) + stage.max_tokens // 2
            try:
                await self.limiter.acquire(model, est)
            except (BudgetExceededError, TimeoutError) as exc:
                log.info("llm.skip_model", model=model, reason=str(exc))
                usage.failures += 1
                continue
            try:
                raw = await self.client.chat.completions.with_raw_response.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name(schema),
                            "strict": True,
                            "schema": json_schema,
                        },
                    },
                    reasoning_effort=stage.effort,
                    include_reasoning=False,
                    max_completion_tokens=stage.max_tokens,
                    timeout=self.timeout_s,
                )
            except groq.RateLimitError as exc:
                retry_after = _retry_after(exc.response.headers if exc.response else {})
                self.limiter.penalize(model, retry_after)
                self.limiter.record(model, est, 0)
                log.warning("llm.rate_limited", model=model, retry_after=retry_after)
                LLM_CALLS.labels(model=model, outcome="rate_limited").inc()
                usage.failures += 1
                continue
            except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as exc:
                log.warning("llm.transient_error", model=model, error=str(exc))
                usage.failures += 1
                continue
            except groq.BadRequestError as exc:  # e.g. json_validate_failed
                log.warning("llm.bad_request", model=model, error=str(exc)[:300])
                usage.failures += 1
                if _generation_failed(exc) and model not in retried:
                    # Malformed or empty output is stochastic: one more try on the same model
                    # before falling back.
                    retried.add(model)
                    queue.insert(0, model)
                continue
            except groq.APIStatusError as exc:
                log.warning("llm.api_error", model=model, status=exc.status_code)
                usage.failures += 1
                continue

            self.limiter.update_from_headers(model, raw.headers)
            completion = await raw.parse()
            used_in = completion.usage.prompt_tokens if completion.usage else 0
            used_out = completion.usage.completion_tokens if completion.usage else 0
            self.limiter.record(model, est, used_in + used_out)
            usage.calls += 1
            usage.input_tokens += used_in
            usage.output_tokens += used_out
            LLM_TOKENS.labels(model=model, direction="input").inc(used_in)
            LLM_TOKENS.labels(model=model, direction="output").inc(used_out)

            content = completion.choices[0].message.content if completion.choices else None
            if not content:
                usage.failures += 1
                continue
            try:
                parsed = schema.model_validate_json(content)
            except ValidationError as exc:
                log.warning("llm.schema_violation", model=model, error=str(exc)[:300])
                usage.failures += 1
                continue
            if use_cache:
                await self.cache.set(key, parsed.model_dump(mode="json"), LLM_CACHE_TTL_S)
            LLM_CALLS.labels(model=model, outcome="ok").inc()
            return parsed, usage
        return None, usage


def _generation_failed(exc: groq.BadRequestError) -> bool:
    """Groq's 400 for output that did not match the schema (not a problem with the request)."""
    body = exc.body if isinstance(exc.body, dict) else {}
    err = body.get("error", body)
    return isinstance(err, dict) and err.get("code") in (
        "json_validate_failed",
        "output_parse_failed",
    )


def _retry_after(headers: object) -> float | None:
    try:
        value = headers.get("retry-after")  # type: ignore[attr-defined]
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
