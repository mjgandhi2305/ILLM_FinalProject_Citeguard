"""Opt-in claim-support check (design §4.9): does the cited paper's abstract support the
sentence that cites it? Only the abstract is read, so the result is a hint, not a verdict."""

from __future__ import annotations

import html
import re
from typing import Protocol

from citeguard.domain.models import (
    CitationResult,
    ClaimCheck,
    ClaimSupport,
    LLMUsage,
    Record,
    Verdict,
)
from citeguard.match.normalize import normalize_title
from citeguard.parse.identifiers import normalize_doi
from citeguard.sources.registry import SourceSet

MAX_CLAIMS = 3  # citing sentences checked per reference
CHECKABLE = (Verdict.VERIFIED, Verdict.VERIFIED_WITH_ERRORS)  # the cited work is known

_TAG_RE = re.compile(r"<[^>]+>")  # Crossref abstracts are JATS XML
_WS_RE = re.compile(r"\s+")
_LEAD_RE = re.compile(r"^(?:abstract|summary)\s*[:.\-–]?\s*", re.IGNORECASE)


class ClaimChecker(Protocol):
    async def check(
        self, record: Record, abstract: str, claims: list[str]
    ) -> tuple[list[ClaimCheck] | None, LLMUsage]: ...


def clean_abstract(text: str | None) -> str | None:
    """Plain text, or None when there is too little to judge a claim against."""
    if not text:
        return None
    plain = _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(text))).strip()
    plain = _LEAD_RE.sub("", plain)
    return plain[:4000] if len(plain.split()) >= 30 else None


def claims_for(result: CitationResult) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sentence in result.reference.contexts:
        s = _WS_RE.sub(" ", sentence).strip()[:600]
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:MAX_CLAIMS]


async def find_abstract(sources: SourceSet, result: CitationResult) -> tuple[str, Record] | None:
    """The cited work's abstract: from records already retrieved, else by DOI lookup."""
    if result.best_match is None:
        return None
    best = result.best_match.record
    doi = normalize_doi(best.doi)
    title = normalize_title(best.title)
    retrieved = [best] + [
        r
        for e in result.evidence
        for r in e.records
        if (doi and normalize_doi(r.doi) == doi) or normalize_title(r.title) == title
    ]
    for rec in retrieved:
        if abstract := clean_abstract(rec.abstract):
            return abstract, rec
    if doi:
        for name in ("openalex", "semantic_scholar"):
            src = sources.get(name)
            if src is None:
                continue
            resp = await src.lookup("doi", doi)
            for rec in resp.records:
                if abstract := clean_abstract(rec.abstract):
                    return abstract, rec
    return None


def undetermined(claims: list[str], why: str) -> list[ClaimCheck]:
    return [
        ClaimCheck(claim=c, label=ClaimSupport.CANNOT_DETERMINE, rationale=why, mode="none")
        for c in claims
    ]


async def check_claims(
    sources: SourceSet, result: CitationResult, checker: ClaimChecker
) -> tuple[list[ClaimCheck], LLMUsage]:
    claims = claims_for(result)
    if not claims or result.verdict not in CHECKABLE or result.best_match is None:
        return [], LLMUsage()
    found = await find_abstract(sources, result)
    if found is None:
        return undetermined(
            claims,
            "No abstract of this paper is available in OpenAlex or Semantic Scholar, so the "
            "claim could not be checked.",
        ), LLMUsage()
    abstract, rec = found
    checks, usage = await checker.check(result.best_match.record, abstract, claims)
    if checks is None:
        return undetermined(
            claims, "The claim check could not be completed; try again later."
        ), usage
    url = rec.url or (f"https://doi.org/{rec.doi}" if rec.doi else None)
    for c in checks:
        c.abstract_source = rec.source
        c.abstract_url = url
    return checks, usage
