import pytest

from citeguard.domain.models import Author, ParsedReference
from citeguard.match.linkage import DEFAULT_MODEL, compute_features
from citeguard.match.names import compare_authors, parse_name, split_author_list
from citeguard.match.normalize import title_similarity
from citeguard.match.venues import canonical_venue, venue_similarity
from tests.conftest import ATTENTION


@pytest.mark.parametrize(
    ("raw", "family", "given"),
    [
        ("Vaswani, Ashish", "Vaswani", "Ashish"),
        ("A. Vaswani", "Vaswani", "A."),
        ("Ashish Vaswani", "Vaswani", "Ashish"),
        ("Laurens van der Maaten", "van der Maaten", "Laurens"),
        ("LeCun Y", "LeCun", "Y"),
        ("Wei Wang 0001", "Wang", "Wei"),
        ("Martin Luther King Jr.", "King", "Martin Luther"),
    ],
)
def test_parse_name(raw: str, family: str, given: str) -> None:
    a = parse_name(raw)
    assert a is not None
    assert (a.family, a.given) == (family, given)


def test_split_author_lists() -> None:
    apa, _ = split_author_list("Vaswani, A., Shazeer, N., Kaiser, Ł., & Polosukhin, I.")
    assert [a.family for a in apa] == ["Vaswani", "Shazeer", "Kaiser", "Polosukhin"]
    ieee, _ = split_author_list("A. Vaswani, N. Shazeer, and N. Parmar")
    assert [a.family for a in ieee] == ["Vaswani", "Shazeer", "Parmar"]
    van, _ = split_author_list("LeCun Y, Bengio Y, Hinton G")
    assert [a.family for a in van] == ["LeCun", "Bengio", "Hinton"]
    etal, truncated = split_author_list("Brown, T. et al.")
    assert truncated and etal[0].family == "Brown"


def test_compare_authors() -> None:
    claimed = [Author(family="Vaswani"), Author(family="Shazeer")]
    actual = ATTENTION.authors
    c = compare_authors(claimed, actual, claimed_truncated=True)
    assert c.first_author_match is True and c.f1 == 1.0
    wrong = compare_authors([Author(family="Hinton"), Author(family="LeCun")], actual)
    assert wrong.f1 == 0.0 and wrong.first_author_match is False
    swapped = compare_authors(
        [Author(family="Wei", given="Zhang")], [Author(family="Zhang", given="Wei")]
    )
    assert swapped.f1 == 1.0


def test_title_similarity() -> None:
    assert title_similarity("Attention is all you need", "Attention Is All You Need.") == 1.0
    assert title_similarity("{BERT}: Pre-training", "BERT: Pre-training") == 1.0
    assert title_similarity("Attention", "Attention is all you need") < 0.6
    assert (
        title_similarity(
            "Deep residual learning for image recognition",
            "Deep Residual Learning for Image Recognition: a study of ResNets",
        )
        >= 0.95
    )


def test_venues() -> None:
    assert canonical_venue("Proc. NeurIPS") == "neurips"
    assert canonical_venue("Advances in Neural Information Processing Systems 30") == "neurips"
    assert venue_similarity("NIPS", "Neural Information Processing Systems") == 1.0
    assert venue_similarity("ICML", "NeurIPS") == 0.0
    assert venue_similarity("Nat. Mach. Intell.", "Nature Machine Intelligence") == 0.9
    assert venue_similarity("arXiv", "NeurIPS") is None  # preprint vs venue: not comparable


def test_linkage_probabilities() -> None:
    good = ParsedReference(
        raw="",
        title="Attention is all you need",
        authors=[Author(family="Vaswani")],
        authors_truncated=True,
        year=2017,
        container_title="NeurIPS",
    )
    p_good = DEFAULT_MODEL.probability(compute_features(good, ATTENTION))
    assert p_good > 0.99
    unrelated = good.model_copy(update={"title": "Graph neural networks for chemistry"})
    assert DEFAULT_MODEL.probability(compute_features(unrelated, ATTENTION)) < 0.3


def test_repository_venues_are_preprints() -> None:
    from citeguard.match.venues import is_preprint_venue

    for name in (
        "arXiv (Cornell University)",
        "bioRxiv (Cold Spring Harbor Laboratory)",
        "Zenodo (CERN European Organization for Nuclear Research)",
        "SSRN Electronic Journal",
    ):
        assert is_preprint_venue(name), name
    assert not is_preprint_venue("Nature")
    assert (
        venue_similarity(
            "Advances in Neural Information Processing Systems", "arXiv (Cornell University)"
        )
        is None
    )


def test_non_latin_names() -> None:
    native = [Author(family="杨", given="怡")]
    assert compare_authors(native, [Author(family="杨", given="怡")]).f1 == 1.0
    # native script vs transliteration: unknown, not "different"
    translit = compare_authors(native, [Author(family="Yang", given="Yi")])
    assert translit.f1 is None and translit.first_author_match is None
    armenian = [Author(family="Խաչատրյան", given="Նարինե")]
    assert compare_authors(armenian, armenian).f1 == 1.0


def test_cjk_name_order() -> None:
    a = parse_name("杨 怡")
    assert a is not None and (a.family, a.given) == ("杨", "怡")
    assert compare_authors([a], [Author(family="杨", given="怡飞")]).first_author_match is True


def test_cjk_western_order_from_openalex() -> None:
    crossref_style = parse_name("杨 怡")
    openalex_style = parse_name("怡飞 杨")  # OpenAlex shows CJK names given-first
    assert crossref_style and openalex_style
    assert compare_authors([crossref_style], [openalex_style]).f1 == 1.0
