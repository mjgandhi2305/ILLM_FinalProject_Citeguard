from pathlib import Path

from citeguard.domain.models import CitationType
from citeguard.ingest.bibtex import parse_bibtex
from citeguard.ingest.documents import sniff_kind
from citeguard.ingest.latex import parse_latex
from citeguard.ingest.text import extract_references
from citeguard.parse.heuristic import parse_heuristic

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_bibtex_fixture() -> None:
    refs, warnings = parse_bibtex((FIXTURES / "sample_mixed.bib").read_text())
    assert not warnings
    assert len(refs) == 8
    by_key = {r.key: r for r in refs}
    assert by_key["vaswani2017"].type == CitationType.PAPER_CONFERENCE
    assert by_key["vaswani2017"].authors[0].family == "Vaswani"
    assert by_key["fake_borrowed_doi"].ids.doi == "10.1038/nature14539"
    assert by_key["devlin2018bert"].ids.arxiv_id == "1810.04805"
    assert by_key["devlin2018bert"].type == CitationType.PREPRINT
    assert all(r.parse_method == "bibtex" for r in refs)


def test_heuristic_styles() -> None:
    apa = parse_heuristic(
        "Vaswani, A., Shazeer, N., & Polosukhin, I. (2017). Attention is all you need. "
        "Advances in Neural Information Processing Systems, 30, 5998–6008."
    )
    assert apa.title == "Attention is all you need"
    assert apa.year == 2017 and apa.volume == "30" and apa.pages == "5998-6008"
    assert apa.type == CitationType.PAPER_CONFERENCE

    ieee = parse_heuristic(
        '[3] A. Vaswani and N. Shazeer, "Attention is all you need," in Proc. NeurIPS, 2017.'
    )
    assert ieee.title == "Attention is all you need" and ieee.container_title == "Proc. NeurIPS"

    vancouver = parse_heuristic(
        "LeCun Y, Bengio Y, Hinton G. Deep learning. Nature. 2015;521(7553):436-44."
    )
    assert vancouver.title == "Deep learning" and vancouver.container_title == "Nature"
    assert [a.family for a in vancouver.authors] == ["LeCun", "Bengio", "Hinton"]

    chatbot = parse_heuristic(
        "1. Smith, J., & Lee, K. (2021). **Graph Transformers for Protein Folding**. "
        "*Nature Machine Intelligence*, 3(4), 211–223."
    )
    assert chatbot.title == "Graph Transformers for Protein Folding"
    assert chatbot.container_title == "Nature Machine Intelligence"
    assert [a.family for a in chatbot.authors] == ["Smith", "Lee"]


CHATBOT_ANSWER = """Transformers dominate NLP [1]. Deep learning revolutionised vision [2], see also [1, 2].

**References**

1. Vaswani, A., Shazeer, N., & Parmar, N. (2017). Attention is all you need. *Advances in Neural Information Processing Systems*, 30.
2. LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. *Nature*, 521(7553), 436–444. https://doi.org/10.1038/nature14539
"""


def test_text_extraction_with_contexts() -> None:
    found = extract_references(CHATBOT_ANSWER)
    assert len(found.entries) == 2
    assert found.labels == ["1", "2"]
    assert any("Transformers dominate" in s for s in found.contexts[0])
    assert any("revolutionised vision" in s for s in found.contexts[1])


def test_latex() -> None:
    tex = r"""
    Attention models \cite{vas17} changed NLP.
    \begin{thebibliography}{9}
    \bibitem{vas17} A.~Vaswani, N.~Shazeer, ``Attention is all you need,'' in \emph{NeurIPS}, 2017.
    \end{thebibliography}
    """
    refs, _ = parse_latex(tex)
    assert len(refs) == 1
    assert refs[0].key == "vas17" and refs[0].year == 2017
    assert refs[0].contexts


def test_sniff_kind() -> None:
    assert sniff_kind(b"%PDF-1.7 ...") == "pdf"
    assert sniff_kind(b"@article{x, title={y}}") == "bibtex"
    assert sniff_kind(b"plain text", "notes.md") == "text"


