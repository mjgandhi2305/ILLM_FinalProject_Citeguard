"""Verifier + rules against an in-memory corpus: one test per verdict path."""

from collections.abc import Callable

from citeguard.domain.models import (
    Author,
    CitationType,
    DiscrepancyCode,
    Flag,
    Identifiers,
    ParsedReference,
    Record,
    Severity,
    Verdict,
)
from citeguard.explain.templates import template_explanation
from citeguard.sources.registry import SourceSet
from citeguard.suggest.corrections import correction
from citeguard.verify.verifier import Verifier


def ref(
    title: str,
    authors: list[str],
    year: int,
    venue: str | None = None,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    rtype: CitationType = CitationType.ARTICLE_JOURNAL,
    **kw: object,
) -> ParsedReference:
    return ParsedReference(
        raw=f"{', '.join(authors)} ({year}). {title}. {venue or ''}",
        title=title,
        authors=[
            Author(family=a.split()[-1], given=" ".join(a.split()[:-1]) or None) for a in authors
        ],
        year=year,
        container_title=venue,
        type=rtype,
        ids=Identifiers(doi=doi, arxiv_id=arxiv_id),
        parse_method="structured",
        parse_confidence=1.0,
        **kw,  # type: ignore[arg-type]
    )


async def test_verified(make_sources: Callable[..., SourceSet]) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "Attention is all you need",
            ["Ashish Vaswani", "Noam Shazeer"],
            2017,
            "NeurIPS",
            rtype=CitationType.PAPER_CONFERENCE,
            authors_truncated=True,
        ),
        0,
    )
    assert r.verdict == Verdict.VERIFIED
    assert r.confidence > 0.9
    assert "Verified" in template_explanation(r).headline


async def test_verified_via_doi_skips_search(make_sources: Callable[..., SourceSet]) -> None:
    sources = make_sources()
    r = await Verifier(sources).verify(
        ref(
            "Deep learning",
            ["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"],
            2015,
            "Nature",
            doi="10.1038/nature14539",
        ),
        0,
    )
    assert r.verdict == Verdict.VERIFIED
    assert not any(c.startswith("search") for c in sources.by_name["crossref"].calls)  # type: ignore[attr-defined]


async def test_verified_with_errors(make_sources: Callable[..., SourceSet]) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "Deep learning",
            ["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"],
            2018,
            "Nature",
            volume="520",
        ),
        0,
    )
    assert r.verdict == Verdict.VERIFIED_WITH_ERRORS
    codes = {d.code for d in r.discrepancies}
    assert DiscrepancyCode.YEAR_MISMATCH in codes
    assert DiscrepancyCode.VOLUME_ISSUE_PAGES_MISMATCH in codes
    fix = correction(r, ["apa"])
    assert fix is not None and "2015" in fix.formatted["apa"]


async def test_misattributed_and_chimeric(make_sources: Callable[..., SourceSet]) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "Attention is all you need",
            ["Geoffrey Hinton", "Simon Osindero"],
            2017,
            "NeurIPS",
            rtype=CitationType.PAPER_CONFERENCE,
        ),
        0,
    )
    assert r.verdict == Verdict.MISATTRIBUTED
    codes = {d.code for d in r.discrepancies}
    assert DiscrepancyCode.AUTHORS_FABRICATED in codes
    assert DiscrepancyCode.CHIMERIC_TITLE_AUTHORS in codes


async def test_fabricated_with_borrowed_doi(make_sources: Callable[..., SourceSet]) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "Contrastive graph transformers for protein folding dynamics",
            ["John Smith", "Kevin Lee"],
            2021,
            "Nature Machine Intelligence",
            doi="10.1038/nature14539",
        ),
        0,
    )
    assert r.verdict == Verdict.FABRICATED
    assert r.confidence >= 0.9
    assert any(d.code == DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK for d in r.discrepancies)
    assert "Deep learning" in template_explanation(r).reasons[0].text


async def test_fabricated_unregistered_doi(make_sources: Callable[..., SourceSet]) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "Quantum attention for low-resource translation",
            ["Priya Kumar"],
            2023,
            "ACL",
            doi="10.18653/v1/2023.acl-long.9999",
            rtype=CitationType.PAPER_CONFERENCE,
        ),
        0,
    )
    assert r.verdict == Verdict.FABRICATED
    assert any(d.code == DiscrepancyCode.ID_NOT_REGISTERED for d in r.discrepancies)


async def test_wrong_doi_on_real_paper_is_misattributed(
    make_sources: Callable[..., SourceSet],
) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "Attention is all you need",
            ["Ashish Vaswani", "Noam Shazeer"],
            2017,
            "NeurIPS",
            doi="10.1038/nature14539",
            rtype=CitationType.PAPER_CONFERENCE,
            authors_truncated=True,
        ),
        0,
    )
    assert r.verdict == Verdict.MISATTRIBUTED
    assert any(
        d.code == DiscrepancyCode.ID_RESOLVES_TO_DIFFERENT_WORK and d.severity == "critical"
        for d in r.discrepancies
    )


