"""OpenAlex works API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from citeguard.domain.models import CitationType, LookupStatus, Record
from citeguard.match.names import parse_name
from citeguard.parse.identifiers import normalize_doi
from citeguard.sources.base import IdKind, SearchQuery, Source, SourceResponse, response
from citeguard.sources.http import SourceHttp

BASE = "https://api.openalex.org"
SELECT = (
    "id,doi,display_name,publication_year,authorships,primary_location,type,biblio,"
    "is_retracted,ids,abstract_inverted_index,cited_by_count"
)


def _abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    positions = [(pos, word) for word, idxs in inverted.items() for pos in idxs]
    return " ".join(word for _, word in sorted(positions))[:4000] or None


def _type(work: dict[str, Any]) -> CitationType:
    t = (work.get("type") or "").lower()
    source_type = ((work.get("primary_location") or {}).get("source") or {}).get("type")
    if t == "article":
        if source_type == "conference":
            return CitationType.PAPER_CONFERENCE
        if source_type == "repository":
            return CitationType.PREPRINT
        return CitationType.ARTICLE_JOURNAL
    return {
        "preprint": CitationType.PREPRINT,
        "book": CitationType.BOOK,
        "book-chapter": CitationType.CHAPTER,
        "dissertation": CitationType.THESIS,
        "dataset": CitationType.DATASET,
        "report": CitationType.REPORT,
    }.get(t, CitationType.OTHER)


def work_to_record(work: dict[str, Any]) -> Record:
    authors = []
    for a in work.get("authorships") or []:
        name = (a.get("author") or {}).get("display_name") or a.get("raw_author_name")
        parsed = parse_name(name) if name else None
        if parsed:
            authors.append(parsed)
    biblio = work.get("biblio") or {}
    pages = None
    if biblio.get("first_page"):
        pages = biblio["first_page"]
        if biblio.get("last_page") and biblio["last_page"] != biblio["first_page"]:
            pages = f"{pages}-{biblio['last_page']}"
    source = (work.get("primary_location") or {}).get("source") or {}
    ids = work.get("ids") or {}
    pmid = str(ids["pmid"]).rsplit("/", 1)[-1] if ids.get("pmid") else None
    return Record(
        source="openalex",
        source_id=str(work.get("id", "")).rsplit("/", 1)[-1],
        url=work.get("id"),
        title=work.get("display_name"),
        authors=authors,
        year=work.get("publication_year"),
        container_title=source.get("display_name"),
        volume=biblio.get("volume"),
        issue=biblio.get("issue"),
        pages=pages,
        publisher=source.get("host_organization_name"),
        type=_type(work),
        doi=normalize_doi(work.get("doi")),
        pmid=pmid,
        abstract=_abstract(work.get("abstract_inverted_index")),
        is_retracted=work.get("is_retracted"),
        cited_by=work.get("cited_by_count"),
    )


class OpenAlex(Source):
    name = "openalex"
    display_name = "OpenAlex"
    rate_per_s = 8.0
    lookup_kinds = frozenset({"doi", "pmid"})
    tier = "general"

    def __init__(self, http: SourceHttp, contact_email: str, api_key: str | None = None) -> None:
        super().__init__(http, contact_email)
        # Sent as a header so the key never appears in URLs, logs or cache keys.
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = {"mailto": self.contact_email, "select": SELECT, **extra}
        return params

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        if kind not in ("doi", "pmid"):
            return await super().lookup(kind, value)
        url = f"{BASE}/works/{kind}:{quote(value, safe='/()._-:;')}"
        res = await self.http.get(url, params=self._params(), headers=self.headers)
        records = [work_to_record(res.data)] if res.ok and isinstance(res.data, dict) else []
        browse = records[0].url if records else f"https://openalex.org/works?search={quote(value)}"
        return response(res, records, browse)

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        text = (query.text or query.title or "").strip()
        if not text:
            return SourceResponse(status=LookupStatus.NOT_FOUND, note="nothing to search")
        # Commas/colons are fine in `search`; strip characters OpenAlex rejects.
        cleaned = text.replace("|", " ").replace("!", " ")[:300]
        res = await self.http.get(
            f"{BASE}/works",
            params=self._params(search=cleaned, **{"per-page": limit}),
            headers=self.headers,
        )
        records = []
        if res.ok and isinstance(res.data, dict):
            records = [work_to_record(w) for w in res.data.get("results") or []]
        return response(
            res, records, "https://openalex.org/works?" + urlencode({"search": cleaned})
        )
