"""Source adapter protocol and helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from citeguard.domain.models import LookupStatus, ParsedReference, Record
from citeguard.sources.http import HttpResult, SourceHttp

IdKind = Literal["doi", "arxiv", "pmid"]


@dataclass
class SearchQuery:
    title: str | None = None
    author: str | None = None  # family name(s) of leading author(s)
    year: int | None = None
    venue: str | None = None
    text: str | None = None  # free text (reformulated queries, alternatives)

    @classmethod
    def from_reference(cls, ref: ParsedReference) -> SearchQuery:
        author = " ".join(a.family for a in ref.authors[:2]) or None
        return cls(title=ref.title, author=author, year=ref.year, venue=ref.container_title)

    def as_text(self) -> str:
        parts = [self.text or self.title or "", self.author or ""]
        return " ".join(p for p in parts if p).strip()

    def describe(self) -> str:
        bits = []
        if self.title:
            bits.append(f'title="{self.title}"')
        if self.text:
            bits.append(f'q="{self.text}"')
        if self.author:
            bits.append(f"author={self.author}")
        if self.year:
            bits.append(f"year={self.year}")
        return ", ".join(bits) or "(empty)"


@dataclass
class SourceResponse:
    status: LookupStatus
    records: list[Record] = field(default_factory=list)
    url: str | None = None
    latency_ms: int = 0
    cached: bool = False
    note: str | None = None


def status_from_http(result: HttpResult, has_records: bool) -> LookupStatus:
    if result.status == -1:
        return LookupStatus.UNAVAILABLE
    if result.status == 429:
        return LookupStatus.RATE_LIMITED
    if result.ok:
        return LookupStatus.FOUND if has_records else LookupStatus.NOT_FOUND
    if result.not_found:
        return LookupStatus.NOT_FOUND
    return LookupStatus.ERROR


def response(
    result: HttpResult, records: list[Record], url: str | None, note: str | None = None
) -> SourceResponse:
    return SourceResponse(
        status=status_from_http(result, bool(records)),
        records=records,
        url=url,
        latency_ms=result.latency_ms,
        cached=result.cached,
        note=note or result.error,
    )


class Source(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]
    rate_per_s: ClassVar[float] = 1.0
    lookup_kinds: ClassVar[frozenset[str]] = frozenset()
    can_search: ClassVar[bool] = True
    # "general" sources are searched first for every citation; "specialist" sources are
    # routed by field / type or used when general sources find nothing.
    tier: ClassVar[Literal["general", "specialist", "registry"]] = "general"

    def __init__(self, http: SourceHttp, contact_email: str) -> None:
        self.http = http
        self.contact_email = contact_email

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        return SourceResponse(status=LookupStatus.UNAVAILABLE, note=f"{kind} lookup unsupported")

    @abstractmethod
    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse: ...

    @property
    def breaker_state(self) -> str:
        return self.http.breaker.state
