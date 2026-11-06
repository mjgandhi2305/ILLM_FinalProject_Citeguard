"""DBLP publication search (computer science)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from citeguard.domain.models import CitationType, LookupStatus, Record
from citeguard.match.names import parse_name
from citeguard.parse.identifiers import normalize_doi
from citeguard.sources.base import SearchQuery, Source, SourceResponse, response

BASE = "https://dblp.org/search/publ/api"

_TYPE_MAP = {
    "conference and workshop papers": CitationType.PAPER_CONFERENCE,
    "journal articles": CitationType.ARTICLE_JOURNAL,
    "informal and other publications": CitationType.PREPRINT,
    "books and theses": CitationType.BOOK,
    "parts in books or collections": CitationType.CHAPTER,
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def hit_to_record(info: dict[str, Any]) -> Record:
    authors = []
    for a in _as_list((info.get("authors") or {}).get("author")):
        name = a.get("text") if isinstance(a, dict) else a
        parsed = parse_name(name) if name else None
        if parsed:
            authors.append(parsed)
    venue = info.get("venue")
    if isinstance(venue, list):
        venue = venue[0] if venue else None
    year = info.get("year")
    title = (info.get("title") or "").rstrip(".") or None
    rtype = _TYPE_MAP.get(str(info.get("type", "")).lower(), CitationType.OTHER)
    ee = _as_list(info.get("ee"))
    arxiv_id = None
    for link in ee:
        if isinstance(link, str) and "arxiv.org/abs/" in link:
            arxiv_id = link.rsplit("/abs/", 1)[1]
    return Record(
        source="dblp",
        source_id=str(info.get("key", "")),
        url=info.get("url"),
        title=title,
        authors=authors,
        year=int(year) if year and str(year).isdigit() else None,
        container_title=venue,
        volume=info.get("volume"),
        issue=info.get("number"),
        pages=info.get("pages"),
        type=rtype,
        doi=normalize_doi(info.get("doi")),
        arxiv_id=arxiv_id,
    )


class Dblp(Source):
    name = "dblp"
    display_name = "DBLP"
    rate_per_s = 1.0
    tier = "specialist"

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        text = (query.title or query.text or "").strip()
        if not text:
            return SourceResponse(status=LookupStatus.NOT_FOUND, note="nothing to search")
        params = {"q": text[:250], "format": "json", "h": limit}
        res = await self.http.get(BASE, params=params)
        records = []
        if res.ok and isinstance(res.data, dict):
            hits = ((res.data.get("result") or {}).get("hits") or {}).get("hit") or []
            records = [hit_to_record(h.get("info") or {}) for h in hits]
        return response(res, records, "https://dblp.org/search?" + urlencode({"q": text[:200]}))
