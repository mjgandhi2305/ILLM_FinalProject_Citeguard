"""LLM layer against a mocked Groq endpoint: schemas, fallbacks, caching and grounding guards."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import groq
import httpx
import pytest
import respx

from citeguard.config import Settings
from citeguard.domain.models import (
    Author,
    CheckOptions,
    CitationResult,
    CitationType,
    Identifiers,
    ParsedReference,
    Verdict,
)
from citeguard.engine import Engine, LLMServices
from citeguard.llm.client import GroqLLM, StageConfig
from citeguard.llm.limiter import ModelLimiter
from citeguard.llm.schema import strict_schema
from citeguard.llm.services import (
    LLMAdjudicator,
    LLMExplainer,
    LLMReferenceParser,
    LLMReformulator,
    _ParseBatch,
)
from citeguard.sources.infra import MemoryCache, NullCache
from citeguard.sources.registry import SourceSet
from citeguard.verify.verifier import Verifier

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def completion(payload: dict[str, Any], model: str = "openai/gpt-oss-20b") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(payload)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
        },
        headers={"x-ratelimit-remaining-tokens": "7000"},
    )


def make_llm(cache: Any = None, fallbacks: list[str] | None = None) -> GroqLLM:
    client = groq.AsyncGroq(api_key="test-key", max_retries=0)
    return GroqLLM(
        client,
        ModelLimiter(rpm=10_000, tpm=10_000_000, tpd=10_000_000),
        cache=cache or NullCache(),
        fallback_models=fallbacks or [],
    )


STAGE = StageConfig("openai/gpt-oss-20b", "low", 1000)


def test_strict_schema_shape() -> None:
    schema = strict_schema(_ParseBatch)
    ref = schema["$defs"]["_RefOut"]
    assert ref["additionalProperties"] is False
    assert set(ref["required"]) == set(ref["properties"])
    assert {"type": "null"} in ref["properties"]["doi"]["anyOf"]
    assert "default" not in json.dumps(schema) and "title" not in ref["properties"]["doi"]


@respx.mock
async def test_parser_keeps_only_faithful_fields() -> None:
    raw = "Smith, J. (2021). Graph transformers for proteins. Nature Machine Intelligence, 3, 1-9."
    respx.post(GROQ_URL).mock(
        return_value=completion(
            {
                "references": [
                    {
                        "index": 0,
                        "title": "Graph transformers for proteins",
                        "authors": [
                            {"family": "Smith", "given": "J."},
                            {"family": "Invented", "given": "X."},
                        ],
                        "authors_truncated": False,
                        "container_title": "Nature Machine Intelligence",
                        "year": 2021,
                        "volume": "3",
                        "issue": None,
                        "pages": "1-9",
                        "publisher": None,
                        "type": "article-journal",
                        "doi": "10.1038/s42256-021-00001-1",  # hallucinated: not in raw text
                        "arxiv_id": None,
                        "pmid": None,
                        "isbn": None,
                        "url": None,
                    },
                    {
                        "index": 1,
                        "title": "A completely rewritten title",
                        "authors": [],
                        "authors_truncated": False,
                        "container_title": None,
                        "year": None,
                        "volume": None,
                        "issue": None,
                        "pages": None,
                        "publisher": None,
                        "type": "unknown",
                        "doi": None,
                        "arxiv_id": None,
                        "pmid": None,
                        "isbn": None,
                        "url": None,
                    },
                ]
            }
        )
    )
    parser = LLMReferenceParser(make_llm(), STAGE)
    refs, usage = await parser.parse([raw, "Doe (2020). Original title here. Journal."])
    assert usage.calls == 1
    first = refs[0]
    assert first is not None
    assert first.ids.doi is None  # invented DOI dropped
    assert [a.family for a in first.authors] == ["Smith"]  # invented author dropped
    assert first.parse_method == "llm" and first.type == CitationType.ARTICLE_JOURNAL
    assert refs[1] is None  # unfaithful title → caller falls back to heuristic parse


@respx.mock
async def test_fallback_model_on_rate_limit_and_cache() -> None:
    route = respx.post(GROQ_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": {"message": "rate"}}, headers={"retry-after": "1"}),
            completion({"queries": []}, model="openai/gpt-oss-120b"),
        ]
    )
    llm = make_llm(cache=MemoryCache(), fallbacks=["openai/gpt-oss-120b"])
    ref = ParsedReference(raw="x", title="Some title of a paper", authors=[Author(family="Doe")])
    reform = LLMReformulator(llm, STAGE)
    queries, usage = await reform.reformulate(ref, [])
    assert queries == [] and usage.failures == 1 and usage.calls == 1
    models = [json.loads(c.request.content)["model"] for c in route.calls]
    assert models == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    body = json.loads(route.calls[1].request.content)
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["include_reasoning"] is False and body["reasoning_effort"] == "low"
    # second identical call is served from cache: no new HTTP request
    _, usage2 = await reform.reformulate(ref, [])
    assert usage2.cached_calls == 1 and route.call_count == 2


@respx.mock
async def test_adjudicator_cannot_pick_unknown_candidate(
    make_sources: Callable[..., SourceSet],
) -> None:
    from tests.conftest import ATTENTION

    respx.post(GROQ_URL).mock(
        return_value=completion(
            {"decision": "match", "candidate_id": "c9", "confidence": 0.9, "rationale": "x"}
        )
    )
    from citeguard.match.linkage import DEFAULT_MODEL, compute_features

    ref = ParsedReference(raw="r", title="Attention is all you need", year=2017)
    feats = compute_features(ref, ATTENTION)
    from citeguard.domain.models import Candidate

    cand = Candidate(
        record=ATTENTION,
        features=feats,
        probability=DEFAULT_MODEL.probability(feats),
        evidence_id="ev1",
    )
    outcome = await LLMAdjudicator(make_llm(), STAGE).adjudicate(ref, [cand])
    assert outcome is not None and outcome.chosen is None and not outcome.rejected_all


def _fabricated_result() -> CitationResult:
    from citeguard.domain.models import (
        Discrepancy,
        DiscrepancyCode,
        Evidence,
        LookupStatus,
        Severity,
    )

    ref = ParsedReference(
        raw="Smith, J. (2021). Contrastive Graph Transformers. Nature Machine Intelligence.",
        title="Contrastive Graph Transformers",
        authors=[Author(family="Smith", given="J.")],
        year=2021,
        container_title="Nature Machine Intelligence",
        ids=Identifiers(doi="10.1038/nature14539"),
    )
    return CitationResult(
        index=0,
        reference=ref,
        verdict=Verdict.FABRICATED,
        confidence=0.97,
        discrepancies=[
            Discrepancy(
                code=DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK,
                severity=Severity.CRITICAL,
                field="doi",
                message='The DOI is real but belongs to "Deep learning" by LeCun (2015)',
                evidence_ids=["ev1"],
            )
        ],
        evidence=[
            Evidence(
                id="ev1", source="doi", operation="registry", query="doi", status=LookupStatus.FOUND
            ),
            Evidence(
                id="ev2",
                source="crossref",
                operation="search",
                query="q",
                status=LookupStatus.NOT_FOUND,
            ),
        ],
    )


GOOD_EXPLANATION = {
    "verdict_echo": "FABRICATED",
    "headline": "Likely fabricated: the DOI belongs to another paper and the title is in no index.",
    "reasons": [
        {
            "text": 'The DOI resolves to "Deep learning" by LeCun (2015), not this title.',
            "evidence_ids": ["ev1"],
        },
        {"text": "Crossref has no record with this title.", "evidence_ids": ["ev2"]},
    ],
    "recommendation": "Remove or replace this reference.",
}


@respx.mock
async def test_explainer_retries_then_accepts_grounded_answer() -> None:
    bad = {
        **GOOD_EXPLANATION,
        "reasons": [
            {
                "text": 'It was actually "Protein Folding Transformers" (2019).',
                "evidence_ids": ["ev7"],
            }
        ],
    }
    route = respx.post(GROQ_URL).mock(side_effect=[completion(bad), completion(GOOD_EXPLANATION)])
    expl, usage = await LLMExplainer(make_llm(), STAGE).explain(_fabricated_result())
    assert expl is not None and expl.mode == "llm"
    assert expl.headline.startswith("Likely fabricated")
    assert usage.failures == 1 and route.call_count == 2
    retry_prompt = json.loads(route.calls[1].request.content)["messages"][1]["content"]
    assert "unknown evidence id 'ev7'" in retry_prompt


@respx.mock
async def test_explainer_rejects_verdict_contradiction() -> None:
    contradicting = {**GOOD_EXPLANATION, "verdict_echo": "VERIFIED"}
    respx.post(GROQ_URL).mock(return_value=completion(contradicting))
    expl, _ = await LLMExplainer(make_llm(), STAGE).explain(_fabricated_result())
    assert expl is None  # caller keeps the template explanation


@respx.mock
async def test_explainer_rejects_a_headline_that_is_only_the_label() -> None:
    empty = {**GOOD_EXPLANATION, "headline": "Likely fabricated:"}
    route = respx.post(GROQ_URL).mock(side_effect=[completion(empty), completion(GOOD_EXPLANATION)])
    expl, _ = await LLMExplainer(make_llm(), STAGE).explain(_fabricated_result())
    assert expl is not None and expl.headline != "Likely fabricated:"
    retry_prompt = json.loads(route.calls[1].request.content)["messages"][1]["content"]
    assert "main finding" in retry_prompt


@respx.mock
async def test_engine_with_llm_never_fails_when_groq_is_down(
    make_sources: Callable[..., SourceSet],
) -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(503))
    llm = make_llm()
    services = LLMServices(
        parser=LLMReferenceParser(llm, STAGE),
        adjudicator=LLMAdjudicator(llm, STAGE),
        reformulator=LLMReformulator(llm, STAGE),
        explainer=LLMExplainer(llm, STAGE),
    )
    settings = Settings(cache_backend="none", groq_api_key=None)
    bib = """@article{x, title={Deep learning}, author={LeCun, Yann and Bengio, Yoshua},
    journal={Nature}, year={2015}}
    @article{y, title={Holographic sparse attention for tidal energy forecasting},
    author={Nobody, Ann}, journal={Energy Letters}, year={2022}}"""
    async with Engine(settings, llm=services, sources=make_sources(), cache=NullCache()) as engine:
        report = await engine.check("bibtex", bib, options=CheckOptions(suggest_alternatives=False))
    verdicts = [c.verdict for c in report.citations]
    assert verdicts == [Verdict.VERIFIED, Verdict.FABRICATED]
    assert all(c.explanation and c.explanation.mode == "template" for c in report.citations)
    assert report.summary.llm_usage.failures > 0


async def test_reformulation_is_bounded(make_sources: Callable[..., SourceSet]) -> None:
    from citeguard.domain.models import LLMUsage
    from citeguard.sources.base import SearchQuery

    class EightQueries:
        async def reformulate(self, ref: Any, closest: Any) -> tuple[list[SearchQuery], LLMUsage]:
            return [SearchQuery(title=f"variant {i}") for i in range(8)], LLMUsage(calls=1)

    sources = make_sources()
    ref = ParsedReference(
        raw="r",
        title="Unfindable imaginary title of nothing",
        year=2020,
        container_title="Journal",
        type=CitationType.ARTICLE_JOURNAL,
    )
    result = await Verifier(sources, reformulator=EightQueries()).verify(ref, 0)
    searches = [c for c in sources.by_name["openalex"].calls if "variant" in c]  # type: ignore[attr-defined]
    assert len(searches) == 4
    assert result.verdict == Verdict.FABRICATED and result.llm_usage.calls == 1


@pytest.mark.live
async def test_live_groq_parse() -> None:  # pragma: no cover - needs GROQ_API_KEY
    from citeguard.config import get_settings
    from citeguard.llm.services import build_llm_services

    settings = get_settings()
    if not settings.llm_available:
        pytest.skip("GROQ_API_KEY not configured")
    services = build_llm_services(settings, NullCache())
    assert services.parser is not None
    refs, usage = await services.parser.parse(
        ["Vaswani A, et al. Attention is all you need. NeurIPS 2017."]
    )
    assert refs[0] is not None and refs[0].title and "attention" in refs[0].title.lower()
    assert usage.calls == 1


def test_headline_prefix_always_matches_verdict() -> None:
    from citeguard.llm.services import _with_verdict_prefix

    assert (
        _with_verdict_prefix(
            "Verified: real paper with minor citation errors.", Verdict.VERIFIED_WITH_ERRORS
        )
        == "Real paper with errors: real paper with minor citation errors."
    )
    assert _with_verdict_prefix("The DOI belongs to another paper.", Verdict.FABRICATED).startswith(
        "Likely fabricated: the DOI"
    )


def test_headline_must_not_call_a_non_fabricated_citation_fake() -> None:
    from citeguard.explain.bundle import verdict_contradictions

    assert verdict_contradictions(
        "Could not verify: citation appears fabricated.", Verdict.UNVERIFIABLE
    )
    assert verdict_contradictions("Real paper, but the year is wrong.", Verdict.VERIFIED) == []
    assert (
        verdict_contradictions("No such paper exists; likely fabricated.", Verdict.FABRICATED) == []
    )


@respx.mock
async def test_malformed_output_is_retried_on_the_same_model() -> None:
    invalid = httpx.Response(
        400,
        json={
            "error": {
                "message": "Generated JSON does not match the expected schema.",
                "type": "invalid_request_error",
                "code": "json_validate_failed",
                "failed_generation": "",
            }
        },
    )
    good = {"queries": [{"title": "Deep learning", "keywords": None, "author": "LeCun"}]}
    route = respx.post(GROQ_URL).mock(side_effect=[invalid, completion(good)])
    from citeguard.llm.services import _Queries

    out, usage = await make_llm(fallbacks=["openai/gpt-oss-120b"]).structured(
        STAGE, "sys", "user", _Queries
    )
    assert out is not None and usage.failures == 1
    models = [json.loads(c.request.content)["model"] for c in route.calls]
    assert models == ["openai/gpt-oss-20b", "openai/gpt-oss-20b"]  # same model, then success