async def test_unverifiable_when_sources_down(make_sources: Callable[..., SourceSet]) -> None:
    sources = make_sources(down=("crossref", "openalex", "semantic_scholar"))
    r = await Verifier(sources).verify(
        ref("Some real but unindexed paper on topic", ["Ann Author"], 2020, "Journal of Things"), 0
    )
    assert r.verdict == Verdict.UNVERIFIABLE
    assert Flag.SOURCES_DEGRADED in r.flags


async def test_book_not_found_is_unverifiable(make_sources: Callable[..., SourceSet]) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "A history of obscure regional printing presses",
            ["Ann Author"],
            1987,
            None,
            rtype=CitationType.BOOK,
        ),
        0,
    )
    assert r.verdict == Verdict.UNVERIFIABLE


async def test_retracted_flag(make_sources: Callable[..., SourceSet]) -> None:
    r = await Verifier(make_sources()).verify(
        ref(
            "Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental "
            "disorder in children",
            ["Andrew Wakefield", "Simon Murch"],
            1998,
            "Lancet",
        ),
        0,
    )
    assert Flag.RETRACTED in r.flags
    assert "retracted" in template_explanation(r).recommendation.lower()


async def test_off_by_one_year_is_an_error_when_sources_agree(
    make_sources: Callable[..., SourceSet],
) -> None:
    r = await Verifier(make_sources()).verify(
        ref("Deep learning", ["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"], 2016, "Nature"), 0
    )
    year = next(d for d in r.discrepancies if d.code == DiscrepancyCode.YEAR_MISMATCH)
    assert year.severity == "minor" and r.verdict == Verdict.VERIFIED_WITH_ERRORS


async def test_late_redeposit_is_not_a_year_error(make_sources: Callable[..., SourceSet]) -> None:
    from tests.conftest import rec

    copy = rec(
        "Attention Is All You Need",
        ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        2025,
        None,
        doi="10.65215/abc123",
        rtype=CitationType.PREPRINT,
    )
    sources = make_sources([copy], down=("openalex", "semantic_scholar"))
    r = await Verifier(sources).verify(
        ref(
            "Attention is all you need",
            ["Ashish Vaswani", "Noam Shazeer"],
            2017,
            "NeurIPS",
            rtype=CitationType.PAPER_CONFERENCE,
            authors_truncated=True,
        ),
        0,
    )
    year = next(d for d in r.discrepancies if d.code == DiscrepancyCode.YEAR_MISMATCH)
    assert year.severity == "info" and "later copy" in year.message
    assert r.verdict == Verdict.VERIFIED and r.confidence <= 0.75
    assert Flag.SOURCES_DEGRADED in r.flags


async def test_redeposit_template_does_not_claim_year_match(
    make_sources: Callable[..., SourceSet],
) -> None:
    from tests.conftest import rec

    copy = rec(
        "Attention Is All You Need",
        ["Ashish Vaswani", "Noam Shazeer"],
        2025,
        None,
        doi="10.65215/abc123",
        rtype=CitationType.PREPRINT,
    )
    r = await Verifier(make_sources([copy])).verify(
        ref(
            "Attention is all you need",
            ["Ashish Vaswani", "Noam Shazeer"],
            2017,
            "NeurIPS",
            rtype=CitationType.PAPER_CONFERENCE,
        ),
        0,
    )
    expl = template_explanation(r)
    assert "could not be confirmed" in expl.headline
    assert "title and authors match" in expl.reasons[0].text


def _misparsed(raw: str, bad_title: str, doi: str | None = None) -> ParsedReference:
    """What the heuristic parser produced before it could read names like "Van Tinteren H"."""
    return ParsedReference(
        raw=raw,
        title=bad_title,
        authors=[Author(family="Hinton", given="G")],
        year=2006,
        container_title=None,
        ids=Identifiers(doi=doi),
        parse_method="heuristic",
        parse_confidence=0.7,
    )


async def test_misparsed_citation_is_reparsed_via_its_doi(
    make_sources: Callable[..., SourceSet],
) -> None:
    raw = (
        "Hinton GE, Osindero S, Teh YW, et al. A fast learning algorithm for deep belief "
        "nets. Neural Computation. 2006;18(7):1527-1554. doi:10.1162/neco.2006.18.7.1527"
    )
    r = await Verifier(make_sources()).verify(
        _misparsed(raw, "Teh YW, et al", doi="10.1162/neco.2006.18.7.1527"), 0
    )
    assert r.verdict == Verdict.VERIFIED
    assert r.reference.title == "A fast learning algorithm for deep belief nets"


