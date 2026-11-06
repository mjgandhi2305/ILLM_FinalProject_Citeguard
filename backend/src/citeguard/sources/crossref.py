"""Crossref REST API (polite pool)."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from citeguard.domain.models import LookupStatus
from citeguard.sources.base import IdKind, SearchQuery, Source, SourceResponse, response
from citeguard.sources.csl import csl_to_record

BASE = "https://api.crossref.org"


class Crossref(Source):
    name = "crossref"
    display_name = "Crossref"
    rate_per_s = 5.0
    lookup_kinds = frozenset({"doi"})
    tier = "general"

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        if kind != "doi":
            return await super().lookup(kind, value)
        url = f"{BASE}/works/{quote(value, safe='/()._-:;')}"
        res = await self.http.get(url, params={"mailto": self.contact_email})
        records = []
        if res.ok and isinstance(res.data, dict) and res.data.get("message"):
            records = [csl_to_record(res.data["message"], source=self.name)]
        return response(res, records, f"https://search.crossref.org/?q={quote(value)}")

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        biblio = " ".join(
            str(p) for p in (query.text or query.title, query.year, query.venue) if p
        ).strip()
        if not biblio:
            return SourceResponse(status=LookupStatus.NOT_FOUND, note="nothing to search")
        params: dict[str, str | int] = {
            "query.bibliographic": biblio[:500],
            "rows": limit,
            "mailto": self.contact_email,
        }
        if query.author:
            params["query.author"] = query.author
        res = await self.http.get(f"{BASE}/works", params=params)
        records = []
        if res.ok and isinstance(res.data, dict):
            items = (res.data.get("message") or {}).get("items") or []
            records = [csl_to_record(item, source=self.name) for item in items]
        browse = "https://search.crossref.org/?" + urlencode({"q": biblio[:200]})
        return response(res, records, browse)
