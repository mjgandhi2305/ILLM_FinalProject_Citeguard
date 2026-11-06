"""Deterministic explanations: always available, used in pass 1 and as the LLM fallback."""

from __future__ import annotations

from citeguard.domain.models import (
    CitationResult,
    Discrepancy,
    DiscrepancyCode,
    Explanation,
    Flag,
    LookupStatus,
    Reason,
    Severity,
    Verdict,
)

SOURCE_NAMES = {
    "doi": "doi.org",
    "crossref": "Crossref",
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
    "arxiv": "arXiv",
    "dblp": "DBLP",
    "pubmed": "PubMed",
}

_FIELD_LABEL = {
    "title": "title",
    "authors": "authors",
    "year": "year",
    "venue": "venue",
    "pages": "pages",
    "volume": "volume",
    "doi": "DOI",
    "arxiv_id": "arXiv ID",
}


CLAIM_NOT_SUPPORTED_ADVICE = (
    "Its abstract does not support the sentence citing it (see the claim check): make sure the "
    "paper says what you cite it for, or cite a source that does."
)


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _searched(result: CitationResult) -> tuple[list[str], list[str]]:
    names = sorted(
        {
            SOURCE_NAMES.get(e.source, e.source)
            for e in result.evidence
            if e.operation in ("search", "lookup")
            and e.status in (LookupStatus.FOUND, LookupStatus.NOT_FOUND)
        }
    )
    ev_ids = [e.id for e in result.evidence if e.operation == "search"]
    return names, ev_ids


def _reason(d: Discrepancy) -> Reason:
    return Reason(text=d.message, evidence_ids=d.evidence_ids)


def template_explanation(result: CitationResult) -> Explanation:
    v = result.verdict
    best = result.best_match.record if result.best_match else None
    serious = [d for d in result.discrepancies if d.severity != Severity.INFO]
    notes = [d for d in result.discrepancies if d.severity == Severity.INFO]
    searched, search_ev = _searched(result)
    reasons: list[Reason] = []

    if v == Verdict.VERIFIED and best:
        found_in = sorted(
            {SOURCE_NAMES.get(e.source, e.source) for e in result.evidence if e.records}
        )
        venue = f" in {best.container_title}" if best.container_title else ""
        year_unconfirmed = any(d.code == DiscrepancyCode.YEAR_MISMATCH for d in notes)
        if year_unconfirmed:
            headline = f'Verified: "{best.title}" exists; the cited year could not be confirmed.'
            matched_fields = "title and authors"
        else:
            headline = f'Verified: matches "{best.title}" ({best.year}){venue}.'
            matched_fields = "title, authors and year"
        reasons.append(
            Reason(
                text=f"The citation's {matched_fields} match the record in {_join(found_in)}.",
                evidence_ids=[result.best_match.evidence_id] if result.best_match else [],
            )
        )
        reasons += [_reason(d) for d in notes]
        recommendation = (
            "Double-check the publication year against the publisher's page."
            if year_unconfirmed
            else "No action needed."
        )
    elif v == Verdict.VERIFIED_WITH_ERRORS and best:
        fields = sorted({_FIELD_LABEL.get(d.field or "", d.field or "") for d in serious})
        headline = (
            f"Real paper, but the citation has {len(serious)} error"
            f"{'s' if len(serious) != 1 else ''} ({_join([f for f in fields if f])})."
        )
        reasons += [_reason(d) for d in serious + notes]
        recommendation = "Use the corrected citation below."
    elif v == Verdict.MISATTRIBUTED:
        lead = next(
            (d for d in serious if d.severity == Severity.CRITICAL),
            next((d for d in serious if d.code == DiscrepancyCode.AUTHORS_FABRICATED), None),
        )
        title = f'"{best.title}"' if best else "the cited work"
        detail = (
            (lead.message[0].lower() + lead.message[1:]).rstrip(".")
            if lead
            else ("key details are wrong")
        )
        headline = f"Misattributed: {title} exists, but {detail}."
        reasons += [_reason(d) for d in serious + notes]
        recommendation = (
            "Check which work you meant to cite. If it is the paper found, use the corrected "
            "citation; otherwise replace or remove the reference."
        )
    elif v == Verdict.FABRICATED:
        headline = (
            f"Likely fabricated: no matching publication in {len(searched)} scholarly "
            f"database{'s' if len(searched) != 1 else ''}."
        )
        id_reasons = [
            _reason(d)
            for d in serious
            if d.code
            in (
                DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK,
                DiscrepancyCode.ID_NOT_REGISTERED,
                DiscrepancyCode.ID_INVALID_SYNTAX,
            )
        ]
        reasons += id_reasons
        not_found = next((d for d in serious if d.code == DiscrepancyCode.TITLE_NOT_FOUND), None)
        if searched:
            text = f"Searched {_join(searched)}: no record matches this title and author list"
            if not_found and not_found.actual:
                text += (
                    f'. The closest title found was "{not_found.actual}", which is a different work'
                )
            reasons.append(Reason(text=text + ".", evidence_ids=search_ev[:6]))
        for s in result.risk_signals:
            reasons.append(Reason(text=s.message + "."))
        recommendation = (
            "Do not cite this reference. Use one of the suggested real papers, or find the "
            "source that actually supports your claim."
        )
    else:  # UNVERIFIABLE
        failed = Flag.SOURCES_DEGRADED in result.flags
        possible = result.candidates[0] if result.candidates else None
        if not result.reference.title:
            headline = "Could not verify: no title could be identified in this reference."
        elif failed:
            headline = "Could not verify: too few scholarly databases responded."
        elif possible and possible.probability >= 0.5:
            headline = (
                f'Could not verify: possibly "{possible.record.title}" '
                f"({possible.record.year}), but the match is uncertain."
            )
        else:
            headline = (
                "Could not verify: this type of work (book, thesis, report, web page) is "
                "poorly covered by scholarly databases."
            )
        if searched:
            reasons.append(
                Reason(
                    text=f"Searched {_join(searched)} without a confident match.",
                    evidence_ids=search_ev[:6],
                )
            )
        reasons += [_reason(d) for d in serious if d.code != DiscrepancyCode.TITLE_NOT_FOUND]
        recommendation = "Check this reference manually (library catalogue, publisher site)."

    if Flag.RETRACTED in result.flags and v != Verdict.FABRICATED:
        recommendation = "This paper is retracted: do not rely on it. " + recommendation
    if Flag.CLAIM_NOT_SUPPORTED in result.flags:
        recommendation = CLAIM_NOT_SUPPORTED_ADVICE + (
            "" if recommendation == "No action needed." else " " + recommendation
        )
    if Flag.PREPRINT_HAS_PUBLISHED_VERSION in result.flags:
        reasons.append(
            Reason(text="A peer-reviewed version of this preprint exists; prefer citing it.")
        )
    return Explanation(
        headline=headline, reasons=reasons, recommendation=recommendation, mode="template"
    )
