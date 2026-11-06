"""Deterministic decision rules: matched record(s) + evidence → verdict, discrepancies, flags,
confidence. No LLM output can reach `VERIFIED` without passing through these rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from citeguard.domain.models import (
    ARTICLE_LIKE,
    Candidate,
    CitationType,
    Discrepancy,
    DiscrepancyCode,
    Flag,
    ParsedReference,
    Severity,
    Verdict,
)
from citeguard.match.linkage import MATCH_THRESHOLD, STRONG_TITLE
from citeguard.match.names import compare_authors, format_authors_short
from citeguard.match.normalize import main_title, normalize_title, title_similarity, word_count
from citeguard.match.venues import is_preprint_venue, venue_similarity
from citeguard.parse.identifiers import normalize_doi

IdStatus = Literal["absent", "invalid", "registered", "unregistered", "unknown"]


@dataclass
class IdFindings:
    doi_status: IdStatus = "absent"
    doi_evidence: str | None = None
    doi_candidate: Candidate | None = None  # record the claimed DOI resolves to
    doi_points_elsewhere: bool = False
    arxiv_status: IdStatus = "absent"
    arxiv_evidence: str | None = None
    arxiv_candidate: Candidate | None = None
    arxiv_points_elsewhere: bool = False


@dataclass
class Decision:
    verdict: Verdict
    confidence: float
    discrepancies: list[Discrepancy] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    best: Candidate | None = None
    group: list[Candidate] = field(default_factory=list)
    closest: Candidate | None = None


def same_work_group(matched: Candidate, candidates: list[Candidate]) -> list[Candidate]:
    group = []
    mdoi = normalize_doi(matched.record.doi)
    for c in candidates:
        if c is matched:
            group.append(c)
            continue
        cdoi = normalize_doi(c.record.doi)
        same_doi = bool(mdoi and cdoi and mdoi == cdoi)
        same_title = title_similarity(c.record.title, matched.record.title) >= 0.95
        authors = compare_authors(matched.record.authors, c.record.authors)
        compatible_authors = authors.f1 is None or authors.f1 >= 0.5
        if same_doi or (same_title and compatible_authors and c.probability >= 0.5):
            group.append(c)
    return group


def ev(c: Candidate) -> list[str]:
    return [c.evidence_id]


def _field_checks(
    ref: ParsedReference, matched: Candidate, group: list[Candidate], ids: IdFindings
) -> tuple[list[Discrepancy], list[Flag]]:
    out: list[Discrepancy] = []
    flags: list[Flag] = []
    recs = [c.record for c in group]
    group_ev = sorted({c.evidence_id for c in group})

    # --- title -------------------------------------------------------------------------
    if ref.title:
        best_title = max(group, key=lambda c: title_similarity(ref.title, c.record.title))
        sim = title_similarity(ref.title, best_title.record.title)
        if normalize_title(ref.title) != normalize_title(best_title.record.title):
            subtitle_only = normalize_title(main_title(ref.title)) == normalize_title(
                main_title(best_title.record.title or "")
            )
            sev = (
                Severity.INFO
                if subtitle_only or sim >= STRONG_TITLE
                else Severity.MINOR
                if sim >= 0.85
                else Severity.MAJOR
            )
            code = (
                DiscrepancyCode.TITLE_MISMATCH_MAJOR
                if sev == Severity.MAJOR
                else DiscrepancyCode.TITLE_MISMATCH_MINOR
            )
            out.append(
                Discrepancy(
                    code=code,
                    severity=sev,
                    field="title",
                    claimed=ref.title,
                    actual=best_title.record.title,
                    message=f"Title differs from the published title (similarity {sim:.2f})",
                    evidence_ids=ev(best_title),
                )
            )

    # --- authors -------------------------------------------------------------------------
    if ref.authors and any(r.authors for r in recs):
        comparisons = [
            (compare_authors(ref.authors, c.record.authors, ref.authors_truncated), c)
            for c in group
            if c.record.authors
        ]
        # Sources disagree (Crossref sometimes lists the publisher as first author), so compare
        # with the record most consistent with the citation. Records whose names cannot be
        # compared (native script vs. transliteration) are used only when nothing else is left.
        cmp, c_best = max(
            comparisons,
            key=lambda t: (
                t[0].f1 is not None,
                t[0].f1 or 0.0,
                t[0].first_author_match is True,
                -len(t[0].actual_unmatched),
            ),
        )
        actual_names = format_authors_short(c_best.record.authors, 4)
        claimed_names = format_authors_short(ref.authors, 4)
        most = max(len(c.record.authors) for _, c in comparisons)
        if cmp.f1 is None:
            # Spelling cannot be compared, but the count can: a citation listing three authors
            # for a one-author paper names at least two people who are not on it.
            if len(ref.authors) > 2 * most:
                out.append(
                    Discrepancy(
                        code=DiscrepancyCode.AUTHORS_FABRICATED,
                        severity=Severity.MAJOR,
                        field="authors",
                        claimed=claimed_names,
                        actual=actual_names,
                        message=(
                            f"The citation lists {len(ref.authors)} authors, but the paper has "
                            f"only {most} ({actual_names})"
                        ),
                        evidence_ids=ev(c_best),
                    )
                )
        elif (cmp.precision or 0.0) < 0.5:  # most listed authors are not on the paper
            out.append(
                Discrepancy(
                    code=DiscrepancyCode.AUTHORS_FABRICATED,
                    severity=Severity.MAJOR,
                    field="authors",
                    claimed=claimed_names,
                    actual=actual_names,
                    message=(
                        f"Only {cmp.matched} of {len(ref.authors)} listed authors appear on "
                        f"the actual paper, which is by {actual_names}"
                    ),
                    evidence_ids=ev(c_best),
                )
            )
        else:
            if cmp.first_author_match is False:
                listed_elsewhere = any(
                    a.family == ref.authors[0].family for a in c_best.record.authors
                )
                code = (
                    DiscrepancyCode.AUTHORS_REORDERED
                    if listed_elsewhere
                    else DiscrepancyCode.FIRST_AUTHOR_MISMATCH
                )
                out.append(
                    Discrepancy(
                        code=code,
                        severity=Severity.MINOR if listed_elsewhere else Severity.MAJOR,
                        field="authors",
                        claimed=ref.authors[0].display(),
                        actual=c_best.record.authors[0].display(),
                        message=(
                            f"First author should be {c_best.record.authors[0].display()}, "
                            f"not {ref.authors[0].display()}"
                        ),
                        evidence_ids=ev(c_best),
                    )
                )
            if cmp.claimed_unmatched:
                names = ", ".join(a.display() for a in cmp.claimed_unmatched[:4])
                out.append(
                    Discrepancy(
                        code=DiscrepancyCode.AUTHORS_EXTRA,
                        severity=Severity.MINOR,
                        field="authors",
                        claimed=names,
                        actual=actual_names,
                        message=f"Listed author(s) not on the paper: {names}",
                        evidence_ids=ev(c_best),
                    )
                )
            if cmp.actual_unmatched and not ref.authors_truncated:
                out.append(
                    Discrepancy(
                        code=DiscrepancyCode.AUTHORS_MISSING,
                        severity=Severity.INFO,
                        field="authors",
                        claimed=claimed_names,
                        actual=actual_names,
                        message=f"{len(cmp.actual_unmatched)} author(s) omitted without 'et al.'",
                        evidence_ids=ev(c_best),
                    )
                )

    # --- year ----------------------------------------------------------------------------
    years = [r.year for r in recs if r.year]
    if ref.year and years:
        delta = min(abs(ref.year - y) for y in years)
        if delta > 0:
            closest_year = min(years, key=lambda y: abs(ref.year - y))  # type: ignore[operator]
            # ±1 is tolerated only when the sources themselves disagree (online-first vs.
            # print dates); when they agree, an off-by-one year is a real citation error.
            sources_disagree = len({y for y in years if abs(y - closest_year) <= 1}) > 1
            if delta == 1:
                sev = Severity.INFO if sources_disagree else Severity.MINOR
            else:
                sev = Severity.MINOR if delta == 2 else Severity.MAJOR
            message = f"Published in {closest_year}, cited as {ref.year}"
            # Famous papers get re-deposited years later (Zenodo copies, junk DOIs). A much later
            # record without a real venue is not evidence that the cited year is wrong.
            later_copies = [r for r in recs if r.year == closest_year]
            if closest_year - ref.year >= 3 and all(
                not r.container_title
                or is_preprint_venue(r.container_title)
                or r.type == CitationType.PREPRINT
                for r in later_copies
            ):
                sev = Severity.INFO
                message = (
                    f"Only a later copy ({closest_year}) of this work was found, so the original "
                    f"{ref.year} publication could not be confirmed"
                )
            out.append(
                Discrepancy(
                    code=DiscrepancyCode.YEAR_MISMATCH,
                    severity=sev,
                    field="year",
                    claimed=str(ref.year),
                    actual=str(closest_year),
                    message=message,
                    evidence_ids=group_ev,
                )
            )
    if ref.year and ref.year > datetime.now(UTC).year:
        out.append(
            Discrepancy(
                code=DiscrepancyCode.FUTURE_DATE,
                severity=Severity.MAJOR,
                field="year",
                claimed=str(ref.year),
                message=f"Cited year {ref.year} is in the future",
            )
        )

    # --- venue ---------------------------------------------------------------------------
    if ref.container_title:
        sims = [
            (s, c)
            for c in group
            if (s := venue_similarity(ref.container_title, c.record.container_title)) is not None
        ]
        if sims:
            sim, c_v = max(sims, key=lambda t: t[0])
            if sim < 0.75:
                out.append(
                    Discrepancy(
                        code=DiscrepancyCode.VENUE_MISMATCH,
                        severity=Severity.MAJOR if sim < 0.5 else Severity.MINOR,
                        field="venue",
                        claimed=ref.container_title,
                        actual=c_v.record.container_title,
                        message=(
                            f"Published in {c_v.record.container_title}, not {ref.container_title}"
                        ),
                        evidence_ids=ev(c_v),
                    )
                )

    # --- volume / pages ------------------------------------------------------------------
    pages_known = [c for c in group if c.features.pages_match is not None]
    if pages_known and not any(c.features.pages_match for c in pages_known):
        c_p = pages_known[0]
        out.append(
            Discrepancy(
                code=DiscrepancyCode.VOLUME_ISSUE_PAGES_MISMATCH,
                severity=Severity.MINOR,
                field="pages",
                claimed=ref.pages,
                actual=c_p.record.pages,
                message=f"Pages are {c_p.record.pages}, cited as {ref.pages}",
                evidence_ids=ev(c_p),
            )
        )
    vol_known = [c for c in group if c.features.volume_match is not None]
    if vol_known and not any(c.features.volume_match for c in vol_known):
        c_vol = vol_known[0]
        out.append(
            Discrepancy(
                code=DiscrepancyCode.VOLUME_ISSUE_PAGES_MISMATCH,
                severity=Severity.MINOR,
                field="volume",
                claimed=ref.volume,
                actual=c_vol.record.volume,
                message=f"Volume is {c_vol.record.volume}, cited as {ref.volume}",
                evidence_ids=ev(c_vol),
            )
        )

    # --- identifiers ---------------------------------------------------------------------
    claimed_doi = normalize_doi(ref.ids.doi)
    group_dois = {d for r in recs if (d := normalize_doi(r.doi))}
    if claimed_doi and claimed_doi not in group_dois:
        actual = ", ".join(sorted(group_dois)) or None
        if ids.doi_points_elsewhere and ids.doi_candidate:
            other = ids.doi_candidate.record
            out.append(
                Discrepancy(
                    code=DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK,
                    severity=Severity.CRITICAL,
                    field="doi",
                    claimed=claimed_doi,
                    actual=actual,
                    message=(
                        f'DOI {claimed_doi} belongs to a different work: "{other.title}" '
                        f"by {format_authors_short(other.authors)} ({other.year})"
                    ),
                    evidence_ids=[
                        e for e in (ids.doi_evidence, ids.doi_candidate.evidence_id) if e
                    ],
                )
            )
        elif ids.doi_status == "unregistered":
            out.append(
                Discrepancy(
                    code=DiscrepancyCode.ID_NOT_REGISTERED,
                    severity=Severity.MAJOR,
                    field="doi",
                    claimed=claimed_doi,
                    actual=actual,
                    message=f"DOI {claimed_doi} does not exist"
                    + (f"; the paper's DOI is {actual}" if actual else ""),
                    evidence_ids=[ids.doi_evidence] if ids.doi_evidence else [],
                )
            )
        elif ids.doi_status == "invalid":
            out.append(
                Discrepancy(
                    code=DiscrepancyCode.ID_INVALID_SYNTAX,
                    severity=Severity.MAJOR,
                    field="doi",
                    claimed=ref.ids.doi,
                    actual=actual,
                    message=f"'{ref.ids.doi}' is not a valid DOI",
                )
            )
        elif group_dois and not ids.doi_candidate:
            out.append(
                Discrepancy(
                    code=DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK,
                    severity=Severity.MINOR,
                    field="doi",
                    claimed=claimed_doi,
                    actual=actual,
                    message=f"Cited DOI {claimed_doi} differs from the paper's DOI {actual}",
                    evidence_ids=[e for e in (ids.doi_evidence,) if e],
                )
            )
    if ids.arxiv_status == "unregistered":
        out.append(
            Discrepancy(
                code=DiscrepancyCode.ID_NOT_REGISTERED,
                severity=Severity.MAJOR,
                field="arxiv_id",
                claimed=ref.ids.arxiv_id,
                message=f"arXiv:{ref.ids.arxiv_id} does not exist",
                evidence_ids=[ids.arxiv_evidence] if ids.arxiv_evidence else [],
            )
        )
    elif ids.arxiv_points_elsewhere and ids.arxiv_candidate:
        other = ids.arxiv_candidate.record
        out.append(
            Discrepancy(
                code=DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK,
                severity=Severity.CRITICAL,
                field="arxiv_id",
                claimed=ref.ids.arxiv_id,
                actual=other.arxiv_id,
                message=f'arXiv:{ref.ids.arxiv_id} is a different paper: "{other.title}"',
                evidence_ids=[ids.arxiv_candidate.evidence_id],
            )
        )

    # --- flags ---------------------------------------------------------------------------
    retracted = [c for c in group if c.record.is_retracted]
    if retracted:
        flags.append(Flag.RETRACTED)
        out.append(
            Discrepancy(
                code=DiscrepancyCode.RETRACTED,
                severity=Severity.INFO,
                message="This paper has been retracted and should not be cited as evidence",
                evidence_ids=[c.evidence_id for c in retracted],
            )
        )
    claimed_preprint = ref.type == CitationType.PREPRINT or is_preprint_venue(ref.container_title)
    if claimed_preprint and any(
        r.type in (CitationType.ARTICLE_JOURNAL, CitationType.PAPER_CONFERENCE)
        and r.container_title
        and not is_preprint_venue(r.container_title)
        for r in recs
    ):
        flags.append(Flag.PREPRINT_HAS_PUBLISHED_VERSION)
    return out, flags


def _matched_verdict(discrepancies: list[Discrepancy]) -> Verdict:
    codes = {d.code for d in discrepancies if d.severity != Severity.INFO}
    if DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK in codes and any(
        d.severity == Severity.CRITICAL for d in discrepancies
    ):
        return Verdict.MISATTRIBUTED
    if DiscrepancyCode.AUTHORS_FABRICATED in codes:
        return Verdict.MISATTRIBUTED
    if any(d.severity in (Severity.MINOR, Severity.MAJOR) for d in discrepancies):
        return Verdict.VERIFIED_WITH_ERRORS
    return Verdict.VERIFIED


def choose_match(
    ref: ParsedReference,
    candidates: list[Candidate],
    ids: IdFindings,
    adjudicated: Candidate | None,
    llm_used: bool,
) -> tuple[Candidate | None, bool]:
    """Returns (matched candidate, needs_disclaimer_that_match_is_uncertain)."""
    if ids.doi_candidate and not ids.doi_points_elsewhere:
        return ids.doi_candidate, False
    if ids.arxiv_candidate and not ids.arxiv_points_elsewhere:
        return ids.arxiv_candidate, False
    if not candidates:
        return None, False
    pool = [c for c in candidates if c not in (ids.doi_candidate, ids.arxiv_candidate)]
    if not pool:
        return None, False
    best = max(pool, key=lambda c: c.probability)
    if best.probability >= MATCH_THRESHOLD:
        return best, False
    strong = [c for c in pool if c.features.title_sim >= STRONG_TITLE]
    if strong:
        return max(strong, key=lambda c: c.probability), False
    if adjudicated is not None:
        return adjudicated, True
    if not llm_used and best.probability >= 0.75:
        return best, True
    return None, False


def fabricated_confidence(
    ref: ParsedReference, ids: IdFindings, unhealthy: int, reformulated: bool, risk: float
) -> float:
    prior = {
        CitationType.ARTICLE_JOURNAL: 0.9,
        CitationType.PAPER_CONFERENCE: 0.85,
        CitationType.PREPRINT: 0.85,
    }.get(ref.type, 0.75)
    if ids.doi_points_elsewhere or ids.doi_status == "unregistered":
        prior += 0.07
    if ids.arxiv_status == "unregistered" or ids.arxiv_points_elsewhere:
        prior += 0.05
    if reformulated:
        prior += 0.03
    prior += 0.05 * risk
    prior -= 0.1 * unhealthy
    return round(max(0.5, min(0.99, prior)), 3)


def decide(
    ref: ParsedReference,
    candidates: list[Candidate],
    ids: IdFindings,
    *,
    adjudicated: Candidate | None = None,
    adjudication_rejected_all: bool = False,
    llm_used: bool = False,
    reformulated: bool = False,
    general_responded: int = 0,
    unhealthy_general: int = 0,
    risk: float = 0.0,
    chimera: Candidate | None = None,
) -> Decision:
    matched, uncertain = choose_match(ref, candidates, ids, adjudicated, llm_used)
    # Records an identifier merely *points to* are evidence against the citation, never
    # "closest matches" for it.
    unrelated = {
        id(c)
        for c, elsewhere in (
            (ids.doi_candidate, ids.doi_points_elsewhere),
            (ids.arxiv_candidate, ids.arxiv_points_elsewhere),
        )
        if c is not None and elsewhere
    }
    pool = [c for c in candidates if id(c) not in unrelated]
    closest = max(pool, key=lambda c: c.probability) if pool else None

    if matched is not None:
        group = same_work_group(matched, candidates)
        discrepancies, flags = _field_checks(ref, matched, group, ids)
        verdict = _matched_verdict(discrepancies)
        if verdict == Verdict.MISATTRIBUTED and chimera is not None:
            discrepancies.append(
                Discrepancy(
                    code=DiscrepancyCode.CHIMERIC_TITLE_AUTHORS,
                    severity=Severity.MAJOR,
                    field="authors",
                    claimed=format_authors_short(ref.authors),
                    actual=chimera.record.title,
                    message=(
                        f"The listed authors wrote a different paper, "
                        f'"{chimera.record.title}" ({chimera.record.year}); the citation '
                        "appears to merge two works"
                    ),
                    evidence_ids=[chimera.evidence_id],
                )
            )
        if uncertain and adjudicated is not None:
            flags.append(Flag.LLM_ADJUDICATED)
        confidence = matched.probability
        if ids.doi_candidate is matched and not ids.doi_points_elsewhere:
            confidence = max(confidence, 0.97)
        if uncertain:
            confidence = min(confidence, 0.8)
        if any(d.message.startswith("Only a later copy") for d in discrepancies):
            confidence = min(confidence, 0.75)
        if unhealthy_general:
            confidence *= 0.95
            flags.append(Flag.SOURCES_DEGRADED)
        return Decision(
            verdict=verdict,
            confidence=round(max(0.5, min(0.995, confidence)), 3),
            discrepancies=discrepancies,
            flags=flags,
            best=matched,
            group=group,
            closest=closest,
        )

    # ---- no match ---------------------------------------------------------------------
    discrepancies: list[Discrepancy] = []  # type: ignore[no-redef]
    flags: list[Flag] = []  # type: ignore[no-redef]
    if ids.doi_points_elsewhere and ids.doi_candidate:
        other = ids.doi_candidate.record
        discrepancies.append(
            Discrepancy(
                code=DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK,
                severity=Severity.CRITICAL,
                field="doi",
                claimed=ids.doi_candidate.record.doi,
                actual=other.title,
                message=(
                    f'The DOI is real but belongs to "{other.title}" by '
                    f"{format_authors_short(other.authors)} ({other.year})"
                ),
                evidence_ids=[e for e in (ids.doi_evidence, ids.doi_candidate.evidence_id) if e],
            )
        )
    elif ids.doi_status == "unregistered":
        discrepancies.append(
            Discrepancy(
                code=DiscrepancyCode.ID_NOT_REGISTERED,
                severity=Severity.MAJOR,
                field="doi",
                claimed=ref.ids.doi,
                message=f"DOI {ref.ids.doi} is not registered with any DOI agency",
                evidence_ids=[ids.doi_evidence] if ids.doi_evidence else [],
            )
        )
    elif ids.doi_status == "invalid":
        discrepancies.append(
            Discrepancy(
                code=DiscrepancyCode.ID_INVALID_SYNTAX,
                severity=Severity.MAJOR,
                field="doi",
                claimed=ref.ids.doi,
                message=f"'{ref.ids.doi}' is not a syntactically valid DOI",
            )
        )
    if ids.arxiv_status == "unregistered":
        discrepancies.append(
            Discrepancy(
                code=DiscrepancyCode.ID_NOT_REGISTERED,
                severity=Severity.MAJOR,
                field="arxiv_id",
                claimed=ref.ids.arxiv_id,
                message=f"arXiv:{ref.ids.arxiv_id} does not exist",
                evidence_ids=[ids.arxiv_evidence] if ids.arxiv_evidence else [],
            )
        )
    elif ids.arxiv_points_elsewhere and ids.arxiv_candidate:
        discrepancies.append(
            Discrepancy(
                code=DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK,
                severity=Severity.CRITICAL,
                field="arxiv_id",
                claimed=ref.ids.arxiv_id,
                actual=ids.arxiv_candidate.record.title,
                message=(
                    f"arXiv:{ref.ids.arxiv_id} is a different paper: "
                    f'"{ids.arxiv_candidate.record.title}"'
                ),
                evidence_ids=[ids.arxiv_candidate.evidence_id],
            )
        )
    if ref.title:
        closest_note = ""
        if closest is not None and closest.record.title:
            closest_note = (
                f'; the closest record is "{closest.record.title}" '
                f"(title similarity {closest.features.title_sim:.2f})"
            )
        discrepancies.append(
            Discrepancy(
                code=DiscrepancyCode.TITLE_NOT_FOUND,
                severity=Severity.MAJOR,
                field="title",
                claimed=ref.title,
                actual=closest.record.title if closest else None,
                message="No publication with this title was found" + closest_note,
                evidence_ids=[closest.evidence_id] if closest else [],
            )
        )

    enough_metadata = word_count(ref.title) >= 3
    article_like = ref.type in ARTICLE_LIKE or (
        ref.type == CitationType.UNKNOWN and bool(ref.container_title)
    )
    id_says_fake = (
        ids.doi_points_elsewhere
        or ids.doi_status in ("unregistered", "invalid")
        or ids.arxiv_status == "unregistered"
        or ids.arxiv_points_elsewhere
    )
    ambiguous_left = bool(closest and closest.probability >= 0.5 and not adjudication_rejected_all)
    if unhealthy_general:
        flags.append(Flag.SOURCES_DEGRADED)

    if id_says_fake and enough_metadata and not ambiguous_left:
        verdict = Verdict.FABRICATED
    elif not enough_metadata or general_responded < 2 or ambiguous_left:
        verdict = Verdict.UNVERIFIABLE
    elif article_like:
        verdict = Verdict.FABRICATED
    else:
        verdict = Verdict.UNVERIFIABLE

    if verdict == Verdict.FABRICATED:
        confidence = fabricated_confidence(ref, ids, unhealthy_general, reformulated, risk)
    else:
        confidence = 0.5
    return Decision(
        verdict=verdict,
        confidence=confidence,
        discrepancies=discrepancies,
        flags=flags,
        best=None,
        group=[],
        closest=closest,
    )
