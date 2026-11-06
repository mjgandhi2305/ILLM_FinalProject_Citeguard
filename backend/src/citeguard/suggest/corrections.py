"""Corrected citation for real-but-wrong references, merged from the same-work group."""

from __future__ import annotations

from collections.abc import Sequence

from citeguard.domain.models import (
    Candidate,
    CitationResult,
    CitationType,
    FieldDiff,
    Record,
    Severity,
    Suggestion,
    Verdict,
)
from citeguard.match.linkage import STRONG_TITLE
from citeguard.match.normalize import title_similarity
from citeguard.match.venues import is_preprint_venue
from citeguard.parse.identifiers import normalize_doi
from citeguard.suggest.format import format_record

# Most authoritative metadata first.
_AUTHORITY = ["crossref", "doi", "pubmed", "openalex", "semantic_scholar", "dblp", "arxiv"]


def _rank(rec: Record) -> int:
    return _AUTHORITY.index(rec.source) if rec.source in _AUTHORITY else len(_AUTHORITY)


def _same_era(a: Record, b: Record) -> bool:
    """Excludes late re-deposits (Zenodo copies etc.) that share a famous paper's title."""
    return not (a.year and b.year and abs(a.year - b.year) > 1)


def merge_records(best: Record, group: list[Candidate]) -> Record:
    """Start from the matched record (upgraded to its published version when the match is a
    preprint) and fill gaps from same-era records of the group, most authoritative first."""
    recs = sorted({id(c.record): c.record for c in group}.values(), key=_rank)
    base = best
    if base.type == CitationType.PREPRINT or is_preprint_venue(base.container_title):
        published = [
            r
            for r in recs
            if r.container_title
            and not is_preprint_venue(r.container_title)
            and r.type in (CitationType.ARTICLE_JOURNAL, CitationType.PAPER_CONFERENCE)
            and _same_era(r, base)
        ]
        if published:
            base = published[0]
    merged = base.model_copy(deep=True)
    for r in (r for r in recs if _same_era(r, merged)):
        for f in ("doi", "volume", "issue", "pages", "container_title", "publisher", "arxiv_id"):
            if not getattr(merged, f) and getattr(r, f):
                setattr(merged, f, getattr(r, f))
        if not merged.authors and r.authors:
            merged.authors = r.authors
        if len(r.authors) > len(merged.authors) and r.source != "arxiv":
            merged.authors = r.authors
    return merged


def correction(result: CitationResult, styles: Sequence[str]) -> Suggestion | None:
    if result.verdict not in (Verdict.VERIFIED_WITH_ERRORS, Verdict.MISATTRIBUTED):
        return None
    if result.best_match is None:
        return None
    group = [
        c
        for c in result.candidates
        if c is result.best_match
        or normalize_doi(c.record.doi) == normalize_doi(result.best_match.record.doi)
        or title_similarity(c.record.title, result.best_match.record.title) >= STRONG_TITLE
    ] or [result.best_match]
    merged = merge_records(result.best_match.record, group)
    diffs = [
        FieldDiff(field=d.field or d.code.value, claimed=d.claimed, actual=d.actual)
        for d in result.discrepancies
        if d.severity != Severity.INFO and d.field
    ]
    return Suggestion(
        kind="correction",
        record=merged,
        formatted=format_record(merged, styles),
        diffs=diffs,
        method="deterministic",
    )
