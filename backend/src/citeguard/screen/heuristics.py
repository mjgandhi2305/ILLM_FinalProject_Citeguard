"""Offline screening: cheap signals available before any network call."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from citeguard.domain.models import CitationType, ParsedReference, RiskSignal
from citeguard.match.venues import canonical_venue
from citeguard.parse.identifiers import (
    DOI_PREFIX_PUBLISHER,
    arxiv_id_year,
    doi_prefix,
    is_valid_doi_syntax,
)

# venue keyword -> DOI prefixes that publisher uses
_VENUE_PUBLISHER_PREFIXES: dict[str, set[str]] = {
    "ieee": {"10.1109"},
    "acm": {"10.1145"},
    "plos": {"10.1371"},
    "springer": {"10.1007", "10.1186"},
    "elsevier": {"10.1016"},
    "wiley": {"10.1002", "10.1111"},
    "mdpi": {"10.3390"},
    "frontiers": {"10.3389"},
}
_NATURE_VENUE = re.compile(r"^nature\b", re.IGNORECASE)


def screen(ref: ParsedReference, now: datetime | None = None) -> tuple[float, list[RiskSignal]]:
    """Return (risk score in [0, 1], signals)."""
    now = now or datetime.now(UTC)
    signals: list[RiskSignal] = []

    def add(code: str, message: str, weight: float) -> None:
        signals.append(RiskSignal(code=code, message=message, weight=weight))

    doi = ref.ids.doi
    if doi and not is_valid_doi_syntax(doi):
        add("DOI_SYNTAX", f"DOI '{doi}' is not syntactically valid", 0.5)

    venue = (ref.container_title or "").lower()
    if doi and venue and is_valid_doi_syntax(doi):
        prefix = doi_prefix(doi)
        mentioned = {k for k in _VENUE_PUBLISHER_PREFIXES if re.search(rf"\b{k}\b", venue)}
        if len(mentioned) == 1:
            (kw,) = mentioned
            if prefix not in _VENUE_PUBLISHER_PREFIXES[kw] and prefix != "10.48550":
                owner = DOI_PREFIX_PUBLISHER.get(prefix, f"registrant {prefix}")
                add(
                    "DOI_PUBLISHER_MISMATCH",
                    f"Venue mentions {kw.upper()} but the DOI prefix {prefix} belongs to {owner}",
                    0.35,
                )
        if _NATURE_VENUE.match(ref.container_title or "") and prefix != "10.1038":
            owner = DOI_PREFIX_PUBLISHER.get(prefix, f"registrant {prefix}")
            add(
                "DOI_PUBLISHER_MISMATCH",
                f"Nature-family venue but the DOI prefix {prefix} belongs to {owner}",
                0.35,
            )

    if ref.ids.arxiv_id and ref.year:
        ay = arxiv_id_year(ref.ids.arxiv_id)
        if ay and ref.year < ay:
            add(
                "ARXIV_DATE",
                f"arXiv ID {ref.ids.arxiv_id} was assigned in {ay}, after the cited year {ref.year}",
                0.4,
            )

    if ref.year:
        if ref.year > now.year:
            add("FUTURE_YEAR", f"Publication year {ref.year} is in the future", 0.5)
        elif ref.year < 1600:
            add("ANCIENT_YEAR", f"Publication year {ref.year} is implausible", 0.3)
        canonical = canonical_venue(ref.container_title)
        founded = {"iclr": 2013, "neurips": 1987, "icml": 1980, "tmlr": 2022, "naacl": 2000,
                   "emnlp": 1996, "tacl": 2013, "jmlr": 2000, "cvpr": 1983, "aaai": 1980}  # fmt: skip
        if canonical and canonical in founded and ref.year < founded[canonical]:
            add(
                "VENUE_ANACHRONISM",
                f"{ref.container_title} did not exist in {ref.year} (first held {founded[canonical]})",
                0.45,
            )

    if ref.pages:
        m = re.match(r"^\s*(\d+)\s*[-–—]+\s*(\d+)\s*$", ref.pages)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if end < start and len(m.group(2)) >= len(m.group(1)):
                add("PAGES_REVERSED", f"Page range {ref.pages} ends before it starts", 0.3)
            elif end - start > 300:
                add(
                    "PAGES_LONG", f"Page range {ref.pages} is implausibly long for an article", 0.15
                )

    if (
        ref.type == CitationType.ARTICLE_JOURNAL
        and ref.year
        and ref.year >= 2005
        and not ref.ids.doi
        and ref.parse_method == "bibtex"
    ):
        add("NO_DOI", "Recent journal article without a DOI", 0.05)

    if ref.parse_method == "bibtex" and any("et al" in a.family.lower() for a in ref.authors):
        add("ET_AL_IN_AUTHORS", "'et al.' inside a structured author list", 0.1)

    if not ref.title:
        add("NO_TITLE", "No title could be identified", 0.1)

    score = 1.0
    for s in signals:
        score *= 1.0 - s.weight
    return round(1.0 - score, 3), signals
