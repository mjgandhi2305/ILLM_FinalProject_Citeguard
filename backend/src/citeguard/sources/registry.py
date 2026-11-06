"""Builds the set of source adapters with shared HTTP client, cache, limiters and breakers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from citeguard.config import Settings
from citeguard.sources.arxiv import Arxiv
from citeguard.sources.base import Source
from citeguard.sources.crossref import Crossref
from citeguard.sources.dblp import Dblp
from citeguard.sources.doi_org import DoiOrg
from citeguard.sources.http import SourceHttp
from citeguard.sources.infra import Cache, CircuitBreaker, RateLimiter, TokenBucket
from citeguard.sources.openalex import OpenAlex
from citeguard.sources.pubmed import PubMed
from citeguard.sources.semantic_scholar import SemanticScholar

LimiterFactory = Callable[[str, float], RateLimiter]


def local_limiter(name: str, rate: float) -> RateLimiter:
    return TokenBucket(rate=rate, burst=max(1.0, rate))


@dataclass
class SourceSet:
    doi: DoiOrg | None
    by_name: dict[str, Source] = field(default_factory=dict)

    def general(self) -> list[Source]:
        return [s for s in self.by_name.values() if s.tier == "general"]

    def specialist(self) -> list[Source]:
        return [s for s in self.by_name.values() if s.tier == "specialist"]

    def get(self, name: str) -> Source | None:
        return self.by_name.get(name)

    def health(self) -> dict[str, str]:
        return {name: s.breaker_state for name, s in self.by_name.items()}


def build_sources(
    settings: Settings,
    client: httpx.AsyncClient,
    cache: Cache,
    limiter_factory: LimiterFactory = local_limiter,
    enabled: list[str] | None = None,
) -> SourceSet:
    enabled_names = set(enabled or settings.enabled_sources)
    s2_key = settings.s2_api_key.get_secret_value() if settings.s2_api_key else None
    ncbi_key = settings.ncbi_api_key.get_secret_value() if settings.ncbi_api_key else None
    oa_key = settings.openalex_api_key.get_secret_value() if settings.openalex_api_key else None

    def http_for(cls: type[Source], rate: float | None = None) -> SourceHttp:
        r = rate if rate is not None else cls.rate_per_s
        return SourceHttp(
            cls.name,
            client,
            limiter_factory(cls.name, r),
            cache,
            CircuitBreaker(cls.name),
            max_retries=settings.http_max_retries,
            ttl_hit_s=settings.cache_ttl_hit_s,
            ttl_miss_s=settings.cache_ttl_miss_s,
        )

    email = settings.contact_email
    candidates: list[Source] = []
    doi: DoiOrg | None = None
    if "doi" in enabled_names:
        doi = DoiOrg(http_for(DoiOrg), email)
    if "crossref" in enabled_names:
        candidates.append(Crossref(http_for(Crossref), email))
    if "openalex" in enabled_names:
        candidates.append(OpenAlex(http_for(OpenAlex), email, api_key=oa_key))
    if "semantic_scholar" in enabled_names:
        candidates.append(
            SemanticScholar(
                http_for(SemanticScholar, 1.0 if s2_key else 0.5), email, api_key=s2_key
            )
        )
    if "arxiv" in enabled_names:
        candidates.append(Arxiv(http_for(Arxiv), email))
    if "dblp" in enabled_names:
        candidates.append(Dblp(http_for(Dblp), email))
    if "pubmed" in enabled_names:
        candidates.append(
            PubMed(http_for(PubMed, 8.0 if ncbi_key else 2.5), email, api_key=ncbi_key)
        )
    return SourceSet(doi=doi, by_name={s.name: s for s in candidates})


def make_http_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_s, connect=10.0),
        headers={"User-Agent": settings.user_agent},
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
