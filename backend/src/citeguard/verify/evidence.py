"""Evidence trail for one citation."""

from __future__ import annotations

from typing import Literal

from citeguard.domain.models import Evidence, LookupStatus
from citeguard.sources.base import SourceResponse


class EvidenceLog:
    def __init__(self) -> None:
        self.items: list[Evidence] = []

    def add(
        self,
        source: str,
        operation: Literal["lookup", "search", "registry"],
        query: str,
        resp: SourceResponse,
        *,
        max_records: int = 5,
    ) -> Evidence:
        ev = Evidence(
            id=f"ev{len(self.items) + 1}",
            source=source,
            operation=operation,
            query=query,
            status=resp.status,
            records=resp.records[:max_records],
            url=resp.url,
            latency_ms=resp.latency_ms,
            cached=resp.cached,
            note=resp.note,
        )
        self.items.append(ev)
        return ev

    def get(self, ev_id: str) -> Evidence | None:
        return next((e for e in self.items if e.id == ev_id), None)

    def responded(self, source: str) -> bool:
        """Did `source` answer at least one query (found or definitively not found)?"""
        return any(
            e.source == source and e.status in (LookupStatus.FOUND, LookupStatus.NOT_FOUND)
            for e in self.items
        )

    def failed_sources(self) -> list[str]:
        failed = {
            e.source
            for e in self.items
            if e.status in (LookupStatus.ERROR, LookupStatus.RATE_LIMITED, LookupStatus.UNAVAILABLE)
        }
        return sorted(s for s in failed if not self.responded(s))

    def searched_sources(self) -> list[str]:
        return sorted({e.source for e in self.items if e.operation == "search"})
