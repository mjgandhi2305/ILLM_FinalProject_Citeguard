"""LLM-backed pipeline services (Groq). Each one is optional and guarded: the LLM can parse,
choose among retrieved candidates, propose searches, explain and rank, but it can never
decide on its own that a paper exists."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import groq
from pydantic import BaseModel
from rapidfuzz import fuzz

from citeguard.config import Settings
from citeguard.domain.models import (
    Author,
    Candidate,
    CitationResult,
    CitationType,
    ClaimCheck,
    ClaimSupport,
    Explanation,
    Identifiers,
    LLMUsage,
    ParsedReference,
    Reason,
    Record,
    Verdict,
)
from citeguard.engine import LLMServices
from citeguard.explain.bundle import build_bundle, validate_explanation, verdict_contradictions
from citeguard.llm import prompts
from citeguard.llm.client import GroqLLM, StageConfig
from citeguard.llm.limiter import ModelLimiter
from citeguard.match.normalize import fold, normalize_title
from citeguard.parse.identifiers import extract_identifiers, normalize_arxiv_id, normalize_doi
from citeguard.sources.base import SearchQuery
from citeguard.sources.infra import Cache
from citeguard.verify.verifier import AdjudicationOutcome


def _data_block(payload: Any) -> str:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"<data>\n{body}\n</data>"


# --------------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------------
class _AuthorOut(BaseModel):
    family: str
    given: str | None


CitationTypeOut = Literal[
    "article-journal", "paper-conference", "preprint", "book", "chapter", "thesis",
    "report", "webpage", "dataset", "other", "unknown",
]  # fmt: skip


class _RefOut(BaseModel):
    index: int
    title: str | None
    authors: list[_AuthorOut]
    authors_truncated: bool
    container_title: str | None
    year: int | None
    volume: str | None
    issue: str | None
    pages: str | None
    publisher: str | None
    type: CitationTypeOut
    doi: str | None
    arxiv_id: str | None
    pmid: str | None
    isbn: str | None
    url: str | None


class _ParseBatch(BaseModel):
    references: list[_RefOut]


def _appears_in(fragment: str, raw: str, threshold: float = 85) -> bool:
    f, r = fold(fragment), fold(raw)
    if not f:
        return False
    return f in r or fuzz.partial_ratio(f, r) >= threshold


def to_reference(raw: str, out: _RefOut) -> ParsedReference | None:
    """Accept an LLM parse only if it is faithful to the raw string."""
    if out.title and not _appears_in(out.title, raw):
        return None  # the model rewrote or invented the title
    regex_ids = extract_identifiers(raw)
    llm_doi = normalize_doi(out.doi)
    llm_arxiv = normalize_arxiv_id(out.arxiv_id)
    ids = Identifiers(
        doi=regex_ids.doi or (llm_doi if llm_doi and llm_doi in raw.lower() else None),
        arxiv_id=regex_ids.arxiv_id or (llm_arxiv if llm_arxiv and llm_arxiv in raw else None),
        pmid=regex_ids.pmid or (out.pmid if out.pmid and out.pmid in raw else None),
        isbn=regex_ids.isbn,
        url=regex_ids.url,
    )
    authors = [
        Author(family=a.family.strip(), given=(a.given or None))
        for a in out.authors
        if a.family.strip() and _appears_in(a.family, raw, 90)
    ]
    year = out.year if out.year and str(out.year) in raw else None
    try:
        ctype = CitationType(out.type)
    except ValueError:
        ctype = CitationType.UNKNOWN
    return ParsedReference(
        raw=raw,
        authors=authors,
        authors_truncated=out.authors_truncated,
        title=out.title,
        container_title=out.container_title
        if out.container_title and _appears_in(out.container_title, raw, 80)
        else None,
        year=year,
        volume=out.volume,
        issue=out.issue,
        pages=out.pages,
        publisher=out.publisher,
        type=ctype,
        ids=ids,
        parse_method="llm",
        parse_confidence=0.9 if out.title else 0.3,
    )


class LLMReferenceParser:
    def __init__(self, llm: GroqLLM, stage: StageConfig, batch_size: int = 20) -> None:
        self.llm = llm
        self.stage = stage
        self.batch_size = batch_size

    async def parse(self, raws: list[str]) -> tuple[list[ParsedReference | None], LLMUsage]:
        usage = LLMUsage()
        results: list[ParsedReference | None] = [None] * len(raws)
        for start in range(0, len(raws), self.batch_size):
            chunk = raws[start : start + self.batch_size]
            lines = "\n".join(f"[{i}] {r[:1200]}" for i, r in enumerate(chunk))
            stage = StageConfig(
                self.stage.model, self.stage.effort, min(8000, 350 * len(chunk) + 800)
            )
            batch, u = await self.llm.structured(
                stage, prompts.PARSE, _data_block(lines), _ParseBatch
            )
            usage.add(u)
            if batch is None:
                continue
            for out in batch.references:
                if 0 <= out.index < len(chunk):
                    results[start + out.index] = to_reference(chunk[out.index], out)
        return results, usage


# --------------------------------------------------------------------------------------------
# Adjudication
# --------------------------------------------------------------------------------------------
class _Adjudication(BaseModel):
    decision: Literal["match", "none"]
    candidate_id: str | None
    confidence: float
    rationale: str


def _citation_view(ref: ParsedReference) -> dict[str, Any]:
    return {
        "as_written": ref.raw[:700],
        "title": ref.title,
        "authors": [a.display() for a in ref.authors[:8]],
        "year": ref.year,
        "venue": ref.container_title,
    }


def _record_view(r: Record, abstract_chars: int = 0) -> dict[str, Any]:
    view: dict[str, Any] = {
        "title": r.title,
        "authors": [a.display() for a in r.authors[:8]],
        "year": r.year,
        "venue": r.container_title,
        "doi": r.doi,
        "type": r.type.value,
    }
    if abstract_chars and r.abstract:
        view["abstract"] = r.abstract[:abstract_chars]
    return view


class LLMAdjudicator:
    MIN_TITLE_SIM = 0.55  # the model may not pick a candidate below this floor

    def __init__(self, llm: GroqLLM, stage: StageConfig) -> None:
        self.llm = llm
        self.stage = stage

    async def adjudicate(
        self, ref: ParsedReference, candidates: list[Candidate]
    ) -> AdjudicationOutcome | None:
        ids = {f"c{i + 1}": c for i, c in enumerate(candidates)}
        payload = {
            "citation": _citation_view(ref),
            "candidates": {cid: _record_view(c.record) for cid, c in ids.items()},
        }
        out, usage = await self.llm.structured(
            self.stage, prompts.ADJUDICATE, _data_block(payload), _Adjudication
        )
        if out is None:
            return AdjudicationOutcome(chosen=None, rejected_all=False, usage=usage)
        if out.decision == "none":
            return AdjudicationOutcome(
                chosen=None, rejected_all=True, rationale=out.rationale, usage=usage
            )
        chosen = ids.get(out.candidate_id or "")
        if chosen is None or chosen.features.title_sim < self.MIN_TITLE_SIM:
            return AdjudicationOutcome(chosen=None, rejected_all=False, usage=usage)
        return AdjudicationOutcome(
            chosen=chosen, rejected_all=False, rationale=out.rationale, usage=usage
        )


# --------------------------------------------------------------------------------------------
# Query reformulation
# --------------------------------------------------------------------------------------------
class _Query(BaseModel):
    title: str | None
    keywords: str | None
    author: str | None


class _Queries(BaseModel):
    queries: list[_Query]


class LLMReformulator:
    def __init__(self, llm: GroqLLM, stage: StageConfig) -> None:
        self.llm = llm
        self.stage = stage

    async def reformulate(
        self, ref: ParsedReference, closest: list[Record]
    ) -> tuple[list[SearchQuery], LLMUsage]:
        payload = {
            "citation": _citation_view(ref),
            "closest_records_found": [_record_view(r) for r in closest[:3]],
        }
        out, usage = await self.llm.structured(
            self.stage, prompts.REFORMULATE, _data_block(payload), _Queries
        )
        if out is None:
            return [], usage
        claimed_families = {fold(a.family) for a in ref.authors}
        queries: list[SearchQuery] = []
        seen = {normalize_title(ref.title)}
        for q in out.queries[:4]:
            text = (q.title or q.keywords or "").strip()
            if not text or normalize_title(text) in seen:
                continue
            seen.add(normalize_title(text))
            author = q.author if q.author and fold(q.author) in claimed_families else None
            queries.append(
                SearchQuery(
                    title=q.title.strip() if q.title else None,
                    text=q.keywords.strip() if q.keywords and not q.title else None,
                    author=author,
                )
            )
        return queries, usage


# --------------------------------------------------------------------------------------------
# Explanations
# --------------------------------------------------------------------------------------------
class _ReasonOut(BaseModel):
    text: str
    evidence_ids: list[str]


class _ExplanationOut(BaseModel):
    verdict_echo: str
    headline: str
    reasons: list[_ReasonOut]
    recommendation: str


HEADLINE_PREFIX = {
    "FABRICATED": "Likely fabricated:",
    "MISATTRIBUTED": "Misattributed:",
    "VERIFIED_WITH_ERRORS": "Real paper with errors:",
    "VERIFIED": "Verified:",
    "UNVERIFIABLE": "Could not verify:",
}


def _with_verdict_prefix(headline: str, verdict: Verdict) -> str:
    """The headline must open with the verdict's own label, whatever the model wrote."""
    expected = HEADLINE_PREFIX[verdict.value]
    text = headline.strip()
    head, sep, rest = text.partition(":")
    if sep and len(head) <= 40:  # model wrote some "<label>:" prefix; replace it
        text = rest.strip()
    return f"{expected} {text[:1].lower() + text[1:]}" if text else expected


