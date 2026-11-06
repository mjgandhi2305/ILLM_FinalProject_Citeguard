"""Semantic Scholar Graph API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from citeguard.domain.models import CitationType, LookupStatus, Record
from citeguard.match.names import parse_name
from citeguard.parse.identifiers import normalize_doi
from citeguard.sources.base import IdKind, SearchQuery, Source, SourceResponse, response
from citeguard.sources.http import SourceHttp

BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = (
    "title,authors,year,venue,publicationVenue,externalIds,journal,publicationTypes,"
    "abstract,citationCount,url"
)


def _type(paper: dict[str, Any]) -> CitationType:
    types = [t.lower() for t in paper.get("publicationTypes") or []]
    ext = paper.get("externalIds") or {}
    if "conference" in types:
        return CitationType.PAPER_CONFERENCE
    if "journalarticle" in types or "review" in types:
        return CitationType.ARTICLE_JOURNAL
    if "book" in types:
        return CitationType.BOOK
    if "booksection" in types:
        return CitationType.CHAPTER
    if "dataset" in types:
        return CitationType.DATASET
    if ext.get("ArXiv") and not paper.get("venue"):
        return CitationType.PREPRINT
    return CitationType.UNKNOWN


def paper_to_record(paper: dict[str, Any]) -> Record:
    ext = paper.get("externalIds") or {}
    journal = paper.get("journal") or {}
    venue = (
        (paper.get("publicationVenue") or {}).get("name")
        or paper.get("venue")
        or journal.get("name")
        or None
    )
    authors = [a for p in paper.get("authors") or [] if (a := parse_name(p.get("name") or ""))]
    return Record(
        source="semantic_scholar",
        source_id=str(paper.get("paperId", "")),
        url=paper.get("url"),
        title=paper.get("title"),
        authors=authors,
        year=paper.get("year"),
        container_title=venue,
        volume=(journal.get("volume") or "").strip() or None,
        pages=(journal.get("pages") or "").strip() or None,
        type=_type(paper),
        doi=normalize_doi(ext.get("DOI")),
        arxiv_id=ext.get("ArXiv"),
        pmid=str(ext["PubMed"]) if ext.get("PubMed") else None,
        abstract=paper.get("abstract"),
        cited_by=paper.get("citationCount"),
    )


class SemanticScholar(Source):
    name = "semantic_scholar"
    display_name = "Semantic Scholar"
    rate_per_s = 1.0
    lookup_kinds = frozenset({"doi", "arxiv", "pmid"})
    tier = "general"

    def __init__(self, http: SourceHttp, contact_email: str, api_key: str | None = None) -> None:
        super().__init__(http, contact_email)
        self.headers = {"x-api-key": api_key} if api_key else None

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        prefix = {"doi": "DOI", "arxiv": "ARXIV", "pmid": "PMID"}[kind]
        url = f"{BASE}/paper/{prefix}:{quote(value, safe='/()._-:;')}"
        res = await self.http.get(url, params={"fields": FIELDS}, headers=self.headers)
        records = [paper_to_record(res.data)] if res.ok and isinstance(res.data, dict) else []
        browse = records[0].url if records else None
        return response(res, records, browse)

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        """Best-title match (`/paper/search/match`) for citation verification."""
        title = (query.title or query.text or "").strip()
        if not title:
            return SourceResponse(status=LookupStatus.NOT_FOUND, note="nothing to search")
        res = await self.http.get(
            f"{BASE}/paper/search/match",
            params={"query": title[:300], "fields": FIELDS},
            headers=self.headers,
        )
        records = []
        if res.ok and isinstance(res.data, dict):
            records = [paper_to_record(p) for p in res.data.get("data") or []]
        browse = "https://www.semanticscholar.org/search?" + urlencode({"q": title[:200]})
        return response(res, records, browse)

    async def relevance_search(self, text: str, limit: int = 10) -> SourceResponse:
        """Topical search used for suggesting real alternatives."""
        res = await self.http.get(
            f"{BASE}/paper/search",
            params={"query": text[:300], "limit": limit, "fields": FIELDS},
            headers=self.headers,
        )
        records = []
        if res.ok and isinstance(res.data, dict):
            records = [paper_to_record(p) for p in res.data.get("data") or []]
        browse = "https://www.semanticscholar.org/search?" + urlencode({"q": text[:200]})
        return response(res, records, browse)
