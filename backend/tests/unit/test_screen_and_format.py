from datetime import UTC, datetime

from citeguard.domain.models import Author, Identifiers, ParsedReference
from citeguard.screen.heuristics import screen
from citeguard.suggest.format import format_apa, format_bibtex, format_ieee
from tests.conftest import DEEP_LEARNING


def test_screen_signals() -> None:
    ref = ParsedReference(
        raw="",
        title="Something",
        year=2031,
        container_title="IEEE Transactions on Pattern Analysis and Machine Intelligence",
        pages="300-120",
        ids=Identifiers(doi="10.1145/1234567.1234568", arxiv_id="2203.01234"),
    )
    risk, signals = screen(ref, now=datetime(2026, 10, 29, tzinfo=UTC))
    codes = {s.code for s in signals}
    assert {"DOI_PUBLISHER_MISMATCH", "FUTURE_YEAR", "PAGES_REVERSED"} <= codes
    assert risk > 0.6


def test_screen_iclr_anachronism() -> None:
    ref = ParsedReference(raw="", title="X y z", year=2010, container_title="ICLR")
    _, signals = screen(ref)
    assert any(s.code == "VENUE_ANACHRONISM" for s in signals)


def test_clean_reference_has_no_risk() -> None:
    ref = ParsedReference(
        raw="",
        title="Deep learning",
        year=2015,
        container_title="Nature",
        authors=[Author(family="LeCun")],
        ids=Identifiers(doi="10.1038/nature14539"),
    )
    risk, signals = screen(ref)
    assert risk == 0.0 and not signals


def test_formatters() -> None:
    apa = format_apa(DEEP_LEARNING)
    assert apa.startswith("LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521")
    assert "https://doi.org/10.1038/nature14539" in apa
    ieee = format_ieee(DEEP_LEARNING)
    assert ieee.startswith('Y. LeCun, Y. Bengio, and G. Hinton, "Deep learning," Nature')
    bib = format_bibtex(DEEP_LEARNING)
    assert bib.startswith("@article{lecun2015deep,") and "doi = {10.1038/nature14539}" in bib
