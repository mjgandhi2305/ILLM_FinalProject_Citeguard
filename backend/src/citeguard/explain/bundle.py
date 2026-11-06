"""Evidence bundle (the only facts the LLM may use) and the validator for its explanations."""

from __future__ import annotations

import json
import re
from typing import Any

from citeguard.domain.models import CitationResult, Record, Verdict
from citeguard.match.normalize import fold

_CALLS_FAKE_RE = re.compile(r"fabricat|\bfake\b|hallucinat|does not exist|non-?existent", re.I)


def _record(r: Record) -> dict[str, Any]:
    names = [a.display() for a in r.authors[:4]] + (["et al."] if len(r.authors) > 4 else [])
    return {
        "title": r.title,
        "authors": names,
        "year": r.year,
        "venue": r.container_title,
        "doi": r.doi,
        "url": r.url,
        "retracted": r.is_retracted or None,
    }


def build_bundle(result: CitationResult) -> dict[str, Any]:
    ref = result.reference
    citation = {
        "as_written": ref.raw[:700],
        "title": ref.title,
        "authors": [a.display() for a in ref.authors[:8]]
        + (["et al."] if ref.authors_truncated else []),
        "year": ref.year,
        "venue": ref.container_title,
        "volume": ref.volume,
        "pages": ref.pages,
        "doi": ref.ids.doi,
        "arxiv_id": ref.ids.arxiv_id,
    }
    evidence = []
    for e in result.evidence:
        evidence.append(
            {
                "id": e.id,
                "source": e.source,
                "operation": e.operation,
                "query": e.query[:200],
                "status": e.status.value,
                "note": e.note,
                "top_records": [_record(r) for r in e.records[:2]],
            }
        )
    return {
        "citation": {k: v for k, v in citation.items() if v not in (None, [], "")},
        "verdict": result.verdict.value,
        "confidence": round(result.confidence, 2),
        "flags": [f.value for f in result.flags],
        "matched_record": (
            {**_record(result.best_match.record), "evidence_id": result.best_match.evidence_id}
            if result.best_match
            else None
        ),
        "discrepancies": [
            {
                "code": d.code.value,
                "severity": d.severity.value,
                "field": d.field,
                "claimed": d.claimed,
                "actual": d.actual,
                "message": d.message,
                "evidence_ids": d.evidence_ids,
            }
            for d in result.discrepancies
        ],
        "evidence": evidence,
        "signals": [{"id": f"sig:{s.code}", "message": s.message} for s in result.risk_signals],
    }


def bundle_ids(bundle: dict[str, Any]) -> set[str]:
    return {e["id"] for e in bundle["evidence"]} | {s["id"] for s in bundle["signals"]}


_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{4,})[\"“”]")
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'“”,;)]+")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def validate_explanation(
    texts: list[str], cited_ids: list[list[str]], bundle: dict[str, Any]
) -> list[str]:
    """Return a list of violations (empty = grounded)."""
    problems: list[str] = []
    allowed = bundle_ids(bundle)
    haystack = fold(json.dumps(bundle, ensure_ascii=False))
    raw_haystack = json.dumps(bundle, ensure_ascii=False).lower()
    for ids in cited_ids:
        if not ids:
            problems.append("a reason cites no evidence id")
        for i in ids:
            if i not in allowed:
                problems.append(f"unknown evidence id {i!r}")
    for text in texts:
        for quoted in _QUOTE_RE.findall(text):
            if fold(quoted) and fold(quoted) not in haystack:
                problems.append(f"quoted text not in evidence: {quoted!r}")
        for doi in _DOI_RE.findall(text):
            if doi.lower().rstrip(".") not in raw_haystack:
                problems.append(f"DOI not in evidence: {doi}")
        for year in _YEAR_RE.findall(text):
            if year not in raw_haystack:
                problems.append(f"year not in evidence: {year}")
    return problems


def verdict_contradictions(headline: str, verdict: Verdict) -> list[str]:
    """The headline is read first: it must not call a real or undecided citation fake."""
    if verdict in (Verdict.FABRICATED, Verdict.MISATTRIBUTED):
        return []
    if _CALLS_FAKE_RE.search(headline):
        return [f"the headline calls the citation fake, but the verdict is {verdict.value}"]
    return []
