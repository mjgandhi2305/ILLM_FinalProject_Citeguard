"""Real alternatives for fabricated citations: topical retrieval + (optional) LLM rerank."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Sequence
from typing import Protocol

from citeguard.domain.models import (
    CitationResult,
    LLMUsage,
    ParsedReference,
    Record,
    Suggestion,
)
from citeguard.match.linkage import STRONG_TITLE
from citeguard.match.normalize import fold, normalize_title, title_similarity
from citeguard.parse.identifiers import normalize_doi
from citeguard.sources.base import SearchQuery
from citeguard.sources.registry import SourceSet
from citeguard.sources.semantic_scholar import SemanticScholar
from citeguard.suggest.format import format_record

_STOP = set(
    [
        "a",
        "an",
        "the",
        "of",
        "for",
        "and",
        "in",
        "on",
        "to",
        "with",
        "via",
        "by",
        "is",
        "are",
        "from",
        "using",
        "based",
        "towards",
        "toward",
        "study",
        "analysis",
        "approach",
        "new",
        "novel",
        "method",
        "methods",
    ]
)


class Reranker(Protocol):
    """Returns the chosen candidates with a relevance note; an empty list means none fit, and
    None means the reranker could not answer."""

    async def rerank(
        self, ref: ParsedReference, candidates: list[Record], k: int
    ) -> tuple[list[tuple[Record, str]] | None, LLMUsage]: ...


_MARKER_RE = re.compile(r"\[[\d,\s–-]+\]|\([^()]*\b(?:1[6-9]|20)\d{2}[a-z]?\)")


def claim_reference(ref: ParsedReference, claim: str) -> ParsedReference:
    """A stand-in reference for searching by the claim instead of the cited title."""
    text = _MARKER_RE.sub(" ", claim)
    return ref.model_copy(update={"title": text, "contexts": [claim]})


def topic_query(ref: ParsedReference) -> str:
    words = [w for w in fold(ref.title or "").split() if w not in _STOP and len(w) > 2]
    return " ".join(words[:12])


def _keyword_score(ref: ParsedReference, rec: Record) -> float:
    q = set(topic_query(ref).split())
    ctx = set(fold(" ".join(ref.contexts)).split()) - _STOP
    t = set(fold(rec.title or "").split())
    a = set(fold(rec.abstract or "").split())
    title_hits = len(q & t)
    if title_hits < 2 and len(q & a) < 3:
        return -1.0  # too weakly related to suggest at all
    overlap = title_hits * 2 + len(q & a) * 0.5 + len(ctx & (t | a)) * 0.3
    popularity = 2.0 * min(1.0, math.log10((rec.cited_by or 0) + 1) / 3)
    return overlap + popularity


async def retrieve_candidates(
    sources: SourceSet, ref: ParsedReference, limit: int = 15, exclude: Record | None = None
) -> list[Record]:
    query = topic_query(ref)
    if not query:
        return []
    jobs = []
    s2 = sources.get("semantic_scholar")
    if isinstance(s2, SemanticScholar):
        jobs.append(s2.relevance_search(query, limit=10))
    if oa := sources.get("openalex"):
        jobs.append(oa.search(SearchQuery(text=query), limit=10))
    responses = await asyncio.gather(*jobs)
    seen: set[str] = set()
    if exclude is not None:  # the cited paper is not an alternative to itself
        seen.add(normalize_doi(exclude.doi) or normalize_title(exclude.title))
        seen.add(normalize_title(exclude.title))
    out: list[Record] = []
    for resp in responses:
        for rec in resp.records:
            if not rec.title or rec.is_retracted or not rec.authors or not rec.year:
                continue
            if title_similarity(ref.title, rec.title) >= STRONG_TITLE:
                continue  # the fabricated title itself cannot be its own alternative
            key = normalize_doi(rec.doi) or normalize_title(rec.title)
            if key in seen or normalize_title(rec.title) in seen:  # also other versions
                continue
            seen.update((key, normalize_title(rec.title)))
            out.append(rec)
    return out[:limit]


async def alternatives(
    sources: SourceSet,
    result: CitationResult,
    styles: Sequence[str],
    reranker: Reranker | None = None,
    k: int = 3,
    claim: str | None = None,
) -> tuple[list[Suggestion], LLMUsage]:
    """Real papers on the same topic. With `claim`, the cited paper is real but does not support
    that sentence, so the search uses the sentence and excludes the cited paper."""
    usage = LLMUsage()
    ref = result.reference
    exclude = None
    if claim is not None:
        ref = claim_reference(ref, claim)
        exclude = result.best_match.record if result.best_match else None
    pool = await retrieve_candidates(sources, ref, exclude=exclude)
    if not pool:
        return [], usage
    if reranker is not None:
        try:
            ranked, usage = await reranker.rerank(ref, pool, k)
            if ranked is not None:  # [] is an answer: no candidate supports the claim
                return [
                    Suggestion(
                        kind="alternative",
                        record=rec,
                        formatted=format_record(rec, styles),
                        relevance_note=note,
                        method="llm",
                    )
                    for rec, note in ranked[:k]
                ], usage
        except Exception:  # LLM trouble falls back to keyword ranking
            usage.failures += 1
    scored = [(s, r) for r in pool if (s := _keyword_score(ref, r)) > 0]
    ranked_kw = [r for _, r in sorted(scored, key=lambda t: -t[0])][:k]
    return [
        Suggestion(
            kind="alternative",
            record=rec,
            formatted=format_record(rec, styles),
            relevance_note="Topically related (keyword match on title/abstract); read before citing.",
            method="keyword",
        )
        for rec in ranked_kw
    ], usage
