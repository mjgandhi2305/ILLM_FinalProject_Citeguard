"""arXiv export API (Atom). Polite limit: one request every three seconds."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from defusedxml import ElementTree

from citeguard.domain.models import CitationType, LookupStatus, Record
from citeguard.match.names import parse_name
from citeguard.match.normalize import fold
from citeguard.parse.identifiers import normalize_doi
from citeguard.sources.base import IdKind, SearchQuery, Source, SourceResponse, response

BASE = "https://export.arxiv.org/api/query"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_ID_RE = re.compile(r"arxiv\.org/abs/(.+?)(v\d+)?$")
_STOP = {"a", "an", "the", "of", "for", "and", "in", "on", "to", "with", "via", "by", "is", "are"}


def parse_feed(xml_text: str) -> list[Record]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    records = []
    for entry in root.findall("a:entry", NS):
        raw_id = (entry.findtext("a:id", default="", namespaces=NS) or "").strip()
        title = re.sub(r"\s+", " ", entry.findtext("a:title", default="", namespaces=NS)).strip()
        m = _ID_RE.search(raw_id)
        if not m or not title or title.lower() == "error":
            continue
        arxiv_id = m.group(1)
        published = entry.findtext("a:published", default="", namespaces=NS)
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            a
            for el in entry.findall("a:author", NS)
            if (a := parse_name(el.findtext("a:name", default="", namespaces=NS)))
        ]
        journal_ref = entry.findtext("arxiv:journal_ref", default=None, namespaces=NS)
        records.append(
            Record(
                source="arxiv",
                source_id=arxiv_id,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                title=title,
                authors=authors,
                year=year,
                container_title=journal_ref.strip() if journal_ref else "arXiv",
                type=CitationType.PREPRINT,
                doi=normalize_doi(entry.findtext("arxiv:doi", default=None, namespaces=NS)),
                arxiv_id=arxiv_id,
                abstract=re.sub(
                    r"\s+", " ", entry.findtext("a:summary", default="", namespaces=NS)
                ).strip()
                or None,
            )
        )
    return records


class Arxiv(Source):
    name = "arxiv"
    display_name = "arXiv"
    rate_per_s = 1 / 3
    lookup_kinds = frozenset({"arxiv"})
    tier = "specialist"

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        if kind != "arxiv":
            return await super().lookup(kind, value)
        res = await self.http.get(BASE, params={"id_list": value, "max_results": 1}, as_json=False)
        records = parse_feed(res.data) if res.ok and isinstance(res.data, str) else []
        return response(res, records, f"https://arxiv.org/abs/{value}")

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        title = query.title or query.text or ""
        words = [w for w in fold(title).split() if w not in _STOP and len(w) > 2]
        if not words:
            return SourceResponse(status=LookupStatus.NOT_FOUND, note="nothing to search")
        words = sorted(set(words), key=len, reverse=True)[:8]
        search_query = " AND ".join(f"ti:{w}" for w in words)
        if query.author:
            search_query += f" AND au:{fold(query.author.split()[0])}"
        params = {"search_query": search_query, "max_results": limit}
        res = await self.http.get(BASE, params=params, as_json=False)
        records = parse_feed(res.data) if res.ok and isinstance(res.data, str) else []
        browse = "https://arxiv.org/search/?" + urlencode(
            {"query": title[:200], "searchtype": "title"}
        )
        return response(res, records, browse)