class LLMExplainer:
    def __init__(self, llm: GroqLLM, stage: StageConfig) -> None:
        self.llm = llm
        self.stage = stage

    async def explain(self, result: CitationResult) -> tuple[Explanation | None, LLMUsage]:
        usage = LLMUsage()
        bundle = build_bundle(result)
        user = _data_block(bundle)
        feedback = ""
        for attempt in range(2):
            out, u = await self.llm.structured(
                self.stage,
                prompts.EXPLAIN,
                user + feedback,
                _ExplanationOut,
                use_cache=attempt == 0,
            )
            usage.add(u)
            if out is None:
                return None, usage
            problems = []
            if out.verdict_echo.strip().upper() != result.verdict.value:
                problems.append(f"verdict_echo must be {result.verdict.value}")
            if not out.reasons:
                problems.append("at least one reason is required")
            texts = [out.headline, out.recommendation] + [r.text for r in out.reasons]
            problems += validate_explanation(texts, [r.evidence_ids for r in out.reasons], bundle)
            problems += verdict_contradictions(out.headline, result.verdict)
            if (
                _with_verdict_prefix(out.headline, result.verdict)
                == HEADLINE_PREFIX[result.verdict.value]
            ):  # seen in the demo: "Real paper with errors:" and nothing after it
                problems.append("headline must state the main finding after the verdict label")
            if not problems:
                return (
                    Explanation(
                        headline=_with_verdict_prefix(out.headline, result.verdict),
                        reasons=[
                            Reason(text=r.text.strip(), evidence_ids=r.evidence_ids)
                            for r in out.reasons[:5]
                        ],
                        recommendation=out.recommendation.strip(),
                        mode="llm",
                    ),
                    usage,
                )
            feedback = (
                "\n\nYour previous answer was rejected by the grounding validator:\n- "
                + "\n- ".join(problems[:8])
                + "\nRewrite it using only facts and ids from the bundle."
            )
            usage.failures += 1
        return None, usage


