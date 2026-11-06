"""Opt-in claim-support check: abstract retrieval, the grounded LLM judgement, engine wiring."""

from __future__ import annotations

import json
from collections.abc import Callable

import respx

from citeguard.config import Settings
from citeguard.domain.models import (
    CheckOptions,
    ClaimCheck,
    ClaimSupport,
    Flag,
    LLMUsage,
    Record,
    Verdict,
)
from citeguard.engine import Engine, LLMServices
from citeguard.llm.services import LLMClaimChecker
from citeguard.report.exporters import to_csv, to_html
from citeguard.sources.infra import NullCache
from citeguard.sources.registry import SourceSet
from citeguard.verify.claims import clean_abstract
from tests.conftest import ATTENTION, BERT, CORPUS, DEEP_LEARNING
from tests.unit.test_llm import GROQ_URL, STAGE, completion, make_llm

ABSTRACT = (
    "The dominant sequence transduction models are based on complex recurrent or convolutional "
    "neural networks. We propose a new simple network architecture, the Transformer, based "
    "solely on attention mechanisms, dispensing with recurrence and convolutions entirely. "
    "Experiments on two machine translation tasks show these models to be superior in quality "
    "while being more parallelizable and requiring significantly less time to train."
)
SUPPORTED = "Attention-only models outperform recurrent networks on machine translation [1]."
UNSUPPORTED = "Transformers cure protein misfolding in mice [1]."


def with_abstracts(corpus: list[Record]) -> list[Record]:
    return [
        r.model_copy(update={"abstract": ABSTRACT}) if r.title == ATTENTION.title else r
        for r in corpus
    ]


def test_clean_abstract_strips_jats_and_rejects_stubs() -> None:
    jats = "<jats:title>Abstract</jats:title><jats:p>" + "word " * 40 + "&amp; more</jats:p>"
    cleaned = clean_abstract(jats)
    assert cleaned is not None and "<" not in cleaned and "& more" in cleaned
    assert clean_abstract("Abstract: too short to judge anything.") is None


@respx.mock
async def test_checker_accepts_a_verbatim_quote() -> None:
    respx.post(GROQ_URL).mock(
        return_value=completion(
            {
                "judgements": [
                    {
                        "claim_id": "s1",
                        "label": "SUPPORTS",
                        "quote": "Experiments on two machine translation tasks show these models "
                        "to be superior in quality",
                        "rationale": "The abstract reports better translation quality.",
                    }
                ]
            }
        )
    )
    checks, usage = await LLMClaimChecker(make_llm(), STAGE).check(ATTENTION, ABSTRACT, [SUPPORTED])
    assert checks is not None and checks[0].label == ClaimSupport.SUPPORTS
    assert checks[0].mode == "llm" and usage.calls == 1


@respx.mock
async def test_checker_never_shows_an_ungrounded_judgement() -> None:
    invented = {
        "judgements": [
            {
                "claim_id": "s1",
                "label": "NOT_SUPPORTED",
                "quote": "Transformers have no effect on protein folding.",  # not in the abstract
                "rationale": "The paper says the opposite.",
            }
        ]
    }
    route = respx.post(GROQ_URL).mock(return_value=completion(invented))
    checks, _ = await LLMClaimChecker(make_llm(), STAGE).check(ATTENTION, ABSTRACT, [UNSUPPORTED])
    assert route.call_count == 2  # one retry with feedback
    retry = json.loads(route.calls[1].request.content)["messages"][1]["content"]
    assert "not verbatim from the abstract" in retry
    assert checks is not None
    assert checks[0].label == ClaimSupport.CANNOT_DETERMINE and checks[0].mode == "none"


class FakeChecker:
    def __init__(self) -> None:
        self.calls = 0

    async def check(
        self, record: Record, abstract: str, claims: list[str]
    ) -> tuple[list[ClaimCheck] | None, LLMUsage]:
        self.calls += 1
        return [
            ClaimCheck(
                claim=c,
                label=ClaimSupport.NOT_SUPPORTED if "protein" in c else ClaimSupport.SUPPORTS,
                rationale="test",
                quote="based solely on attention mechanisms",
            )
            for c in claims
        ], LLMUsage(calls=1)


DOC = f"""Intro. {SUPPORTED} {UNSUPPORTED} Deep nets also work [2].

References
[1] Vaswani, A., Shazeer, N., Parmar, N., & Uszkoreit, J. (2017). Attention Is All You Need. Advances in Neural Information Processing Systems.
[2] LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521, 436-444.
"""


