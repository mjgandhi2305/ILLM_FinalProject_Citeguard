"""PubMed via NCBI E-utilities (biomedical literature)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from citeguard.domain.models import CitationType, LookupStatus, Record
from citeguard.match.names import parse_name
from citeguard.parse.identifiers import normalize_doi
from citeguard.sources.base import IdKind, SearchQuery, Source, SourceResponse, response
from citeguard.sources.http import SourceHttp

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def summary_to_record(pmid: str, item: dict[str, Any]) -> Record:
    authors = [
        a
        for au in item.get("authors") or []
        if au.get("authtype", "Author") == "Author" and (a := parse_name(au.get("name") or ""))
    ]
    year_match = re.match(r"(\d{4})", item.get("pubdate") or item.get("epubdate") or "")
    doi = next(
        (x.get("value") for x in item.get("articleids") or [] if x.get("idtype") == "doi"), None
    )
    return Record(
        source="pubmed",
        source_id=pmid,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        title=(item.get("title") or "").rstrip(".") or None,
        authors=authors,
        year=int(year_match.group(1)) if year_match else None,
        container_title=item.get("fulljournalname") or item.get("source"),
        volume=item.get("volume") or None,
        issue=item.get("issue") or None,
        pages=item.get("pages") or None,
        type=CitationType.ARTICLE_JOURNAL,
        doi=normalize_doi(doi),
        pmid=pmid,
        is_retracted=True if "Retracted Publication" in (item.get("pubtype") or []) else None,
    )


class PubMed(Source):
    name = "pubmed"
    display_name = "PubMed"
    rate_per_s = 2.5
    lookup_kinds = frozenset({"pmid"})
    tier = "specialist"

    def __init__(self, http: SourceHttp, contact_email: str, api_key: str | None = None) -> None:
        super().__init__(http, contact_email)
        self.api_key = api_key

    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = {"tool": "citeguard", "email": self.contact_email, **extra}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    async def _summaries(self, ids: list[str]) -> tuple[list[Record], Any]:
        res = await self.http.get(
            f"{BASE}/esummary.fcgi",
            params=self._params(db="pubmed", id=",".join(ids), retmode="json"),
        )
        records = []
        if res.ok and isinstance(res.data, dict):
            result = res.data.get("result") or {}
            for pmid in result.get("uids") or []:
                item = result.get(pmid) or {}
                if item.get("title"):
                    records.append(summary_to_record(pmid, item))
        return records, res

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        if kind != "pmid":
            return await super().lookup(kind, value)
        records, res = await self._summaries([value])
        return response(res, records, f"https://pubmed.ncbi.nlm.nih.gov/{value}/")

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        title = (query.title or query.text or "").strip()
        if not title:
            return SourceResponse(status=LookupStatus.NOT_FOUND, note="nothing to search")
        clean = re.sub(r"[\[\]()\"]", " ", title)[:250]
        term = f"{clean}[Title]" if query.title else clean
        res = await self.http.get(
            f"{BASE}/esearch.fcgi",
            params=self._params(db="pubmed", term=term, retmode="json", retmax=limit),
        )
        browse = "https://pubmed.ncbi.nlm.nih.gov/?" + urlencode({"term": clean})
        if not (res.ok and isinstance(res.data, dict)):
            return response(res, [], browse)
        ids = (res.data.get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return response(res, [], browse)
        records, sres = await self._summaries(ids[:limit])
        return response(sres, records, browse)