# --------------------------------------------------------------------------------------------
# Alternatives rerank
# --------------------------------------------------------------------------------------------
class _Pick(BaseModel):
    candidate_id: str
    relevance_note: str


class _Picks(BaseModel):
    selections: list[_Pick]


class LLMReranker:
    def __init__(self, llm: GroqLLM, stage: StageConfig) -> None:
        self.llm = llm
        self.stage = stage

    async def rerank(
        self, ref: ParsedReference, candidates: list[Record], k: int
    ) -> tuple[list[tuple[Record, str]] | None, LLMUsage]:
        ids = {f"c{i + 1}": r for i, r in enumerate(candidates[:15])}
        payload = {
            "citation": _citation_view(ref),
            "cited_in_sentences": ref.contexts[:3],
            "candidates": {cid: _record_view(r, abstract_chars=500) for cid, r in ids.items()},
        }
        out, usage = await self.llm.structured(
            self.stage, prompts.RERANK.format(k=k), _data_block(payload), _Picks
        )
        if out is None:
            return None, usage
        picked: list[tuple[Record, str]] = []
        for p in out.selections:
            rec = ids.get(p.candidate_id)
            if rec is not None and rec not in [r for r, _ in picked]:
                picked.append((rec, p.relevance_note.strip()))
        return picked[:k], usage


