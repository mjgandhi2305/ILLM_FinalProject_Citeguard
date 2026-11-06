"""Conversion of CSL-JSON and Crossref `message` objects into `Record`s."""

from __future__ import annotations

import re
from typing import Any

from citeguard.domain.models import Author, CitationType, Record
from citeguard.match.names import parse_name
from citeguard.parse.identifiers import normalize_doi

_TYPE_MAP: dict[str, CitationType] = {
    "journal-article": CitationType.ARTICLE_JOURNAL,
    "article-journal": CitationType.ARTICLE_JOURNAL,
    "article-magazine": CitationType.ARTICLE_JOURNAL,
    "article-newspaper": CitationType.OTHER,
    "proceedings-article": CitationType.PAPER_CONFERENCE,
    "paper-conference": CitationType.PAPER_CONFERENCE,
    "posted-content": CitationType.PREPRINT,
    "preprint": CitationType.PREPRINT,
    "article": CitationType.PREPRINT,  # CSL "article" = unpublished / preprint
    "book": CitationType.BOOK,
    "monograph": CitationType.BOOK,
    "edited-book": CitationType.BOOK,
    "reference-book": CitationType.BOOK,
    "book-chapter": CitationType.CHAPTER,
    "chapter": CitationType.CHAPTER,
    "book-section": CitationType.CHAPTER,
    "dissertation": CitationType.THESIS,
    "thesis": CitationType.THESIS,
    "report": CitationType.REPORT,
    "dataset": CitationType.DATASET,
    "webpage": CitationType.WEBPAGE,
}

_TAG_RE = re.compile(r"<[^>]+>")


def map_type(value: str | None) -> CitationType:
    if not value:
        return CitationType.UNKNOWN
    return _TYPE_MAP.get(value.lower(), CitationType.OTHER)


def first_str(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str):
        cleaned = _TAG_RE.sub("", value).strip()
        return re.sub(r"\s+", " ", cleaned) or None
    return None


def csl_year(item: dict[str, Any]) -> int | None:
    for key in ("issued", "published-print", "published-online", "published", "created"):
        parts = (item.get(key) or {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return None


def csl_authors(item: dict[str, Any]) -> list[Author]:
    authors: list[Author] = []
    for a in item.get("author") or []:
        if a.get("family"):
            authors.append(Author(family=a["family"], given=a.get("given")))
        elif a.get("name") or a.get("literal"):
            parsed = parse_name(a.get("name") or a.get("literal"))
            if parsed:
                authors.append(parsed)
    return authors


def is_retracted_crossref(item: dict[str, Any]) -> bool | None:
    for rel in item.get("updated-by") or []:
        if str(rel.get("type", "")).lower() in {"retraction", "removal", "withdrawal"}:
            return True
    return None


def csl_to_record(item: dict[str, Any], source: str, url: str | None = None) -> Record:
    doi = normalize_doi(item.get("DOI") or item.get("doi"))
    container = first_str(item.get("container-title")) or first_str(
        item.get("short-container-title")
    )
    if not container and item.get("event"):
        event = item["event"]
        container = event.get("name") if isinstance(event, dict) else first_str(event)
    return Record(
        source=source,
        source_id=doi or first_str(item.get("title")) or "unknown",
        url=url or (f"https://doi.org/{doi}" if doi else item.get("URL")),
        title=first_str(item.get("title")),
        authors=csl_authors(item),
        year=csl_year(item),
        container_title=container,
        volume=str(item["volume"]) if item.get("volume") else None,
        issue=str(item["issue"]) if item.get("issue") else None,
        pages=str(item.get("page")) if item.get("page") else None,
        publisher=first_str(item.get("publisher")),
        type=map_type(item.get("type")),
        doi=doi,
        abstract=first_str(item.get("abstract")),
        is_retracted=is_retracted_crossref(item),
        cited_by=item.get("is-referenced-by-count"),
    )
