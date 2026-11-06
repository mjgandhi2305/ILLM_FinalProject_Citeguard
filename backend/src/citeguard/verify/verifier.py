"""Per-citation verification orchestrator (pipeline steps 3–6)."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

import structlog

from citeguard.domain.models import (
    Candidate,
    CitationResult,
    CitationType,
    Flag,
    LLMUsage,
    LookupStatus,
    ParsedReference,
    Record,
)
from citeguard.match.linkage import (
    AMBIGUOUS_THRESHOLD,
    DEFAULT_MODEL,
    MATCH_THRESHOLD,
    STRONG_TITLE,
    LinkageModel,
    compute_features,
)
from citeguard.match.names import compare_authors
from citeguard.match.normalize import fold, normalize_title, title_similarity
from citeguard.match.venues import canonical_venue, is_preprint_venue
from citeguard.parse.heuristic import locate_title, parse_heuristic
from citeguard.parse.identifiers import is_valid_doi_syntax, normalize_doi
from citeguard.screen.heuristics import screen
from citeguard.sources.base import SearchQuery, Source, SourceResponse
from citeguard.sources.registry import SourceSet
from citeguard.verify.evidence import EvidenceLog
from citeguard.verify.rules import IdFindings, decide

log = structlog.get_logger(__name__)

_CS_VENUES = {
    "neurips", "icml", "iclr", "aistats", "colt", "cvpr", "iccv", "eccv", "acl", "emnlp",
    "naacl", "tacl", "aaai", "ijcai", "kdd", "www", "sigir", "chi", "icse", "jmlr", "tpami",
    "tmlr", "arxiv", "pmlr",
}  # fmt: skip
_CS_RE = re.compile(
    r"comput|learning|neural|intelligen|vision|language|robot|software|\bdata\b|ieee|\bacm\b|"
    r"algorithm|network|information|arxiv|corr",
    re.IGNORECASE,
)
_BIOMED_RE = re.compile(
    r"medic|clinic|health|lancet|jama|\bbmj\b|nejm|\bcell\b|\bbio|genet|cancer|oncol|pharm|"
    r"neuro|nurs|epidem|immun|patho|surg|psychiat|physiol|plos|virol|cardio|pediatr|"
    r"diabet|disease|molecul|protein|\bgen(e|om)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------------------------
# LLM hook protocols (implemented in citeguard.llm; absent in LLM-off mode)
# --------------------------------------------------------------------------------------------
@dataclass
class AdjudicationOutcome:
    chosen: Candidate | None
    rejected_all: bool
    rationale: str | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)


class Adjudicator(Protocol):
    async def adjudicate(
        self, ref: ParsedReference, candidates: list[Candidate]
    ) -> AdjudicationOutcome | None: ...


class Reformulator(Protocol):
    async def reformulate(
        self, ref: ParsedReference, closest: list[Record]
    ) -> tuple[list[SearchQuery], LLMUsage]: ...


# --------------------------------------------------------------------------------------------
class Verifier:
    def __init__(
        self,
        sources: SourceSet,
        *,
        model: LinkageModel = DEFAULT_MODEL,
        adjudicator: Adjudicator | None = None,
        reformulator: Reformulator | None = None,
        chimera_check: bool = True,
        exact_titles: bool = False,
    ) -> None:
        self.exact_titles = exact_titles  # ablation: only exact (normalized) title matches count
        self.sources = sources
        self.model = model
        self.adjudicator = adjudicator
        self.reformulator = reformulator
        self.chimera_check = chimera_check

    # ---------------------------------------------------------------------------------------
    async def verify(
        self, ref: ParsedReference, index: int, *, reparsed: bool = False
    ) -> CitationResult:
        started = time.perf_counter()
        risk, signals = screen(ref)
        evlog = EvidenceLog()
        cands: list[Candidate] = []
        ids = IdFindings()
        usage = LLMUsage()

        await self._identifier_phase(ref, evlog, cands, ids)

        if ref.title and not self._confirmed(cands, ids):
            await self._search(ref, self.sources.general(), evlog, cands, ids)
        if ref.title and not self._confirmed(cands, ids):
            specialists = self._route_specialists(ref)
            if specialists:
                await self._search(ref, specialists, evlog, cands, ids)

        if not reparsed and ref.title and not self._confirmed(cands, ids):
            fixed = await self._reparse(ref, evlog, cands, ids)
            if fixed is not None:
                log.info("verify.reparsed", index=index, old=ref.title, new=fixed.title)
                return await self.verify(fixed, index, reparsed=True)

        reformulated = False
        if (
            self.reformulator is not None
            and ref.title
            and not self._confirmed(cands, ids)
            and not any(c.probability >= AMBIGUOUS_THRESHOLD for c in self._search_pool(cands, ids))
        ):
            reformulated = await self._reformulate(ref, evlog, cands, ids, usage)

        adjudicated: Candidate | None = None
        rejected_all = False
        if self.adjudicator is not None and not self._confirmed(cands, ids):
            ambiguous = self._dedupe(
                [
                    c
                    for c in self._search_pool(cands, ids)
                    if AMBIGUOUS_THRESHOLD <= c.probability < MATCH_THRESHOLD
                ]
            )[:3]
            if ambiguous:
                outcome = await self.adjudicator.adjudicate(ref, ambiguous)
                if outcome is not None:
                    usage.add(outcome.usage)
                    adjudicated = outcome.chosen
                    rejected_all = outcome.rejected_all

        chimera = None
        if self.chimera_check and ref.authors and ref.title:
            chimera = await self._maybe_chimera(ref, evlog, cands, ids)

        general = self.sources.general()
        responded = sum(1 for s in general if evlog.responded(s.name))
        failed = set(evlog.failed_sources())
        unhealthy = sum(1 for s in general if s.name in failed)

        decision = decide(
            ref,
            cands,
            ids,
            adjudicated=adjudicated,
            adjudication_rejected_all=rejected_all,
            llm_used=self.adjudicator is not None,
            reformulated=reformulated,
            general_responded=responded if not self._confirmed(cands, ids) else len(general),
            unhealthy_general=unhealthy,
            risk=risk,
            chimera=chimera,
        )
        flags = list(decision.flags)
        if ref.parse_confidence < 0.5:
            flags.append(Flag.LOW_PARSE_CONFIDENCE)

        return CitationResult(
            index=index,
            reference=ref,
            risk_score=risk,
            risk_signals=signals,
            verdict=decision.verdict,
            confidence=decision.confidence,
            flags=sorted(set(flags)),
            discrepancies=decision.discrepancies,
            best_match=decision.best or None,
            candidates=self._dedupe(sorted(cands, key=lambda c: -c.probability))[:5],
            evidence=evlog.items,
            llm_usage=usage,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # ---------------------------------------------------------------------------------------
    def _score(self, ref: ParsedReference, rec: Record, ev_id: str, ids: IdFindings) -> Candidate:
        features = compute_features(ref, rec)
        if self.exact_titles:
            exact = normalize_title(ref.title) == normalize_title(rec.title)
            features = features.model_copy(update={"title_sim": 1.0 if exact else 0.0})
        # A claimed identifier that is known to point at another work must not boost records
        # that carry that identifier.
        if features.id_match and (ids.doi_points_elsewhere or ids.arxiv_points_elsewhere):
            features = features.model_copy(update={"id_match": None})
        return Candidate(
            record=rec,
            features=features,
            probability=self.model.probability(features),
            evidence_id=ev_id,
        )

    def _add(
        self,
        ref: ParsedReference,
        evlog: EvidenceLog,
        cands: list[Candidate],
        ids: IdFindings,
        source: str,
        op: Literal["lookup", "search", "registry"],
        query: str,
        resp: SourceResponse,
    ) -> list[Candidate]:
        ev = evlog.add(source, op, query, resp)
        new = [self._score(ref, rec, ev.id, ids) for rec in resp.records[:5]]
        cands.extend(new)
        return new

    def _search_pool(self, cands: list[Candidate], ids: IdFindings) -> list[Candidate]:
        excluded = {id(c) for c in (ids.doi_candidate, ids.arxiv_candidate) if c is not None}
        return [c for c in cands if id(c) not in excluded]

    def _confirmed(self, cands: list[Candidate], ids: IdFindings) -> bool:
        if ids.doi_candidate is not None and not ids.doi_points_elsewhere:
            return True
        if ids.arxiv_candidate is not None and not ids.arxiv_points_elsewhere:
            return True
        return any(
            c.probability >= MATCH_THRESHOLD
            or (c.features.title_sim >= STRONG_TITLE and (c.features.author_f1 or 0) >= 0.5)
            for c in self._search_pool(cands, ids)
        )

    @staticmethod
    def _dedupe(cands: list[Candidate]) -> list[Candidate]:
        seen: set[str] = set()
        out = []
        for c in cands:
            key = (
                normalize_doi(c.record.doi) or f"{normalize_title(c.record.title)}|{c.record.year}"
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return out

    @staticmethod
    def _points_elsewhere(ref: ParsedReference, cand: Candidate) -> bool:
        if not ref.title:
            return False
        f = cand.features
        if f.title_sim < 0.6:
            return True
        return f.title_sim < 0.85 and f.author_f1 is not None and f.author_f1 < 0.5

    # ---------------------------------------------------------------------------------------
    async def _identifier_phase(
        self, ref: ParsedReference, evlog: EvidenceLog, cands: list[Candidate], ids: IdFindings
    ) -> None:
        jobs = []
        if ref.ids.doi:
            jobs.append(self._resolve_doi(ref, evlog, cands, ids))
        if ref.ids.arxiv_id:
            jobs.append(self._resolve_arxiv(ref, evlog, cands, ids))
        if ref.ids.pmid and (pubmed := self.sources.get("pubmed")):
            jobs.append(self._resolve_pmid(ref, pubmed, evlog, cands, ids))
        if jobs:
            await asyncio.gather(*jobs)

    async def _resolve_doi(
        self, ref: ParsedReference, evlog: EvidenceLog, cands: list[Candidate], ids: IdFindings
    ) -> None:
        doi = normalize_doi(ref.ids.doi) or ref.ids.doi or ""
        if not is_valid_doi_syntax(doi):
            ids.doi_status = "invalid"
            return
        tasks: dict[str, asyncio.Task[SourceResponse]] = {}
        async with asyncio.TaskGroup() as tg:
            if self.sources.doi:
                tasks["doi"] = tg.create_task(self.sources.doi.registered(doi))
            for name in ("crossref", "openalex"):
                if src := self.sources.get(name):
                    tasks[name] = tg.create_task(src.lookup("doi", doi))
        found: list[Candidate] = []
        if "doi" in tasks:
            reg = tasks["doi"].result()
            ev = evlog.add("doi", "registry", f"doi:{doi}", reg)
            ids.doi_evidence = ev.id
            ids.doi_status = {
                LookupStatus.FOUND: "registered",
                LookupStatus.NOT_FOUND: "unregistered",
            }.get(reg.status, "unknown")  # type: ignore[assignment]
        for name in ("crossref", "openalex"):
            if name in tasks:
                found += self._add(
                    ref, evlog, cands, ids, name, "lookup", f"doi:{doi}", tasks[name].result()
                )
        if found and ids.doi_status in ("unknown", "absent"):
            ids.doi_status = "registered"
        if not found and ids.doi_status == "registered" and self.sources.doi:
            # Non-Crossref DOI (DataCite: arXiv, Zenodo, …): ask doi.org for CSL-JSON.
            resp = await self.sources.doi.lookup("doi", doi)
            found += self._add(ref, evlog, cands, ids, "doi", "lookup", f"doi:{doi}", resp)
        if found:
            best = max(found, key=lambda c: (c.features.title_sim, c.probability))
            ids.doi_candidate = best
            ids.doi_points_elsewhere = self._points_elsewhere(ref, best)
            if ids.doi_points_elsewhere:  # neutralize the id boost on everything found so far
                for i, c in enumerate(cands):
                    if c.features.id_match:
                        cands[i] = self._score(ref, c.record, c.evidence_id, ids)
                ids.doi_candidate = next(
                    (c for c in cands if c.record is best.record), ids.doi_candidate
                )

    async def _resolve_arxiv(
        self, ref: ParsedReference, evlog: EvidenceLog, cands: list[Candidate], ids: IdFindings
    ) -> None:
        arxiv_id = ref.ids.arxiv_id or ""
        src = self.sources.get("arxiv")
        s2 = self.sources.get("semantic_scholar")
        found: list[Candidate] = []
        if src is not None:
            resp = await src.lookup("arxiv", arxiv_id)
            ev = evlog.add("arxiv", "lookup", f"arXiv:{arxiv_id}", resp)
            ids.arxiv_evidence = ev.id
            ids.arxiv_status = {
                LookupStatus.FOUND: "registered",
                LookupStatus.NOT_FOUND: "unregistered",
            }.get(resp.status, "unknown")  # type: ignore[assignment]
            found += [self._score(ref, r, ev.id, ids) for r in resp.records[:1]]
            cands.extend(found)
        if s2 is not None and ids.arxiv_status != "unregistered":
            resp = await s2.lookup("arxiv", arxiv_id)
            found += self._add(ref, evlog, cands, ids, s2.name, "lookup", f"arXiv:{arxiv_id}", resp)
            if found and ids.arxiv_status in ("absent", "unknown"):
                ids.arxiv_status = "registered"
        if found:
            best = max(found, key=lambda c: (c.features.title_sim, c.probability))
            ids.arxiv_candidate = best
            ids.arxiv_points_elsewhere = self._points_elsewhere(ref, best)

    async def _resolve_pmid(
        self,
        ref: ParsedReference,
        pubmed: Source,
        evlog: EvidenceLog,
        cands: list[Candidate],
        ids: IdFindings,
    ) -> None:
        resp = await pubmed.lookup("pmid", ref.ids.pmid or "")
        self._add(ref, evlog, cands, ids, pubmed.name, "lookup", f"PMID:{ref.ids.pmid}", resp)

    # ---------------------------------------------------------------------------------------
    async def _search(
        self,
        ref: ParsedReference,
        sources: list[Source],
        evlog: EvidenceLog,
        cands: list[Candidate],
        ids: IdFindings,
        query: SearchQuery | None = None,
    ) -> None:
        q = query or SearchQuery.from_reference(ref)
        resps = await asyncio.gather(*(s.search(q, 5) for s in sources))
        for src, resp in zip(sources, resps, strict=True):
            self._add(ref, evlog, cands, ids, src.name, "search", q.describe(), resp)

    def _route_specialists(self, ref: ParsedReference) -> list[Source]:
        venue = ref.container_title or ""
        haystack = f"{venue} {ref.title or ''}"
        canonical = canonical_venue(venue)
        cs = canonical in _CS_VENUES or bool(_CS_RE.search(venue))
        biomed = bool(_BIOMED_RE.search(haystack))
        out: list[Source] = []
        for src in self.sources.specialist():
            if (
                (
                    src.name == "arxiv"
                    and (
                        ref.type in (CitationType.PREPRINT, CitationType.UNKNOWN)
                        or cs
                        or is_preprint_venue(venue)
                    )
                )
                or (src.name == "pubmed" and (biomed or ref.type == CitationType.UNKNOWN))
                or (src.name == "dblp" and cs)
            ):
                out.append(src)
        return out

    async def _reparse(
        self, ref: ParsedReference, evlog: EvidenceLog, cands: list[Candidate], ids: IdFindings
    ) -> ParsedReference | None:
        """A real record whose title and first author both appear word for word in the citation
        means the parse went wrong (e.g. an author list the parser could not read), not that
        the paper is missing. Returns the citation re-parsed around that title."""
        if ref.parse_method not in ("heuristic", "llm", "grobid"):
            return None
        raw = f" {fold(ref.raw)} "

        def anchor(cs: list[Candidate]) -> Record | None:
            for c in sorted(cs, key=lambda c: -c.probability):
                r = c.record
                if (
                    r.title
                    and r.authors
                    and normalize_title(r.title) != normalize_title(ref.title)
                    # "Ibiapina Brito" is cited as "Brito GMI": any word of the family name
                    and any(
                        f" {w} " in raw for w in fold(r.authors[0].family).split() if len(w) >= 3
                    )
                    and locate_title(ref.raw, r.title)
                ):
                    return r
            return None

        hit = anchor(cands)
        crossref = self.sources.get("crossref")
        if hit is None and crossref is not None:  # Crossref matches whole reference strings
            seen = len(cands)
            await self._search(
                ref, [crossref], evlog, cands, ids, query=SearchQuery(text=ref.raw[:500])
            )
            hit = anchor(cands[seen:])
        if hit is None:
            return None
        return parse_heuristic(ref.raw, title_hint=hit.title)

    async def _reformulate(
        self,
        ref: ParsedReference,
        evlog: EvidenceLog,
        cands: list[Candidate],
        ids: IdFindings,
        usage: LLMUsage,
    ) -> bool:
        assert self.reformulator is not None
        closest = [c.record for c in sorted(cands, key=lambda c: -c.probability)[:3]]
        try:
            queries, u = await self.reformulator.reformulate(ref, closest)
        except Exception as exc:  # LLM failures must never fail verification
            log.warning("reformulate.failed", error=str(exc))
            return False
        usage.add(u)
        targets = [s for s in (self.sources.get("openalex"), self.sources.get("crossref")) if s]
        for q in queries[:4]:
            await self._search(ref, targets, evlog, cands, ids, query=q)
            if self._confirmed(cands, ids):
                break
        return bool(queries)

    async def _maybe_chimera(
        self, ref: ParsedReference, evlog: EvidenceLog, cands: list[Candidate], ids: IdFindings
    ) -> Candidate | None:
        """If the title matches a real paper but the authors do not, look for a different
        paper by the claimed authors (title from one work, authors from another)."""
        title_matches = [
            c for c in self._search_pool(cands, ids) if c.features.title_sim >= STRONG_TITLE
        ] + ([ids.doi_candidate] if ids.doi_candidate and not ids.doi_points_elsewhere else [])
        if not title_matches:
            return None
        best = max(title_matches, key=lambda c: c.features.author_f1 or 0.0)
        if best.features.author_f1 is None or best.features.author_f1 >= 0.5:
            return None
        src = self.sources.get("crossref") or self.sources.get("openalex")
        if src is None:
            return None
        q = SearchQuery(
            text=" ".join(str(x) for x in (ref.container_title, ref.year) if x) or None,
            author=" ".join(a.family for a in ref.authors[:3]),
            year=ref.year,
        )
        resp = await src.search(q, 5)
        ev = evlog.add(src.name, "search", f"authors: {q.author}", resp)
        for rec in resp.records:
            cmp = compare_authors(ref.authors, rec.authors, ref.authors_truncated)
            # The other work must carry most of the listed authors, not one shared surname
            # from a fuzzy author search.
            if (
                (cmp.precision or 0.0) >= 0.8
                and cmp.matched >= min(2, len(ref.authors))
                and title_similarity(ref.title, rec.title) < 0.8
            ):
                return Candidate(
                    record=rec,
                    features=compute_features(ref, rec),
                    probability=0.0,
                    evidence_id=ev.id,
                )
        return None