# --------------------------------------------------------------------------------------------
# Claim support (opt-in)
# --------------------------------------------------------------------------------------------
class _ClaimJudgement(BaseModel):
    claim_id: str
    label: Literal["SUPPORTS", "PARTIAL", "NOT_SUPPORTED", "CANNOT_DETERMINE"]
    quote: str
    rationale: str


class _ClaimJudgements(BaseModel):
    judgements: list[_ClaimJudgement]


def _quote_in(quote: str, folded_abstract: str) -> bool:
    """Verbatim (after folding case and punctuation); "…" may join two abstract passages."""
    parts = [fold(p) for p in re.split(r"\.\.\.|…", quote)]
    parts = [p for p in parts if p]
    return sum(len(p.split()) for p in parts) >= 4 and all(p in folded_abstract for p in parts)


class LLMClaimChecker:
    def __init__(self, llm: GroqLLM, stage: StageConfig) -> None:
        self.llm = llm
        self.stage = stage

    async def check(
        self, record: Record, abstract: str, claims: list[str]
    ) -> tuple[list[ClaimCheck] | None, LLMUsage]:
        usage = LLMUsage()
        ids = {f"s{i + 1}": c for i, c in enumerate(claims)}
        payload = {"cited_paper": _record_view(record), "abstract": abstract, "claims": ids}
        folded = fold(abstract)
        answers: dict[str, _ClaimJudgement] | None = None
        feedback = ""
        for attempt in range(2):
            out, u = await self.llm.structured(
                self.stage,
                prompts.CLAIM,
                _data_block(payload) + feedback,
                _ClaimJudgements,
                use_cache=attempt == 0,
            )
            usage.add(u)
            if out is None:
                break
            answers = {}
            problems = []
            for j in out.judgements:
                if j.claim_id not in ids:
                    problems.append(f"unknown claim id {j.claim_id!r}")
                elif j.claim_id not in answers:
                    answers[j.claim_id] = j
                    if j.label != "CANNOT_DETERMINE" and not _quote_in(j.quote, folded):
                        problems.append(
                            f"{j.claim_id}: the quote is not verbatim from the abstract"
                        )
            problems += [f"no judgement for {cid}" for cid in ids if cid not in answers]
            if not problems:
                break
            feedback = "\n\nYour previous answer had problems; fix them: " + "; ".join(problems)
        if answers is None:
            return None, usage

        checks = []
        for cid, claim in ids.items():
            ans = answers.get(cid)
            if ans is None or (
                ans.label != "CANNOT_DETERMINE" and not _quote_in(ans.quote, folded)
            ):
                # An ungrounded judgement is never shown as a finding.
                checks.append(
                    ClaimCheck(
                        claim=claim,
                        label=ClaimSupport.CANNOT_DETERMINE,
                        rationale="The check could not be tied to the abstract text.",
                        mode="none",
                    )
                )
            else:
                checks.append(
                    ClaimCheck(
                        claim=claim,
                        label=ClaimSupport(ans.label),
                        rationale=ans.rationale.strip(),
                        quote=ans.quote.strip() or None,
                    )
                )
        return checks, usage


# --------------------------------------------------------------------------------------------
def build_llm_services(settings: Settings, cache: Cache) -> LLMServices:
    assert settings.groq_api_key is not None
    client = groq.AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(),
        max_retries=1,
        timeout=settings.llm_timeout_s,
    )
    limiter = ModelLimiter(
        settings.llm_rpm, settings.llm_tpm, settings.llm_tpd, settings.llm_daily_token_budget
    )
    llm = GroqLLM(
        client,
        limiter,
        cache=cache,
        fallback_models=settings.llm_fallback_models,
        timeout_s=settings.llm_timeout_s,
    )
    return LLMServices(
        parser=LLMReferenceParser(
            llm,
            StageConfig(settings.llm_model_parse, "low", 8000),
            batch_size=settings.llm_parse_batch_size,
        ),
        adjudicator=LLMAdjudicator(llm, StageConfig(settings.llm_model_adjudicate, "medium", 2000)),
        reformulator=LLMReformulator(llm, StageConfig(settings.llm_model_reformulate, "low", 1200)),
        explainer=LLMExplainer(llm, StageConfig(settings.llm_model_explain, "medium", 2500)),
        reranker=LLMReranker(llm, StageConfig(settings.llm_model_suggest, "low", 2000)),
        claim_checker=LLMClaimChecker(llm, StageConfig(settings.llm_model_claims, "low", 4000)),
    )