async def test_misparsed_citation_is_reparsed_via_a_whole_string_search(
    make_sources: Callable[..., SourceSet],
) -> None:
    raw = (
        "Hinton GE, Osindero S, Teh YW. A fast learning algorithm for deep belief nets. "
        "Neural Computation. 2006;18(7):1527-1554."
    )
    sources = make_sources()
    r = await Verifier(sources).verify(_misparsed(raw, "Teh YW"), 0)
    assert r.verdict == Verdict.VERIFIED
    crossref = sources.get("crossref")
    assert crossref is not None and any("Neural Computation" in c for c in crossref.calls)  # type: ignore[attr-defined]


async def test_extended_real_title_is_not_rescued(make_sources: Callable[..., SourceSet]) -> None:
    # A hallucination that borrows a real title and first author must stay fake.
    raw = (
        "Vaswani A, Shazeer N. Attention Is All You Need for protein structure prediction. "
        "Nature. 2021;590(7):1-9."
    )
    bad = _misparsed(raw, "Attention Is All You Need for protein structure prediction")
    r = await Verifier(make_sources()).verify(bad, 0)
    assert r.reference.title == bad.title
    assert r.verdict not in (Verdict.VERIFIED, Verdict.VERIFIED_WITH_ERRORS)


async def test_incomplete_author_list_is_a_note_not_misattribution(
    make_sources: Callable[..., SourceSet],
) -> None:
    # BibTeX listing only the first of four authors, without "and others" (F1 would be 0.4)
    r = await Verifier(make_sources()).verify(
        ref(
            "Attention Is All You Need",
            ["Ashish Vaswani"],
            2017,
            "Advances in Neural Information Processing Systems",
            rtype=CitationType.PAPER_CONFERENCE,
        ),
        0,
    )
    assert r.verdict == Verdict.VERIFIED
    codes = {d.code: d.severity for d in r.discrepancies}
    assert DiscrepancyCode.AUTHORS_FABRICATED not in codes
    assert codes.get(DiscrepancyCode.AUTHORS_MISSING) == Severity.INFO


async def test_one_shared_surname_is_not_a_chimera(make_sources: Callable[..., SourceSet]) -> None:
    from tests.conftest import ATTENTION, rec

    # A fuzzy author search returns an unrelated paper by someone else called Vaswani.
    unrelated = rec(
        "A rewarding introduction to global bioethics", ["Rita Vaswani"], 2017, "Bioethics"
    )
    r = await Verifier(make_sources([ATTENTION, unrelated]), chimera_check=True).verify(
        ref(
            "Attention Is All You Need",
            ["Ashish Vaswani", "Geoffrey Hinton"],
            2017,
            "NeurIPS",
            rtype=CitationType.PAPER_CONFERENCE,
        ),
        0,
    )
    assert DiscrepancyCode.CHIMERIC_TITLE_AUTHORS not in {d.code for d in r.discrepancies}


def _split_sources(per_source: dict[str, list[Record]]) -> SourceSet:
    from tests.conftest import FakeDoi, FakeSource

    by_name = {name: FakeSource(name, recs) for name, recs in per_source.items()}
    return SourceSet(doi=FakeDoi({}), by_name=by_name)  # type: ignore[arg-type]


CJK_PAPER = "Analysis of the Clinical Features and Risk Factors of Primary Biliary Cholangitis"


async def test_too_many_authors_for_a_native_script_paper_is_misattributed() -> None:
    from tests.conftest import rec

    paper = rec(CJK_PAPER, ["怡飞 杨"], 2022, "Advances in Clinical Medicine")
    sources = _split_sources({"crossref": [paper], "openalex": [paper], "semantic_scholar": []})
    swapped = await Verifier(sources).verify(
        ref(CJK_PAPER, ["L Sze", "C Cheung", "C Leung"], 2022, "Advances in Clinical Medicine"), 0
    )
    assert swapped.verdict == Verdict.MISATTRIBUTED
    # A correct romanised citation of the same paper cannot be judged by spelling: not fake.
    romanised = await Verifier(sources).verify(
        ref(CJK_PAPER, ["Yifei Yang"], 2022, "Advances in Clinical Medicine"), 0
    )
    assert romanised.verdict == Verdict.VERIFIED


async def test_publisher_listed_as_author_by_one_source_is_not_an_error() -> None:
    from tests.conftest import rec

    title = "A study on the mediating effect of social support among international students"
    crossref = rec(title, ["Korean Academy of Multicultural Welfare", "Sun Ah Paik"], 2023, "Bokji")
    openalex = rec(title, ["Sun Ah Paik"], 2023, "Bokji", source="openalex")
    sources = _split_sources(
        {"crossref": [crossref], "openalex": [openalex], "semantic_scholar": []}
    )
    r = await Verifier(sources).verify(ref(title, ["S. A. Paik"], 2023, "Bokji"), 0)
    assert r.verdict == Verdict.VERIFIED
    assert DiscrepancyCode.AUTHORS_REORDERED not in {d.code for d in r.discrepancies}