async def test_engine_checks_claims_of_verified_citations(
    make_sources: Callable[..., SourceSet],
) -> None:
    checker = FakeChecker()
    services = LLMServices(claim_checker=checker)
    settings = Settings(cache_backend="none", groq_api_key=None)
    sources = make_sources(with_abstracts(CORPUS))
    async with Engine(settings, llm=services, sources=sources, cache=NullCache()) as engine:
        report = await engine.check(
            "text", DOC, options=CheckOptions(check_claims=True, suggest_alternatives=True)
        )
    attention, deep = report.citations
    assert attention.verdict == Verdict.VERIFIED
    labels = {c.claim: c.label for c in attention.claim_checks}
    assert labels[SUPPORTED] == ClaimSupport.SUPPORTS
    assert labels[UNSUPPORTED] == ClaimSupport.NOT_SUPPORTED
    assert Flag.CLAIM_NOT_SUPPORTED in attention.flags
    assert attention.claim_checks[0].abstract_source == "crossref"
    # Alternatives for an unsupported claim never include the cited paper itself.
    assert all(s.record.title != ATTENTION.title for s in attention.suggestions)
    # Deep learning has no abstract in this corpus: undetermined, and no LLM call is spent.
    assert [c.label for c in deep.claim_checks] == [ClaimSupport.CANNOT_DETERMINE]
    assert deep.claim_checks[0].mode == "none"
    assert checker.calls == 1
    assert report.summary.claims_checked == 3 and report.summary.claims_not_supported == 1
    assert report.summary.flagged == 1
    assert attention.explanation is not None
    assert "does not support the sentence" in attention.explanation.recommendation
    assert "No action needed" not in attention.explanation.recommendation


async def test_single_citation_claim_option(make_sources: Callable[..., SourceSet]) -> None:
    services = LLMServices(claim_checker=FakeChecker())
    settings = Settings(cache_backend="none", groq_api_key=None)
    sources = make_sources(with_abstracts([ATTENTION, DEEP_LEARNING, BERT]))
    async with Engine(settings, llm=services, sources=sources, cache=NullCache()) as engine:
        report = await engine.check(
            "citation",
            "Vaswani, A., & Shazeer, N. (2017). Attention Is All You Need. NeurIPS.",
            options=CheckOptions(claim=UNSUPPORTED, suggest_alternatives=False),
        )
        no_llm = await engine.check(
            "citation",
            "Vaswani, A. (2017). Attention Is All You Need. NeurIPS.",
            options=CheckOptions(claim=UNSUPPORTED, use_llm=False),
        )
    [c] = report.citations
    assert [x.label for x in c.claim_checks] == [ClaimSupport.NOT_SUPPORTED]
    assert no_llm.citations[0].claim_checks == []
    assert any("Claim checks need the LLM" in w for w in no_llm.warnings)


def test_exports_show_claim_checks_escaped(make_sources: Callable[..., SourceSet]) -> None:
    from citeguard.domain.models import CitationResult, ParsedReference

    r = CitationResult(
        index=0,
        reference=ParsedReference(raw="ref", title="t"),
        verdict=Verdict.VERIFIED,
        claim_checks=[
            ClaimCheck(
                claim="<script>alert(1)</script> claim",
                label=ClaimSupport.NOT_SUPPORTED,
                rationale="Different topic.",
                quote="On mice.",
                abstract_url="javascript:alert(1)",
            )
        ],
    )
    html = to_html({"input_kind": "text"}, [r])
    assert "Not supported" in html and "&lt;script&gt;" in html and "<script>alert" not in html
    assert "javascript:" not in html
    assert "NOT_SUPPORTED" in to_csv([r])


async def test_reranker_choosing_none_is_respected(make_sources: Callable[..., SourceSet]) -> None:
    from citeguard.domain.models import CitationResult, ParsedReference
    from citeguard.suggest.alternatives import alternatives

    class Picks:
        def __init__(self, answer: list[tuple[Record, str]] | None) -> None:
            self.answer = answer

        async def rerank(
            self, ref: ParsedReference, candidates: list[Record], k: int
        ) -> tuple[list[tuple[Record, str]] | None, LLMUsage]:
            return self.answer, LLMUsage(calls=1)

    fake = CitationResult(
        index=0,
        reference=ParsedReference(raw="r", title="Deep belief nets learning algorithm fast"),
        verdict=Verdict.FABRICATED,
    )
    sources = make_sources()
    none_fit, _ = await alternatives(sources, fake, ["apa"], reranker=Picks([]))
    assert none_fit == []  # the LLM said no candidate supports the claim: show nothing
    failed, _ = await alternatives(sources, fake, ["apa"], reranker=Picks(None))
    assert failed and all(s.method == "keyword" for s in failed)  # LLM down: keyword fallback


def test_conclusion_claim_drops_lead_ins() -> None:
    from citeguard.eval.claims import conclusion_claim

    abstract = (
        "Background sentence that sets the scene for the study. We measured things in many "
        "patients across sites. These results suggest that early screening reduces mortality in "
        "adults over sixty."
    )
    assert (
        conclusion_claim(abstract) == "Early screening reduces mortality in adults over sixty [1]."
    )
    assert conclusion_claim("Too short.") is None
    tail = " Trial registration ANZCTR ACTRN12619001649101 registered on the first of May."
    assert conclusion_claim(abstract + tail) == conclusion_claim(abstract)
