"""Binary document → text. GROBID-based structured PDF parsing lives in `ingest/grobid.py`;
this module is the dependency-light fallback."""

from __future__ import annotations

import io
import re

MAX_PDF_PAGES = 300
# pdfium marks a hyphenation point at a line end with U+FFFE (sometimes a soft hyphen, U+00AD),
# often followed by the line break: "quan\ufffe\ntile" is the word "quantile". Left in, it breaks
# title matching (a real reference looks like it has a typo).
_SOFT_HYPHEN = re.compile(r"[\u00ad\ufffe]\r?\n?")


def strip_soft_hyphens(text: str) -> str:
    return _SOFT_HYPHEN.sub("", text)


PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


class UnsupportedDocumentError(ValueError):
    pass


def sniff_kind(data: bytes, filename: str | None = None) -> str:
    """Decide the input kind from magic bytes first, extension second."""
    name = (filename or "").lower()
    if data.startswith(PDF_MAGIC):
        return "pdf"
    if data.startswith(ZIP_MAGIC) and (name.endswith(".docx") or b"word/" in data[:4000]):
        return "docx"
    if name.endswith(".bib"):
        return "bibtex"
    if name.endswith(".tex"):
        return "latex"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedDocumentError("Unsupported binary file type") from exc
    stripped = text.lstrip()
    if stripped.startswith("@") and "{" in stripped[:200]:
        return "bibtex"
    if "\\begin{document}" in text or "\\bibitem" in text:
        return "latex"
    return "text"


def pdf_to_text(data: bytes, max_pages: int = MAX_PDF_PAGES) -> str:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(data))
    try:
        if len(pdf) > max_pages:
            raise UnsupportedDocumentError(f"PDF has {len(pdf)} pages (limit {max_pages})")
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            pages.append(textpage.get_text_range())
            textpage.close()
            page.close()
        return strip_soft_hyphens("\n".join(pages))
    finally:
        pdf.close()


def docx_to_text(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)
