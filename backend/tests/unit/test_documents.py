"""Binary document ingestion: real PDF / DOCX files built in-test, and GROBID TEI parsing."""

from __future__ import annotations

import io

from citeguard.domain.models import CitationType
from citeguard.ingest.documents import docx_to_text, pdf_to_text, sniff_kind
from citeguard.ingest.grobid import tei_to_references
from citeguard.ingest.text import extract_references

LINES = [
    "Transformers changed NLP [1]. Deep nets learn representations [2].",
    "References",
    '[1] A. Vaswani, N. Shazeer, "Attention is all you need," in Proc. NeurIPS, 2017.',
    '[2] Y. LeCun, Y. Bengio, G. Hinton, "Deep learning," Nature, vol. 521, pp. 436-444, 2015.',
]


def make_pdf(lines: list[str]) -> bytes:
    """Minimal single-page PDF (Helvetica text) with a correct xref table."""
    ops = ["BT", "/F1 10 Tf", "14 TL", "50 780 Td"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({escaped}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def test_pdf_text_extraction_and_reference_split() -> None:
    pdf = make_pdf(LINES)
    assert sniff_kind(pdf, "paper.pdf") == "pdf"
    text = pdf_to_text(pdf)
    assert "Attention is all you need" in text
    found = extract_references(text)
    assert len(found.entries) == 2
    assert found.contexts[0] and "Transformers" in found.contexts[0][0]


def test_docx_extraction() -> None:
    import docx

    document = docx.Document()
    for line in LINES:
        document.add_paragraph(line)
    buf = io.BytesIO()
    document.save(buf)
    data = buf.getvalue()
    assert sniff_kind(data, "paper.docx") == "docx"
    text = docx_to_text(data)
    assert len(extract_references(text).entries) == 2


TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
 <text><body>
  <div><p>Self-attention <ref type="bibr" target="#b0">[1]</ref> replaced recurrence.</p></div>
 </body>
 <back><div type="references"><listBibl>
  <biblStruct xml:id="b0">
   <analytic>
    <title level="a" type="main">Attention is all you need</title>
    <author><persName><forename type="first">Ashish</forename><surname>Vaswani</surname></persName></author>
    <author><persName><forename type="first">Noam</forename><surname>Shazeer</surname></persName></author>
   </analytic>
   <monogr>
    <title level="m">Advances in Neural Information Processing Systems</title>
    <imprint><date type="published" when="2017"/><biblScope unit="page" from="5998" to="6008"/></imprint>
   </monogr>
   <note type="raw_reference">A. Vaswani, N. Shazeer. Attention is all you need. NeurIPS 2017.</note>
  </biblStruct>
  <biblStruct xml:id="b1">
   <analytic>
    <title level="a" type="main">Deep learning</title>
    <author><persName><forename type="first">Yann</forename><surname>LeCun</surname></persName></author>
    <idno type="DOI">10.1038/nature14539</idno>
   </analytic>
   <monogr>
    <title level="j">Nature</title>
    <imprint><biblScope unit="volume">521</biblScope><date type="published" when="2015-05"/></imprint>
   </monogr>
  </biblStruct>
 </listBibl></div></back></text>
</TEI>"""


def test_grobid_tei_parsing() -> None:
    refs = tei_to_references(TEI)
    assert len(refs) == 2
    att, dl = refs
    assert att.title == "Attention is all you need"
    assert [a.family for a in att.authors] == ["Vaswani", "Shazeer"]
    assert att.year == 2017 and att.pages == "5998-6008"
    assert att.type == CitationType.PAPER_CONFERENCE and att.parse_method == "grobid"
    assert att.contexts and "Self-attention" in att.contexts[0]
    assert dl.ids.doi == "10.1038/nature14539" and dl.volume == "521"
    assert dl.type == CitationType.ARTICLE_JOURNAL and dl.container_title == "Nature"
