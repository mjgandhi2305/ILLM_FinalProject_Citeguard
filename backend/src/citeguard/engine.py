"""Engine facade: the single entry point used by the CLI, the API worker and evaluation."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx
import structlog

from citeguard.config import Settings, get_settings
from citeguard.domain.models import (
    VERDICT_SEVERITY_ORDER,
    CheckOptions,
    CheckReport,
    CheckSummary,
    CitationResult,
    ClaimSupport,
    Explanation,
    Flag,
    InputKind,
    LLMUsage,
    ParsedReference,
    Verdict,
)
from citeguard.explain.templates import CLAIM_NOT_SUPPORTED_ADVICE, template_explanation
from citeguard.ingest import documents
from citeguard.ingest.bibtex import parse_bibtex
from citeguard.ingest.text import extract_references
from citeguard.parse.heuristic import parse_heuristic
from citeguard.sources.infra import Cache, DiskCache, MemoryCache, NullCache
from citeguard.sources.registry import (
    LimiterFactory,
    SourceSet,
    build_sources,
    local_limiter,
    make_http_client,
)
from citeguard.suggest.alternatives import Reranker, alternatives
from citeguard.suggest.corrections import correction
from citeguard.verify.claims import CHECKABLE, ClaimChecker, check_claims
from citeguard.verify.verifier import Adjudicator, Reformulator, Verifier

log = structlog.get_logger(__name__)

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class ReferenceParser(Protocol):
    async def parse(self, raws: list[str]) -> tuple[list[ParsedReference | None], LLMUsage]: ...


class Explainer(Protocol):
    async def explain(self, result: CitationResult) -> tuple[Explanation | None, LLMUsage]: ...


@dataclass
class LLMServices:
    parser: ReferenceParser | None = None
    adjudicator: Adjudicator | None = None
    reformulator: Reformulator | None = None
    explainer: Explainer | None = None
    reranker: Reranker | None = None
    claim_checker: ClaimChecker | None = None


def make_cache(settings: Settings) -> Cache:
    if settings.cache_backend == "disk":
        return DiskCache(settings.cache_dir / "http")
    if settings.cache_backend == "memory":
        return MemoryCache()
    if settings.cache_backend == "redis":
        from citeguard.sources.infra import RedisCache

        return RedisCache(settings.redis_url)
    return NullCache()


class Engine:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        cache: Cache | None = None,
        limiter_factory: LimiterFactory = local_limiter,
        llm: LLMServices | None = None,
        http_client: httpx.AsyncClient | None = None,
        sources: SourceSet | None = None,
        verifier_options: dict[str, Any] | None = None,
    ) -> None:
        self.verifier_options = verifier_options or {}
        self.settings = settings or get_settings()
        self.cache = cache if cache is not None else make_cache(self.settings)
        self.limiter_factory = limiter_factory
        self._external_client = http_client
        self._client: httpx.AsyncClient | None = None
        self._llm_override = llm
        self.llm: LLMServices | None = None
        self._sources_override = sources
        self.sources: SourceSet | None = None

    async def __aenter__(self) -> Engine:
        self._client = self._external_client or make_http_client(self.settings)
        self.sources = self._sources_override or build_sources(
            self.settings, self._client, self.cache, self.limiter_factory
        )
        if self._llm_override is not None:
            self.llm = self._llm_override
        elif self.settings.llm_available:
            from citeguard.llm.services import build_llm_services

            self.llm = build_llm_services(self.settings, self.cache)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
        close = getattr(self.cache, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result

    # ---------------------------------------------------------------------------------------
    async def parse_input(
        self, kind: InputKind, content: str | bytes, *, use_llm: bool = True
    ) -> tuple[list[ParsedReference], list[str], LLMUsage]:
        warnings: list[str] = []
        usage = LLMUsage()
        if isinstance(content, bytes) and kind in ("pdf", "docx"):
            if kind == "pdf":
                if self.settings.grobid_url and self.settings.parser_strategy in (
                    "hybrid",
                    "grobid",
                ):
                    from citeguard.ingest.grobid import grobid_references

                    try:
                        refs = await grobid_references(self.settings.grobid_url, content)
                        if refs:
                            return refs, warnings, usage
                        warnings.append("GROBID found no references; using text extraction")
                    except Exception as exc:
                        warnings.append(f"GROBID unavailable ({exc}); using text extraction")
                text = documents.pdf_to_text(content)
            else:
                text = documents.docx_to_text(content)
            kind = "text"
        else:
            text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content

        if kind == "bibtex":
            refs, warns = parse_bibtex(text)
            return refs, warnings + warns, usage
        if kind == "latex":
            from citeguard.ingest.latex import parse_latex

            refs, warns = parse_latex(text)
            if refs:
                return refs, warnings + warns, usage
            kind = "text"

        if kind == "citation":
            entries, contexts = [text.strip()], {}
            labels: list[str | None] = [None]
        else:
            found = extract_references(text)
            entries, contexts, labels = found.entries, found.contexts, found.labels
            if not entries:
                warnings.append("No reference list could be identified in the input")

        refs = [parse_heuristic(e) for e in entries]
        parser = self.llm.parser if (self.llm and use_llm) else None
        strategy = self.settings.parser_strategy
        if parser is not None and strategy in ("hybrid", "llm"):
            todo = [i for i, r in enumerate(refs) if strategy == "llm" or r.parse_confidence < 0.7]
            if todo:
                parsed, usage = await parser.parse([entries[i] for i in todo])
                for i, p in zip(todo, parsed, strict=True):
                    if p is not None:
                        refs[i] = p
        for i, r in enumerate(refs):
            r.contexts = contexts.get(i, [])
            r.key = r.key or labels[i]
        return refs, warnings, usage

    # ---------------------------------------------------------------------------------------
    async def check(
        self,
        kind: InputKind,
        content: str | bytes,
        *,
        options: CheckOptions | None = None,
        on_event: EventCallback | None = None,
    ) -> CheckReport:
        assert self.sources is not None, "use `async with Engine(...)`"
        options = options or CheckOptions()
        use_llm = options.use_llm and self.llm is not None
        llm = self.llm if use_llm else None
        report = CheckReport(input_kind=kind, pipeline_version=self.settings.app_version)

        async def emit(event: str, payload: dict[str, Any]) -> None:
            if on_event is not None:
                try:
                    await on_event(event, payload)
                except Exception as exc:  # a broken listener must not break a check
                    log.warning("event.listener_failed", event_name=event, error=str(exc))

        refs, warnings, parse_usage = await self.parse_input(kind, content, use_llm=use_llm)
        if kind == "citation" and options.claim and refs:
            refs[0].contexts = [options.claim.strip()]
        claim_mode = options.check_claims or bool(options.claim)
        if claim_mode and (llm is None or llm.claim_checker is None):
            warnings.append("Claim checks need the LLM (GROQ_API_KEY); none were run.")
            claim_mode = False
        report.warnings += warnings
        report.summary.llm_usage.add(parse_usage)
        await emit("check.parsed", {"count": len(refs)})

        sources = self.sources
        if options.sources:
            assert self._client is not None
            sources = build_sources(
                self.settings,
                self._client,
                self.cache,
                self.limiter_factory,
                options.sources,
            )
        verifier = Verifier(
            sources,
            adjudicator=llm.adjudicator if llm else None,
            reformulator=llm.reformulator if llm else None,
            **self.verifier_options,
        )

        # ---- pass 1: verdicts -------------------------------------------------------------
        sem = asyncio.Semaphore(self.settings.max_concurrency)
        results: list[CitationResult | None] = [None] * len(refs)

        async def run(i: int, ref: ParsedReference) -> None:
            async with sem:
                try:
                    r = await verifier.verify(ref, i)
                except Exception as exc:
                    log.exception("verify.failed", index=i)
                    r = CitationResult(index=i, reference=ref, verdict=Verdict.UNVERIFIABLE)
                    report.warnings.append(f"Citation {i + 1}: verification error ({exc})")
                r.explanation = template_explanation(r)
                if fix := correction(r, options.styles):
                    r.suggestions.append(fix)
                results[i] = r
                await emit("citation.verified", {"citation": r})

        await asyncio.gather(*(run(i, ref) for i, ref in enumerate(refs)))
        done = [r for r in results if r is not None]

        # ---- pass 2: prose + alternatives, most severe first ------------------------------
        def wants_claims(r: CitationResult) -> bool:
            return claim_mode and r.verdict in CHECKABLE and bool(r.reference.contexts)

        todo = sorted(
            (r for r in done if r.verdict != Verdict.VERIFIED or wants_claims(r)),
            key=lambda r: VERDICT_SEVERITY_ORDER[r.verdict],
        )
        sem2 = asyncio.Semaphore(max(1, self.settings.max_concurrency // 2))

        async def enrich(r: CitationResult) -> None:
            async with sem2:
                changed = False
                if options.suggest_alternatives and r.verdict == Verdict.FABRICATED:
                    alts, u = await alternatives(
                        sources, r, options.styles, reranker=llm.reranker if llm else None
                    )
                    r.suggestions += alts
                    r.llm_usage.add(u)
                    changed = True
                if wants_claims(r) and llm and llm.claim_checker:
                    try:
                        r.claim_checks, u = await check_claims(sources, r, llm.claim_checker)
                        r.llm_usage.add(u)
                        changed = True
                    except Exception as exc:
                        log.warning("claims.failed", index=r.index, error=str(exc))
                    unsupported = [
                        c.claim for c in r.claim_checks if c.label == ClaimSupport.NOT_SUPPORTED
                    ]
                    if unsupported:
                        r.flags = sorted({*r.flags, Flag.CLAIM_NOT_SUPPORTED})
                        # the verdict's advice must not say "no action needed"
                        r.explanation = template_explanation(r)
                        if options.suggest_alternatives:
                            alts, u = await alternatives(
                                sources,
                                r,
                                options.styles,
                                reranker=llm.reranker,
                                claim=unsupported[0],
                            )
                            r.suggestions += alts
                            r.llm_usage.add(u)
                if llm and llm.explainer and options.explain and r.verdict != Verdict.VERIFIED:
                    try:
                        expl, u = await llm.explainer.explain(r)
                        r.llm_usage.add(u)
                        if expl is not None:
                            if Flag.CLAIM_NOT_SUPPORTED in r.flags:
                                expl.recommendation = (
                                    f"{CLAIM_NOT_SUPPORTED_ADVICE} {expl.recommendation}"
                                )
                            r.explanation = expl
                            changed = True
                    except Exception as exc:
                        log.warning("explain.failed", index=r.index, error=str(exc))
                r.enriched = True
                if changed:
                    await emit("citation.enriched", {"citation": r})

        await asyncio.gather(*(enrich(r) for r in todo))

        # ---- summary ------------------------------------------------------------------------
        report.citations = done
        counts = Counter(r.verdict.value for r in done)
        modes: set[Literal["template", "llm"]] = {
            r.explanation.mode for r in done if r.explanation and r.verdict != Verdict.VERIFIED
        }
        for r in done:
            report.summary.llm_usage.add(r.llm_usage)
        unhealthy = sorted({s for r in done for s in _failed_sources(r)})
        report.summary = CheckSummary(
            total=len(done),
            by_verdict={v.value: counts.get(v.value, 0) for v in Verdict},
            flagged=sum(1 for r in done if r.is_problem or Flag.CLAIM_NOT_SUPPORTED in r.flags),
            sources_unhealthy=unhealthy,
            llm_usage=report.summary.llm_usage,
            llm_mode="mixed" if len(modes) > 1 else (modes.pop() if modes else "template"),
            claims_checked=sum(len(r.claim_checks) for r in done),
            claims_not_supported=sum(
                1 for r in done for c in r.claim_checks if c.label == ClaimSupport.NOT_SUPPORTED
            ),
        )
        report.finished_at = datetime.now(UTC)
        await emit("check.completed", {"report": report})
        return report

    def source_health(self) -> dict[str, str]:
        return self.sources.health() if self.sources else {}


def _failed_sources(r: CitationResult) -> list[str]:
    from citeguard.domain.models import LookupStatus

    by_source: dict[str, set[LookupStatus]] = {}
    for e in r.evidence:
        by_source.setdefault(e.source, set()).add(e.status)
    ok = {LookupStatus.FOUND, LookupStatus.NOT_FOUND}
    return [s for s, st in by_source.items() if not (st & ok)]