def test_all_caps_vancouver_title_is_split_correctly() -> None:
    r = parse_heuristic(
        "TERASHIMA T, MIZUHATA M. MOISTURE BEHAVIOUR IN POROUS WALLS. "
        "Journal of Architecture and Planning. 1996;61(488):1-8."
    )
    assert r.title == "MOISTURE BEHAVIOUR IN POROUS WALLS"
    assert r.container_title == "Journal of Architecture and Planning"
    assert [a.family for a in r.authors] == ["TERASHIMA", "MIZUHATA"]


def test_lowercase_vancouver_journal_is_not_glued_to_the_title() -> None:
    r = parse_heuristic(
        "TERASHIMA T, MIZUHATA M. Probabilistic Transformers for Crop Yield Estimation in "
        "Developing Countries. animal. 2008;2(6)."
    )
    assert r.title == "Probabilistic Transformers for Crop Yield Estimation in Developing Countries"
    assert r.container_title == "animal"
    assert r.year == 2008


def test_quoted_phrase_inside_apa_title() -> None:
    r = parse_heuristic(
        "Bellani, G., & Zuanetti, G. (2022). Introducing the “How to …” review article series. "
        "AboutOpen, 9, 10."
    )
    assert r.title == "Introducing the “How to …” review article series"
    assert r.container_title == "AboutOpen"
    v = parse_heuristic("Smith J. A “quoted” word in a title. Nature. 2015;5(2):1-3.")
    assert v.title == "A “quoted” word in a title"
    assert v.container_title == "Nature"
    # a quoted title straight after the year is still the title
    h = parse_heuristic('Smith, J. (2019) "Deep nets for things", Journal of Things, 3, 1-2.')
    assert h.title == "Deep nets for things"
    # IEEE: the quote follows the author list
    i = parse_heuristic(
        'Lorraine E. Maxwell and Suzanne L. Schechtman, "A study of social support in Korea," '
        "Bokjiwa munhwa dayangseong yeongu, vol. 5, no. 3, pp. 85–106, 2023."
    )
    assert i.title == "A study of social support in Korea"


def test_vancouver_names_with_particles_and_diacritics() -> None:
    r = parse_heuristic(
        "Hol JA, Lopez-Yurda MI, Van Tinteren H, Šubic-Kovač M, Helland Å, Ellis‐Barrett L, "
        "Du Plessis E, et al. Prognostic significance of age in Wilms tumour. PLOS ONE. "
        "2019;14(8):e0221373."
    )
    assert r.title == "Prognostic significance of age in Wilms tumour"
    assert r.container_title == "PLOS ONE"
    assert [a.family for a in r.authors] == [
        "Hol", "Lopez-Yurda", "Van Tinteren", "Šubic-Kovač", "Helland", "Ellis‐Barrett", "Du Plessis",
    ]  # fmt: skip


def test_author_list_title_has_low_confidence() -> None:
    r = parse_heuristic("Hol JA, Godzinski J, Vujanic G, et al Prognostic. PLOS ONE. 2019;14(8):1.")
    assert r.parse_confidence <= 0.3


def test_apa_volume_range_is_not_taken_for_pages() -> None:
    r = parse_heuristic(
        "Voss, T., & Bilger, G. (2001). Diffusion of 195Au in amorphous Si3N4 and Si4N3. "
        "Physica B Condensed Matter, 308-310, 431–433."
    )
    assert r.pages == "431-433"


def test_abbreviations_and_portuguese_initials() -> None:
    r = parse_heuristic(
        "Leonova IA, Емельянова АВ. Emergency medical calls to children in St. Petersburg for the "
        "period 2019–2022. EMERGENCY MEDICAL CARE. 2023;24(4):55-61."
    )
    assert (
        r.title == "Emergency medical calls to children in St. Petersburg for the period 2019–2022"
    )
    assert r.container_title == "EMERGENCY MEDICAL CARE"
    p = parse_heuristic(
        "Brito GMI, de Oliveira VMC, Borges BVdS, da Rocha SS, Avelino FVSD, et al. PREVENTION OF "
        "HIV IN PEOPLE WHO LIVE IN A STREET SITUATION. Revista Prevenção de Infecção e Saúde. 2018;4."
    )
    assert p.title == "PREVENTION OF HIV IN PEOPLE WHO LIVE IN A STREET SITUATION"
    assert [a.family for a in p.authors][:3] == ["Brito", "de Oliveira", "Borges"]
