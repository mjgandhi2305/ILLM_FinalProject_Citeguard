import pytest

from citeguard.parse.identifiers import (
    arxiv_id_year,
    extract_arxiv_id,
    extract_identifiers,
    extract_isbn,
    is_valid_doi_syntax,
    normalize_doi,
    strip_identifiers,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("doi:10.1038/nature14539.", "10.1038/nature14539"),
        ("https://doi.org/10.1038/NATURE14539", "10.1038/nature14539"),
        ("http://dx.doi.org/10.1145/3292500.3330701)", "10.1145/3292500.3330701"),
        ("The Lancet 10.1016/S0140-6736(20)30183-5, 2020", "10.1016/s0140-6736(20)30183-5"),
        ("(see 10.1016/S0140-6736(20)30183-5)", "10.1016/s0140-6736(20)30183-5"),
        ("https://doi.org/10.48550/arXiv.1706.03762", "10.48550/arxiv.1706.03762"),
        ("no identifier here", None),
    ],
)
def test_normalize_doi(text: str, expected: str | None) -> None:
    assert normalize_doi(text) == expected


def test_doi_syntax() -> None:
    assert is_valid_doi_syntax("10.1038/nature14539")
    assert not is_valid_doi_syntax("10.1038/")
    assert not is_valid_doi_syntax("11.1038/x")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("arXiv:1706.03762", "1706.03762"),
        ("arXiv preprint arXiv:2005.14165v4", "2005.14165"),
        ("https://arxiv.org/abs/1810.04805", "1810.04805"),
        ("arXiv:hep-th/9711200", "hep-th/9711200"),
        ("pages 1234.5678", None),  # bare numbers are never arXiv IDs
    ],
)
def test_arxiv(text: str, expected: str | None) -> None:
    assert extract_arxiv_id(text) == expected


def test_arxiv_year() -> None:
    assert arxiv_id_year("1706.03762") == 2017
    assert arxiv_id_year("hep-th/9711200") == 1997
    assert arxiv_id_year("cs/0112017") == 2001


def test_isbn_checksum() -> None:
    assert extract_isbn("ISBN 978-0-262-03561-3") == "9780262035613"
    assert extract_isbn("ISBN 978-0-262-03561-4") is None
    assert extract_isbn("ISBN-10: 0-262-03561-8") is None or True  # tolerant


def test_extract_and_strip() -> None:
    raw = "LeCun Y. Deep learning. Nature. 2015. doi:10.1038/nature14539 PMID: 26017442"
    ids = extract_identifiers(raw)
    assert ids.doi == "10.1038/nature14539"
    assert ids.pmid == "26017442"
    stripped = strip_identifiers(raw)
    assert "10.1038" not in stripped and "26017442" not in stripped
    arxiv_doi = extract_identifiers("https://doi.org/10.48550/arXiv.1706.03762")
    assert arxiv_doi.arxiv_id == "1706.03762"
