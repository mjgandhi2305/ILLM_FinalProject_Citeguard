"""BibTeX ingestion. BibTeX is already structured, so no LLM parsing is needed."""

from __future__ import annotations

import re

from bibtexparser.entrypoint import parse_string

from citeguard.domain.models import Author, CitationType, Identifiers, ParsedReference
from citeguard.match.names import has_et_al, parse_name
from citeguard.match.normalize import latex_to_text
from citeguard.parse.identifiers import (
    extract_arxiv_id,
    normalize_arxiv_id,
    normalize_doi,
)

_TYPE_MAP = {
    "article": CitationType.ARTICLE_JOURNAL,
    "inproceedings": CitationType.PAPER_CONFERENCE,
    "conference": CitationType.PAPER_CONFERENCE,
    "proceedings": CitationType.BOOK,
    "book": CitationType.BOOK,
    "inbook": CitationType.CHAPTER,
    "incollection": CitationType.CHAPTER,
    "phdthesis": CitationType.THESIS,
    "mastersthesis": CitationType.THESIS,
    "thesis": CitationType.THESIS,
    "techreport": CitationType.REPORT,
    "report": CitationType.REPORT,
    "online": CitationType.WEBPAGE,
    "dataset": CitationType.DATASET,
}


def _split_and(value: str) -> list[str]:
    """Split a BibTeX author field on top-level ' and ' (ignoring braced groups)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    tokens = re.split(r"(\{|\}|\s+and\s+)", value, flags=re.IGNORECASE)
    for tok in tokens:
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        if depth == 0 and re.fullmatch(r"\s+and\s+", tok or "", flags=re.IGNORECASE):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(tok)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = latex_to_text(value).replace("{", "").replace("}", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def bibtex_authors(value: str) -> tuple[list[Author], bool]:
    truncated = False
    authors: list[Author] = []
    for chunk in _split_and(value):
        if chunk.lower() in {"others", "et al.", "et al"} or has_et_al(chunk):
            truncated = True
            continue
        if chunk.startswith("{") and chunk.endswith("}") and "," not in chunk:
            authors.append(Author(family=_clean(chunk) or chunk))  # corporate author
            continue
        parsed = parse_name(chunk)
        if parsed:
            authors.append(
                Author(family=_clean(parsed.family) or parsed.family, given=_clean(parsed.given))
            )
    return authors, truncated


def _year(fields: dict[str, str]) -> int | None:
    for key in ("year", "date"):
        m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", fields.get(key, ""))
        if m:
            return int(m.group(1))
    return None


def _raw_display(fields: dict[str, str], authors: list[Author]) -> str:
    bits = [
        ", ".join(a.display() for a in authors[:6]) + (" et al." if len(authors) > 6 else ""),
        f"({fields.get('year', 'n.d.')})",
        _clean(fields.get("title")) or "",
        _clean(fields.get("journal") or fields.get("booktitle")) or "",
    ]
    return ". ".join(b for b in bits if b).replace(". (", " (")


def entry_to_reference(entry_type: str, key: str, fields: dict[str, str]) -> ParsedReference:
    authors, truncated = bibtex_authors(fields.get("author", "") or fields.get("editor", ""))
    etype = entry_type.lower()
    ctype = _TYPE_MAP.get(etype, CitationType.OTHER)

    eprint = fields.get("eprint")
    archive = (fields.get("archiveprefix") or fields.get("eprinttype") or "").lower()
    arxiv_id = None
    if eprint and (archive == "arxiv" or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", eprint)):
        arxiv_id = normalize_arxiv_id(eprint)
    for f in ("journal", "note", "howpublished", "url"):
        if not arxiv_id and fields.get(f):
            arxiv_id = extract_arxiv_id(fields[f])
    venue = _clean(fields.get("journal") or fields.get("booktitle") or fields.get("howpublished"))
    if etype in {"misc", "unpublished", "article"} and (
        arxiv_id and (not venue or "arxiv" in (venue or "").lower())
    ):
        ctype = CitationType.PREPRINT

    pmid = fields.get("pmid")
    doi = normalize_doi(fields.get("doi") or "") or normalize_doi(fields.get("url") or "")
    return ParsedReference(
        raw=_raw_display(fields, authors),
        authors=authors,
        authors_truncated=truncated,
        title=_clean(fields.get("title")),
        container_title=venue,
        year=_year(fields),
        volume=_clean(fields.get("volume")),
        issue=_clean(fields.get("number") or fields.get("issue")),
        pages=_clean(fields.get("pages")),
        publisher=_clean(fields.get("publisher")),
        type=ctype,
        ids=Identifiers(
            doi=doi,
            arxiv_id=arxiv_id,
            pmid=pmid.strip() if pmid else None,
            isbn=_clean(fields.get("isbn")),
            url=fields.get("url"),
        ),
        parse_method="bibtex",
        parse_confidence=1.0,
        key=key,
    )


def parse_bibtex(text: str) -> tuple[list[ParsedReference], list[str]]:
    """Return (references, warnings)."""
    library = parse_string(text)
    refs = []
    for entry in library.entries:
        fields = {f.key.lower(): str(f.value) for f in entry.fields}
        if entry.entry_type.lower() in {"comment", "string", "preamble"}:
            continue
        refs.append(entry_to_reference(entry.entry_type, entry.key, fields))
    warnings = [
        f"Could not parse BibTeX block starting at line {b.start_line}"
        for b in library.failed_blocks
    ]
    return refs, warnings
